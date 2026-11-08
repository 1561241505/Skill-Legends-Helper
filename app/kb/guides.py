"""Markdown guide storage with a tiny YAML-ish frontmatter parser."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import GUIDE_DIR, HEROES_PATH, load_json

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


@dataclass
class Guide:
    hero: str
    title: str
    meta: Dict[str, Any]
    body: str
    path: str
    sections: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def source(self) -> str:
        return str(self.meta.get("source", "") or "")

    @property
    def updated(self) -> str:
        return str(self.meta.get("updated", "") or "")


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        items = [_parse_value(x) for x in raw[1:-1].split(",")]
        return [x for x in items if x != ""]
    if "," in raw and all(":" not in part for part in raw.split(",")):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text.lstrip("\ufeff"))
    if not match:
        return {}, text
    meta: Dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_value(value)
    return meta, text[match.end():]


def split_sections(body: str) -> List[Tuple[str, str]]:
    sections: List[Tuple[str, str]] = []
    current_title = "概述"
    current_lines: List[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if "".join(current_lines).strip():
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if "".join(current_lines).strip():
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def parse_guide(text: str, path: Path) -> Optional[Guide]:
    meta, body = parse_frontmatter(text)
    hero = str(meta.get("hero", "") or "").strip()
    if not hero:
        return None
    title = str(meta.get("title", "") or hero).strip()
    return Guide(
        hero=hero,
        title=title,
        meta=meta,
        body=body.strip(),
        path=str(path),
        sections=split_sections(body),
    )


def load_guides() -> Dict[str, Guide]:
    guides: Dict[str, Guide] = {}
    if not GUIDE_DIR.exists():
        return guides
    for path in sorted(GUIDE_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        guide = parse_guide(text, path)
        if guide:
            guides[guide.hero] = guide
    return guides


def save_guide(hero: str, content: str) -> Guide:
    hero = (hero or "").strip()
    if not hero or any(ch in hero for ch in "\\/:*?\"<>|"):
        raise ValueError("英雄名称不合法")
    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    if not content.lstrip().startswith("---"):
        content = (
            "---\nhero: %s\ntitle: %s\npatch: \"2026.10\"\nsource: 手动录入\n"
            "updated: %s\n---\n\n%s" % (hero, hero, date.today().isoformat(), content)
        )
    path = GUIDE_DIR / (hero + ".md")
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    guide = parse_guide(path.read_text(encoding="utf-8"), path)
    if guide is None:
        raise ValueError("攻略必须包含 hero 字段（frontmatter）")
    return guide


def coverage() -> List[Dict[str, Any]]:
    data = load_json(HEROES_PATH, {}) or {}
    heroes = data.get("heroes", [])
    guides = load_guides()
    rows = []
    for hero in heroes:
        guide = guides.get(hero["name"])
        rows.append(
            {
                "name": hero["name"],
                "tier": hero.get("tier", ""),
                "has_guide": guide is not None,
                "title": guide.title if guide else "",
                "updated": guide.updated if guide else "",
                "sections": len(guide.sections) if guide else 0,
                "chars": len(guide.body) if guide else 0,
            }
        )
    return rows
