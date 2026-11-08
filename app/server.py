"""Local-only HTTP server for the 选技助手 web UI."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .config import (
    BASE_DIR,
    DATA_DIR,
    GUIDE_DIR,
    HERO_TEMPLATE_DIR,
    SAMPLES_DIR,
    STATIC_DIR,
    TEMPLATE_DIR,
    get_settings,
    load_json,
    save_settings,
)
from .kb import guides as guide_store
from .kb.recommend import Advisor
from .llm import generate_comment
from .vision import imageops
from .vision.recognizer import Recognizer

MAX_BODY = 24 * 1024 * 1024

# Set by agent.py when the floating HUD runs in the same process.
OVERLAY_TRIGGER = None

RECOGNIZER: Optional[Recognizer] = None
ADVISOR: Optional[Advisor] = None
INIT_LOCK = threading.Lock()


def init_engines() -> Tuple[Recognizer, Advisor]:
    global RECOGNIZER, ADVISOR
    with INIT_LOCK:
        if RECOGNIZER is None:
            RECOGNIZER = Recognizer()
        if ADVISOR is None:
            ADVISOR = Advisor()
        return RECOGNIZER, ADVISOR


GUIDE_TEMPLATE = """---
hero: 英雄名
title: 英雄名 · 核心流派攻略
tier: A
schools: 普攻流, 急速流
patch: "2026.10"
source: 我的实战笔记
updated: 2026-10-26
---

# 英雄名 · 核心流派攻略

## 一句话结论

一句话说明这个英雄什么局能选、什么局不能选。

## 核心机制

- 被动/大招的关键机制。
- 强势期与弱势期。

## 适配流派

1. **主系**：为什么契合。
2. **副系**：什么时候补。

## 开局抓牌顺序

- 前 3 回合拿什么。
- 4~10 回合的转型节点。
- 主系被禁用时的替代路线。

## 宝物与技能选择

- 必拿宝物。
- 技能加点优先级。

## 克制关系

- 怕什么流派。
- 克制什么流派。

## 常见失误

- 最容易犯的一个错误。
"""


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _mask_key(key: str) -> str:
    key = key or ""
    if len(key) <= 10:
        return ("*" * len(key)) if key else ""
    return key[:4] + "*" * 8 + key[-4:]


class Handler(BaseHTTPRequestHandler):
    server_version = "XuanJiAssistant/0.1"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- utilities
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, _json_bytes(data))

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> Dict[str, Any]:
        # Every POST body is consumed exactly once; cache it so the router can
        # drain it even for endpoints that don't need the payload.  Otherwise
        # leftover bytes would poison the next request on a keep-alive socket.
        # The cache is reset for every request in do_POST().
        if getattr(self, "_body_ready", False):
            return self._body_cache
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._body_cache = {}
            self._body_ready = True
            return self._body_cache
        if length > MAX_BODY:
            raise ValueError("上传内容过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("请求体不是合法的 JSON")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是对象")
        self._body_cache = data
        self._body_ready = True
        return data

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._serve_file(STATIC_DIR / "index.html")
            if path == "/library":
                return self._serve_file(STATIC_DIR / "library.html")
            if path.startswith("/static/"):
                return self._serve_file(STATIC_DIR / unquote(path[len("/static/"):]))
            if path.startswith("/data/templates/"):
                rel = unquote(path[len("/data/templates/"):])
                return self._serve_file(TEMPLATE_DIR / rel)
            if path == "/api/status":
                return self._status()
            if path == "/api/catalog":
                return self._catalog()
            if path == "/api/heroes":
                return self._heroes()
            if path == "/api/hero":
                return self._hero(parsed.query)
            if path == "/api/cards":
                return self._cards()
            if path == "/api/rules":
                return self._json({"ok": True, "rules": load_json(DATA_DIR / "rules.json", {})})
            if path == "/api/guides":
                return self._guides(parsed.query)
            if path == "/api/guide":
                return self._guide(parsed.query)
            if path == "/api/settings":
                return self._settings_get()
            if path == "/api/health":
                return self._json({"ok": True, "time": time.time()})
            self._error("Not found", 404)
        except Exception as exc:  # pragma: no cover - defensive
            traceback.print_exc()
            self._error("服务器错误：%s" % exc, 500)

    def _serve_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            allowed = any(
                resolved == root.resolve() or root.resolve() in resolved.parents
                for root in (STATIC_DIR, TEMPLATE_DIR)
            )
            if not allowed or not resolved.is_file():
                self._error("File not found", 404)
                return
            body = resolved.read_bytes()
            ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, body, ctype)
        except OSError:
            self._error("File not found", 404)

    def _status(self) -> None:
        rec, adv = init_engines()
        guide_map = guide_store.load_guides()
        portrait_count = len(rec.hero_templates)
        settings = get_settings()
        self._json(
            {
                "ok": True,
                "version": "0.1.0",
                "heroes": len(rec.heroes),
                "portraits": portrait_count,
                "schools": len(rec.schools),
                "guides": len(guide_map),
                "sample": (SAMPLES_DIR / "draft_001.png").exists(),
                "llm": {
                    "enabled": bool(settings["llm"].get("enabled")),
                    "key_set": bool(settings["llm"].get("api_key")),
                    "model": settings["llm"].get("model", ""),
                },
            }
        )

    def _catalog(self) -> None:
        rec, adv = init_engines()
        guide_map = guide_store.load_guides()
        schools = [
            {
                "id": s["id"],
                "name": s["name"],
                "short": s.get("short", s["name"]),
                "color": s.get("color", "#9aa4b2"),
                "icon": "/data/templates/schools/%s.png" % s["id"],
                "summary": s.get("summary", ""),
            }
            for s in rec.schools
        ]
        heroes = [
            {
                "name": h["name"],
                "aliases": h.get("aliases", []),
                "tier": h.get("tier", "?"),
                "role": h.get("role", ""),
                "power": h.get("power", 0),
                "portrait": "/" + h["portrait"] if h.get("portrait") else "",
                "has_guide": h["name"] in guide_map,
            }
            for h in rec.heroes
        ]
        self._json({"ok": True, "schools": schools, "heroes": heroes})

    def _heroes(self) -> None:
        _, adv = init_engines()
        guide_map = guide_store.load_guides()
        heroes = []
        for hero in adv.heroes:
            detail = adv.hero_detail(hero["name"])
            if detail:
                detail["has_guide"] = hero["name"] in guide_map
                detail["portrait"] = "/" + detail["portrait"] if detail.get("portrait") else ""
                heroes.append(detail)
        schools = []
        for school in adv.schools:
            schools.append(
                {
                    "id": school["id"],
                    "name": school["name"],
                    "short": school.get("short", school["name"]),
                    "color": school.get("color", "#9aa4b2"),
                    "icon": "/data/templates/schools/%s.png" % school["id"],
                    "faction_id": school.get("faction_id"),
                    "summary": school.get("summary", ""),
                    "mechanics": school.get("mechanics", ""),
                    "ban_impact": school.get("ban_impact", ""),
                    "card_count": school.get("card_count", 0),
                }
            )
        self._json(
            {
                "ok": True,
                "heroes": heroes,
                "schools": schools,
                "meta": {
                    "heroes": len(heroes),
                    "cards": len(adv.cards.get("cards", [])),
                    "guides": len(guide_map),
                    "tier_note": "强度为初始整理/面板估算，不是官方胜率；可在 data/heroes.json 校正。",
                },
            }
        )

    def _hero(self, query: str) -> None:
        params = parse_qs(query)
        name = (params.get("name") or [""])[0].strip()
        _, adv = init_engines()
        detail = adv.hero_detail(name)
        if not detail:
            self._error("未收录该英雄", 404)
            return
        detail["portrait"] = "/" + detail["portrait"] if detail.get("portrait") else ""
        self._json({"ok": True, "hero": detail})

    def _cards(self) -> None:
        _, adv = init_engines()
        self._json({"ok": True, **adv.cards})

    def _guides(self, query: str) -> None:
        params = parse_qs(query)
        hero = (params.get("hero") or [""])[0]
        if hero:
            return self._guide(query)
        rows = guide_store.coverage()
        self._json({"ok": True, "heroes": rows, "template": GUIDE_TEMPLATE})

    def _guide(self, query: str) -> None:
        params = parse_qs(query)
        hero = (params.get("hero") or [""])[0].strip()
        path = GUIDE_DIR / (hero + ".md")
        if not hero or not path.exists():
            self._json({"ok": True, "hero": hero, "content": "", "exists": False, "template": GUIDE_TEMPLATE})
            return
        self._json({"ok": True, "hero": hero, "content": path.read_text(encoding="utf-8"), "exists": True})

    def _settings_get(self) -> None:
        settings = get_settings()
        llm = dict(settings.get("llm", {}))
        llm["api_key"] = ""
        llm["api_key_masked"] = _mask_key(settings.get("llm", {}).get("api_key", ""))
        llm["api_key_set"] = bool(settings.get("llm", {}).get("api_key"))
        self._json({"ok": True, "llm": llm})

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            # A handler instance is reused for every request on a keep-alive
            # connection, so clear the previous body before draining this one.
            self._body_ready = False
            self._body_cache = {}
            # Drain the body before routing, even for /api/sample which ignores
            # its payload.  This keeps persistent connections in sync.
            self._body()
            if path == "/api/analyze":
                return self._analyze()
            if path == "/api/sample":
                return self._sample()
            if path == "/api/recommend":
                return self._recommend()
            if path == "/api/learn-hero":
                return self._learn_hero()
            if path == "/api/comment":
                return self._comment()
            if path == "/api/guide":
                return self._save_guide()
            if path == "/api/settings":
                return self._settings_post()
            if path == "/api/overlay/capture":
                callback = OVERLAY_TRIGGER
                if callback is None:
                    raise ValueError("浮窗助手未启动，请先运行 启动浮窗.bat")
                callback()
                return self._json({"ok": True})
            self._error("Not found", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except Exception as exc:  # pragma: no cover - defensive
            traceback.print_exc()
            self._error("服务器错误：%s" % exc, 500)

    def do_PUT(self) -> None:
        self.do_POST()

    def _analyze(self) -> None:
        body = self._body()
        data_url = body.get("image") or ""
        if not data_url:
            raise ValueError("缺少图片数据")
        rec, _ = init_engines()
        raw = imageops.decode_data_url(data_url)
        image = imageops.open_image(raw)
        if image.width < 640 or image.height < 360:
            raise ValueError("图片分辨率过低，请上传完整游戏截图")
        result = rec.analyze(image, debug=bool(body.get("debug")))
        result["ok"] = True
        self._json(result)

    def _sample(self) -> None:
        rec, _ = init_engines()
        path = SAMPLES_DIR / "draft_001.png"
        if not path.exists():
            raise ValueError("示例截图不存在")
        result = rec.analyze(imageops.open_image(path.read_bytes()), debug=False)
        result["ok"] = True
        self._json(result)

    def _recommend(self) -> None:
        body = self._body()
        heroes = body.get("heroes") or []
        enabled = body.get("enabled") or []
        banned = body.get("banned") or []
        if not isinstance(heroes, list) or not heroes:
            raise ValueError("请至少选择一个英雄")
        if len(enabled) != 8:
            raise ValueError("启用流派必须为 8 个")
        _, adv = init_engines()
        result = adv.recommend([str(h) for h in heroes], [str(s) for s in enabled], [str(s) for s in banned])
        result["ok"] = True
        self._json(result)

    def _learn_hero(self) -> None:
        body = self._body()
        name = (body.get("name") or "").strip()
        portrait = body.get("portrait") or ""
        if not name or not portrait:
            raise ValueError("缺少英雄名称或头像")
        rec, _ = init_engines()
        hero = rec.learn_hero(name, portrait)
        self._json({"ok": True, "hero": {"name": hero["name"], "id": hero["id"], "portrait": "/" + hero.get("portrait", "")}})

    def _comment(self) -> None:
        body = self._body()
        heroes = body.get("heroes") or []
        enabled = body.get("enabled") or []
        banned = body.get("banned") or []
        if len(enabled) != 8:
            raise ValueError("启用流派必须为 8 个")
        _, adv = init_engines()
        result = adv.recommend([str(h) for h in heroes], [str(s) for s in enabled], [str(s) for s in banned])
        text = generate_comment(get_settings(), result)
        self._json({"ok": True, "comment": text})

    def _save_guide(self) -> None:
        body = self._body()
        hero = (body.get("hero") or "").strip()
        content = body.get("content") or ""
        if not hero:
            raise ValueError("缺少英雄名称")
        if len(content) > 200_000:
            raise ValueError("攻略内容过长")
        guide = guide_store.save_guide(hero, content)
        _, adv = init_engines()
        adv.reload()
        self._json({"ok": True, "hero": guide.hero, "title": guide.title, "sections": len(guide.sections)})

    def _settings_post(self) -> None:
        body = self._body()
        llm = body.get("llm") or {}
        if not isinstance(llm, dict):
            raise ValueError("llm 必须是对象")
        payload: Dict[str, Any] = {}
        if "enabled" in llm:
            payload["enabled"] = bool(llm["enabled"])
        if "base_url" in llm:
            payload["base_url"] = str(llm["base_url"]).strip()
        if "model" in llm:
            payload["model"] = str(llm["model"]).strip()
        if "api_key" in llm and str(llm["api_key"]).strip():
            payload["api_key"] = str(llm["api_key"]).strip()
        if llm.get("clear_api_key"):
            payload["api_key"] = ""
        settings = save_settings({"llm": payload})
        self._json(
            {
                "ok": True,
                "llm": {
                    "enabled": settings["llm"].get("enabled"),
                    "base_url": settings["llm"].get("base_url"),
                    "model": settings["llm"].get("model"),
                    "api_key_set": bool(settings["llm"].get("api_key")),
                    "api_key_masked": _mask_key(settings["llm"].get("api_key", "")),
                },
            }
        )


class AssistantServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # noqa: D401
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def create_server(host: str = "127.0.0.1", port: int = 8777) -> Tuple[ThreadingHTTPServer, int]:
    init_engines()
    last_error = None
    candidates = [0] if port == 0 else range(port, port + 20)
    for candidate in candidates:
        try:
            httpd = AssistantServer((host, candidate), Handler)
            return httpd, int(httpd.server_address[1])
        except OSError as exc:
            last_error = exc
    raise RuntimeError("无法绑定端口：%s" % last_error)


def _open_browser(url: str) -> bool:
    """Ask Windows to open the URL with the default browser, then fall back."""
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def main(host: str = "127.0.0.1", port: int = 8777, open_browser: bool = True) -> None:
    httpd, actual = create_server(host, port)
    url = "http://%s:%d" % (host, actual)
    print("=" * 58, flush=True)
    print(" 选技大乱斗 · 开局助手", flush=True)
    print(" 已启动：%s" % url, flush=True)
    print(" 如果浏览器没有自动打开，请复制上面的地址手动访问。", flush=True)
    print(" 关闭此窗口或按 Ctrl+C 停止。", flush=True)
    print("=" * 58, flush=True)
    if open_browser:
        def _open_later():
            if not _open_browser(url):
                print("未能自动打开浏览器，请手动访问：%s" % url, flush=True)
        threading.Timer(0.9, _open_later).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
