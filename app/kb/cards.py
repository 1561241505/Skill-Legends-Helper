"""Card database loading and per-hero core-card selection."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR

CARDS_PATH = DATA_DIR / "cards.json"
RARITY_WEIGHT = {3: 110, 2: 60, 1: 22}


def load_cards() -> Dict[str, Any]:
    try:
        data = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("cards"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"meta": {}, "cards": []}


def pick_core_cards(
    hero: Dict[str, Any],
    card_data: Dict[str, Any],
    limit: int = 6,
    enabled: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Rank cards that match a hero's main/secondary schools.

    When ``enabled`` is supplied, only cards from schools available in the
    current draft are returned, so the plan never recommends a banned school.
    Dual-school cards are promoted because one purchase advances both schools.
    Rarity is a tie-breaker, not the only signal.
    """
    schools = {sid: float(weight) for sid, weight in (hero.get("schools") or {}).items() if float(weight) >= 0.5}
    if enabled is not None:
        allowed = set(enabled)
        schools = {sid: weight for sid, weight in schools.items() if sid in allowed}
    if not schools:
        return []
    main_school = max(schools, key=schools.get)
    ranked = []
    for card in card_data.get("cards", []):
        if enabled is not None and card.get("primary_faction") not in schools:
            # A card whose primary school is banned may still appear in the
            # other pool, but its text usually depends on the banned mechanic.
            continue
        factions = list(card.get("faction_ids") or [])
        hits = [sid for sid in factions if sid in schools]
        if not hits:
            continue
        dual = len(hits) >= 2
        primary_hit = card.get("primary_faction") in schools
        secondary_hit = card.get("secondary_faction") in schools
        rarity = int(card.get("rarity") or 1)
        score = RARITY_WEIGHT.get(rarity, 10)
        score += 30 if dual else 0
        score += 15 if primary_hit else 0
        score += 10 if secondary_hit else 0
        score += sum(schools[sid] for sid in hits) * 18
        if card.get("primary_faction") == main_school:
            score += 12
        # Slight penalty for cards that only touch an off-school secondary.
        if not primary_hit and not dual:
            score -= 8
        reason = "双流派" if dual else ("主系" if primary_hit else "副系")
        ranked.append(
            (
                score,
                rarity,
                -int(card.get("id") or 0),
                {
                    "id": card.get("id"),
                    "name": card.get("name"),
                    "rarity": rarity,
                    "rarity_name": card.get("rarity_name"),
                    "factions": card.get("factions") or [],
                    "desc": card.get("desc") or "",
                    "pool": card.get("pool"),
                    "reason": reason,
                    "affinity": round(sum(schools[sid] for sid in hits), 2),
                    "score": round(score, 1),
                },
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    # Keep at most two cards with the same primary faction so the plan is not
    # six near-identical attack cards from one school.
    selected: List[Dict[str, Any]] = []
    per_primary: Dict[str, int] = {}
    for _score, _rarity, _neg_id, payload in ranked:
        primary = None
        for faction in payload.get("factions") or []:
            primary = faction
            break
        if primary and per_primary.get(primary, 0) >= 2:
            continue
        selected.append(payload)
        if primary:
            per_primary[primary] = per_primary.get(primary, 0) + 1
        if len(selected) >= limit:
            break
    return selected
