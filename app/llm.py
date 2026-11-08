"""Optional OpenAI-compatible LLM commentary (grounded on retrieved evidence)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict

SYSTEM_PROMPT = (
    "你是《选技大乱斗》的开局 BP 教练。根据玩家提供的本局启用/禁用流派、三个候选英雄、"
    "评分与攻略摘录，给出简洁、可执行的中文建议。只能使用给定信息，不要编造不存在的机制或数值。"
    "输出 120~180 字：先给结论，再给 2 条理由，最后给 1 条开局操作建议。不要使用 Markdown 标题。"
)


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("未配置 API 地址")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def build_user_prompt(result: Dict[str, Any], limit_evidence: int = 2) -> str:
    draft = result.get("draft", {})
    lines = [
        "本局启用流派：" + "、".join(s.get("name", "") for s in draft.get("enabled", [])),
        "本局禁用流派：" + "、".join(s.get("name", "") for s in draft.get("banned", [])),
        "候选英雄与评分：",
    ]
    for card in result.get("recommendations", []):
        lines.append(
            "- %s：%s 分，定位 %s，评价 %s；开局路线：%s"
            % (
                card.get("name", ""),
                card.get("score", ""),
                card.get("role", ""),
                "；".join(card.get("reasons", [])[:2]),
                "；".join(card.get("build", {}).get("steps", [])[:3]),
            )
        )
        for ev in (card.get("evidence") or [])[:limit_evidence]:
            lines.append("  攻略摘录[%s]：%s" % (ev.get("section", ""), ev.get("text", "")))
    lines.append("请按系统要求给出建议，不要复述完整列表。")
    return "\n".join(lines)


def generate_comment(settings: Dict[str, Any], result: Dict[str, Any]) -> str:
    llm = settings.get("llm", {}) if settings else {}
    if not llm.get("enabled"):
        raise ValueError("LLM 点评未启用")
    api_key = (llm.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("尚未配置 API Key")
    payload = {
        "model": llm.get("model") or "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(result)},
        ],
        "temperature": 0.4,
        "max_tokens": 500,
        "stream": False,
    }
    req = urllib.request.Request(
        _endpoint(llm.get("base_url", "")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    timeout = float(llm.get("timeout") or 45)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("模型接口返回 %s：%s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise RuntimeError("连接模型接口失败：%s" % exc.reason)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("模型返回格式无法解析")
    return str(content).strip()
