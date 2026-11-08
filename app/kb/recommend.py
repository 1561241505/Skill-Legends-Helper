"""Draft analysis, retrieval-augmented evidence and hero scoring.

The recommendation is deterministic and explainable; RAG evidence is attached
to every candidate so a human (or the optional LLM) can verify the reasoning.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..config import HEROES_PATH, SCHOOLS_PATH, load_json
from .cards import load_cards, pick_core_cards
from .guides import load_guides
from .index import GuideIndex


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _pct(value: float) -> str:
    return "%d%%" % int(round(value * 100))


class Advisor:
    def __init__(self) -> None:
        self.schools: List[Dict[str, Any]] = []
        self.school_by_id: Dict[str, Dict[str, Any]] = {}
        self.heroes: List[Dict[str, Any]] = []
        self.hero_by_name: Dict[str, Dict[str, Any]] = {}
        self.guides = {}
        self.index = GuideIndex({})
        self.cards: Dict[str, Any] = {"meta": {}, "cards": []}
        self.stats: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        school_data = load_json(SCHOOLS_PATH, {}) or {}
        self.schools = school_data.get("schools", [])
        self.school_by_id = {s["id"]: s for s in self.schools}
        hero_data = load_json(HEROES_PATH, {}) or {}
        self.heroes = hero_data.get("heroes", [])
        self.hero_by_name = {h["name"]: h for h in self.heroes}
        self.guides = load_guides()
        self.index = GuideIndex(self.guides)
        self.cards = load_cards()
        self.stats = (load_json(HEROES_PATH.parent / "meta_stats.json", {}) or {}).get("heroes", {})

    # ------------------------------------------------------------------ utils
    def resolve_hero(self, name: str) -> Tuple[Optional[Dict[str, Any]], str]:
        name = (name or "").strip()
        if not name:
            return None, ""
        if name in self.hero_by_name:
            return self.hero_by_name[name], name
        for hero in self.heroes:
            if name in (hero.get("aliases") or []):
                return hero, name
        for hero in self.heroes:
            if name and (name in hero["name"] or hero["name"] in name):
                return hero, name
        return None, name

    def _school(self, sid: str) -> Dict[str, Any]:
        return self.school_by_id.get(sid, {"id": sid, "name": sid, "color": "#9aa4b2", "summary": "", "ban_impact": ""})

    def core_cards(
        self, hero: Dict[str, Any], limit: int = 6, enabled: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        return pick_core_cards(hero, self.cards, limit, enabled=enabled)

    def hero_detail(self, value: str) -> Optional[Dict[str, Any]]:
        hero, _matched = self.resolve_hero(value)
        if hero is None:
            return None
        guide = self._guide(hero["name"])
        schools = []
        for sid, weight in sorted((hero.get("schools") or {}).items(), key=lambda item: -item[1]):
            school = self._school(sid)
            schools.append(
                {
                    "id": sid,
                    "name": school.get("name", sid),
                    "color": school.get("color", "#9aa4b2"),
                    "icon": "/data/templates/schools/%s.png" % sid,
                    "weight": round(float(weight), 2),
                    "summary": school.get("summary", ""),
                    "mechanics": school.get("mechanics", ""),
                }
            )
        return {
            "id": hero.get("id"),
            "name": hero["name"],
            "aliases": hero.get("aliases", []),
            "role": hero.get("role", ""),
            "difficulty": hero.get("difficulty", 2),
            "tier": hero.get("tier", "?"),
            "tier_source": hero.get("tier_source", ""),
            "power": hero.get("power", 0),
            "portrait": hero.get("portrait", ""),
            "art": hero.get("art", ""),
            "talent_icon": hero.get("talent_icon", ""),
            "ultimate_icon": hero.get("ultimate_icon", ""),
            "summary": hero.get("summary", ""),
            "stats": hero.get("stats", {}),
            "talent": hero.get("talent", ""),
            "ultimate": hero.get("ultimate", ""),
            "schools": schools,
            "weak_to": [
                {
                    "id": sid,
                    "name": self._school(sid).get("name", sid),
                    "color": self._school(sid).get("color", "#9aa4b2"),
                }
                for sid in (hero.get("weak_to") or [])
            ],
            "core_cards": self.core_cards(hero),
            "has_guide": guide is not None,
            "guide_title": guide.title if guide else "",
            "guide_sections": len(guide.sections) if guide else 0,
            "source": hero.get("source", ""),
        }

    def _guide(self, hero_name: str):
        return self.guides.get(hero_name)

    def _section_text(self, hero_name: str, keyword: str) -> str:
        guide = self._guide(hero_name)
        if not guide:
            return ""
        for title, text in guide.sections:
            if keyword in title:
                return text
        return ""

    def _first_bullets(self, text: str, limit: int = 2) -> List[str]:
        bullets = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(("-", "*", "•")):
                bullets.append(line.lstrip("-*• ").strip())
            if len(bullets) >= limit:
                break
        return bullets

    @staticmethod
    def _plain(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = text.replace("`", "")
        text = text.replace("**", "")
        return text

    @classmethod
    def _trim(cls, text: str, limit: int = 240) -> str:
        text = re.sub(r"\n{2,}", "\n", cls._plain(text)).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "…"

    # --------------------------------------------------------------- scoring
    def score_hero(self, hero: Dict[str, Any], enabled: List[str], banned: List[str]) -> Dict[str, Any]:
        aff: Dict[str, float] = hero.get("schools") or {}
        enabled_set, banned_set = set(enabled), set(banned)
        base = float(hero.get("power", 70))

        syn_raw = sum(w for sid, w in aff.items() if sid in enabled_set)
        synergy = _clamp(30.0 + 28.0 * syn_raw)

        env = 55.0
        main_enabled = [sid for sid, w in aff.items() if w >= 0.75 and sid in enabled_set]
        main_banned = [sid for sid, w in aff.items() if w >= 0.75 and sid in banned_set]
        env += 8.0 * len(main_enabled)
        env -= 14.0 * len(main_banned)
        for sid in hero.get("weak_to") or []:
            env += 7.0 if sid in banned_set else -7.0
        if not any(sid in enabled_set for sid in aff):
            env -= 12.0
        env = _clamp(env)

        stat = self.stats.get(hero["name"], {})
        win_rate = stat.get("win_rate")
        if isinstance(win_rate, (int, float)) and win_rate > 0:
            meta = _clamp(50.0 + (float(win_rate) - 0.5) * 300.0)
        else:
            meta = 50.0

        enabled_aff = sorted([(sid, w) for sid, w in aff.items() if sid in enabled_set], key=lambda x: -x[1])
        flex_bonus = min(4.0, 1.3 * len([1 for _, w in enabled_aff if w >= 0.5]))
        final = 0.42 * base + 0.30 * synergy + 0.18 * env + 0.10 * meta + flex_bonus
        score = _clamp(final)

        return {
            "score": round(score, 1),
            "breakdown": {
                "base": round(base, 1),
                "synergy": round(synergy, 1),
                "environment": round(env, 1),
                "meta": round(meta, 1),
                "flex": round(flex_bonus, 1),
            },
            "enabled_affinity": [(self._school(sid), w) for sid, w in enabled_aff],
            "banned_affinity": [(self._school(sid), w) for sid, w in sorted(aff.items(), key=lambda x: -x[1]) if sid in banned_set],
            "main_enabled": [self._school(sid) for sid in main_enabled],
            "main_banned": [self._school(sid) for sid in main_banned],
            "syn_raw": round(syn_raw, 2),
        }

    def _reasons(self, hero: Dict[str, Any], scored: Dict[str, Any], enabled: List[str], banned: List[str]) -> List[str]:
        reasons: List[str] = []
        enabled_aff = scored["enabled_affinity"]
        banned_aff = scored["banned_affinity"]
        if enabled_aff:
            top = enabled_aff[:2]
            reasons.append(
                "本局 %s 开放，与英雄机制契合（%s）。"
                % ("、".join(s["name"] for s, _ in top), "、".join(_pct(w) for _, w in top))
            )
        if len(enabled_aff) >= 2:
            reasons.append("可以走「%s + %s」的双修路线，成型后比单系更稳。" % (enabled_aff[0][0]["name"], enabled_aff[1][0]["name"]))
        if banned_aff and banned_aff[0][1] >= 0.6:
            worst = banned_aff[0]
            reasons.append("核心流派 %s 被禁用（契合度 %s），强度会打折扣。" % (worst[0]["name"], _pct(worst[1])))
        weak_banned = [self._school(sid) for sid in (hero.get("weak_to") or []) if sid in set(banned)]
        weak_enabled = [self._school(sid) for sid in (hero.get("weak_to") or []) if sid in set(enabled)]
        if weak_banned:
            reasons.append("克制本英雄的 %s 本局被禁用，生存环境变好。" % "、".join(s["name"] for s in weak_banned))
        if weak_enabled:
            reasons.append("注意 %s 开放，对局中需要预留反制手段。" % "、".join(s["name"] for s in weak_enabled))
        guide = self._guide(hero["name"])
        if guide:
            conclusion = self._section_text(hero["name"], "一句话结论")
            if conclusion:
                first = re.sub(r"\s+", " ", self._plain(conclusion)).strip()
                reasons.append(self._trim(first, 110))
            else:
                reasons.append("攻略库中已有该英雄的完整攻略，可直接参考开局路线。")
        else:
            reasons.append("攻略库暂无该英雄的详细攻略，结论主要来自结构化数据，建议谨慎参考。")
        return reasons[:6]

    def _risks(self, hero: Dict[str, Any], scored: Dict[str, Any], enabled: List[str], banned: List[str]) -> List[str]:
        risks: List[str] = []
        for school, weight in scored["banned_affinity"]:
            if weight >= 0.6:
                risks.append("%s 被禁用，主体系无法满配。" % school["name"])
        for sid in hero.get("weak_to") or []:
            if sid in set(enabled):
                school = self._school(sid)
                risks.append("%s 开放，对手有克制手段。" % school["name"])
        guide = self._guide(hero["name"])
        if guide:
            mistakes = self._section_text(hero["name"], "常见失误")
            for bullet in self._first_bullets(mistakes, 2):
                risks.append(bullet)
            if not mistakes:
                caution = self._section_text(hero["name"], "克制关系")
                for bullet in self._first_bullets(caution, 1):
                    risks.append(bullet)
        if not risks:
            risks.append("没有明显的体系冲突，按正常节奏运营即可。")
        # de-duplicate while keeping order
        seen = set()
        unique = []
        for risk in risks:
            if risk not in seen:
                seen.add(risk)
                unique.append(risk)
        return unique[:4]

    def _build(self, hero: Dict[str, Any], scored: Dict[str, Any], enabled: List[str]) -> Dict[str, Any]:
        names = [s["name"] for s, w in scored["enabled_affinity"] if w >= 0.5][:3]
        plan = []
        if names:
            plan.append("主路线：%s" % names[0])
            if len(names) > 1:
                plan.append("副路线：%s" % " / ".join(names[1:]))
        else:
            plan.append("本局没有高度契合的流派，建议换人。")
        opening = self._section_text(hero["name"], "开局抓牌")
        bullets = self._first_bullets(opening, 2)
        if bullets:
            plan.extend(bullets)
        else:
            plan.append("前 3 回合先补生存，4~10 回合集中堆主系，别同时开太多副系。")
        return {"schools": names, "steps": plan}

    def _evidence(self, hero_name: str, enabled: List[str], banned: List[str]) -> List[Dict[str, Any]]:
        query_parts = [hero_name] + [self._school(s)["name"] for s in enabled] + [self._school(s)["name"] for s in banned]
        query = " ".join(query_parts) + " 开局 抓牌 宝物 克制 强度"
        results = self.index.search_any(query, hero=hero_name, top_k=3)
        out = []
        for item in results:
            out.append(
                {
                    "section": item["section"],
                    "text": self._trim(item["text"], 260),
                    "score": item["score"],
                    "source": item["source"],
                    "title": item["title"],
                    "same_hero": item["hero"] == hero_name,
                }
            )
        return out

    def _confidence(self, scored: Dict[str, Any], margin: float, has_guide: bool) -> str:
        if not has_guide:
            return "low"
        if margin >= 4 and scored["score"] >= 70:
            return "high"
        if margin >= 2:
            return "medium"
        return "low"

    def recommend(self, hero_names: List[str], enabled: List[str], banned: List[str]) -> Dict[str, Any]:
        enabled = [s for s in dict.fromkeys(enabled) if s in self.school_by_id]
        banned = [s for s in dict.fromkeys(banned) if s in self.school_by_id and s not in enabled]
        if len(enabled) + len(banned) != 13:
            # keep it robust: fill missing ids so the environment block still renders
            missing = [s["id"] for s in self.schools if s["id"] not in enabled and s["id"] not in banned]
            if len(enabled) < 8:
                enabled += missing[: 8 - len(enabled)]
            banned = [s["id"] for s in self.schools if s["id"] not in enabled]

        candidates = []
        for raw_name in hero_names:
            hero, matched_name = self.resolve_hero(raw_name)
            if hero is None:
                hero = {
                    "name": (raw_name or "未知英雄").strip() or "未知英雄",
                    "aliases": [],
                    "tier": "?",
                    "power": 65,
                    "role": "未收录",
                    "difficulty": 2,
                    "schools": {},
                    "weak_to": [],
                    "summary": "该英雄尚未收录，只能给出保守估计。",
                    "portrait": "",
                }
                matched_name = hero["name"]
            scored = self.score_hero(hero, enabled, banned)
            guide = self._guide(hero["name"])
            candidates.append(
                {
                    "hero": hero,
                    "scored": scored,
                    "has_guide": guide is not None,
                    "guide_title": guide.title if guide else "",
                }
            )

        candidates.sort(key=lambda c: c["scored"]["score"], reverse=True)
        top_score = candidates[0]["scored"]["score"] if candidates else 0.0
        second_score = candidates[1]["scored"]["score"] if len(candidates) > 1 else 0.0
        margin = top_score - second_score

        cards = []
        for rank, cand in enumerate(candidates, 1):
            hero = cand["hero"]
            scored = cand["scored"]
            card_margin = top_score - scored["score"]
            cards.append(
                {
                    "rank": rank,
                    "name": hero["name"],
                    "tier": hero.get("tier", "?"),
                    "role": hero.get("role", ""),
                    "power": hero.get("power", 0),
                    "difficulty": hero.get("difficulty", 2),
                    "portrait": hero.get("portrait", ""),
                    "art": hero.get("art", ""),
                    "talent_icon": hero.get("talent_icon", ""),
                    "ultimate_icon": hero.get("ultimate_icon", ""),
                    "summary": hero.get("summary", ""),
                    "score": scored["score"],
                    "breakdown": scored["breakdown"],
                    "confidence": self._confidence(scored, margin, cand["has_guide"]) if rank == 1 else "backup",
                    "has_guide": cand["has_guide"],
                    "guide_title": cand["guide_title"],
                    "stats": hero.get("stats", {}),
                    "talent": hero.get("talent", ""),
                    "ultimate": hero.get("ultimate", ""),
                    "tier_source": hero.get("tier_source", ""),
                    "core_cards": self.core_cards(hero, enabled=enabled),
                    "reasons": self._reasons(hero, scored, enabled, banned),
                    "risks": self._risks(hero, scored, enabled, banned),
                    "build": self._build(hero, scored, enabled),
                    "evidence": self._evidence(hero["name"], enabled, banned),
                }
            )

        env_notes = self._environment_notes(enabled, banned)
        top = cards[0] if cards else {}
        if cards and len(cards) > 1 and margin < 3:
            verdict = "三个英雄的评分非常接近，建议优先选择你最熟练、且主系开放的英雄。"
        elif cards:
            verdict = "建议首选 %s：%s" % (top["name"], top["reasons"][0] if top["reasons"] else "本局契合度最高。")
        else:
            verdict = "没有可分析的英雄，请先识别或手动选择。"

        return {
            "draft": {
                "heroes": [c["name"] for c in cards],
                "enabled": [self._school(s) for s in enabled],
                "banned": [self._school(s) for s in banned],
            },
            "verdict": verdict,
            "margin": round(margin, 1),
            "environment": {
                "notes": env_notes,
                "enabled_count": len(enabled),
                "banned_count": len(banned),
            },
            "recommendations": cards,
        }

    def _environment_notes(self, enabled: List[str], banned: List[str]) -> List[str]:
        notes: List[str] = []
        enabled_set = set(enabled)
        pairs = []
        for sid in enabled:
            school = self._school(sid)
            for other in school.get("pairs") or []:
                if other in enabled_set and (other, sid) not in pairs and (sid, other) not in pairs:
                    pairs.append((sid, other))
        for a, b in pairs[:2]:
            sa, sb = self._school(a), self._school(b)
            summary = (sa.get("summary", "") or "").rstrip("。")
            notes.append("「%s + %s」同时开放：%s，可以组成双修体系。" % (sa["name"], sb["name"], summary))
        for sid in banned:
            school = self._school(sid)
            notes.append("%s 被禁用：%s" % (school["name"], school.get("ban_impact", "")))
        return notes
