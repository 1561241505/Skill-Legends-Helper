"""Import the supplied hero/card spreadsheets into the assistant's JSON data.

Sources (copied into data/source/):
  选技英雄数据.xlsx  - 60 heroes with base stats, talent, ultimate
  卡牌库.xlsx        - 156 cards with faction/rarity/base value/description
  游戏规则.txt        - attribute/economy/school mechanics

Run:
  python tools/import_game_data.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

SCHOOL_IDS = {
    1: "basic",
    2: "dodge",
    3: "crit",
    4: "life",
    5: "heal",
    6: "ultimate",
    7: "poison",
    8: "freeze",
    9: "shield",
    10: "vulnerable",
    11: "spirit",
    12: "rage",
    13: "haste",
}

SCHOOL_NAMES = {
    1: "普攻流", 2: "闪避流", 3: "暴击流", 4: "生命流", 5: "回复流",
    6: "大招流", 7: "中毒流", 8: "冰冻流", 9: "护盾流", 10: "易伤流",
    11: "精灵流", 12: "怒气流", 13: "急速流",
}

RARITY_NAMES = {1: "普通", 2: "稀有", 3: "传说"}

# Curated primary/secondary schools inferred from each hero's talent + ultimate.
# Weights are 0-1 and drive both the draft score and the core-card selection.
HERO_SCHOOLS: Dict[str, Dict[str, float]] = {
    "刀锋酋长": {"basic": 1.0, "spirit": 0.85, "crit": 0.5},
    "隐匿之刃": {"dodge": 1.0, "crit": 0.6, "basic": 0.5},
    "狂暴战将": {"crit": 1.0, "rage": 0.6, "basic": 0.5},
    "矮人领主": {"life": 1.0, "shield": 0.6, "vulnerable": 0.5},
    "熊猫武士": {"heal": 1.0, "life": 0.8, "shield": 0.4},
    "神秘法师": {"ultimate": 1.0, "spirit": 0.8, "haste": 0.6, "heal": 0.35},
    "剧毒巫师": {"poison": 1.0, "vulnerable": 0.6, "ultimate": 0.5},
    "极寒掌控者": {"freeze": 1.0, "crit": 0.5, "life": 0.4},
    "精灵牧师": {"spirit": 1.0, "heal": 0.8, "ultimate": 0.4},
    "森林游侠": {"basic": 0.95, "haste": 0.8, "spirit": 0.55, "crit": 0.45},
    "致命荆棘": {"life": 1.0, "vulnerable": 0.6, "ultimate": 0.4},
    "地精炮手": {"basic": 0.8, "haste": 0.8, "ultimate": 0.7},
    "渣客鼠王": {"poison": 0.9, "vulnerable": 0.7, "haste": 0.5},
    "部落勇士": {"shield": 1.0, "life": 0.8, "basic": 0.4},
    "浴血狂战": {"crit": 1.0, "life": 0.7, "basic": 0.5},
    "守财奴": {"ultimate": 0.8, "life": 0.6, "shield": 0.6, "basic": 0.5},
    "霸者龙神": {"life": 1.0, "spirit": 0.7, "shield": 0.5},
    "魔镜": {"basic": 0.9, "shield": 0.65, "crit": 0.5, "heal": 0.4},
    "混乱使徒": {"vulnerable": 0.9, "poison": 0.7, "spirit": 0.6},
    "恶魔之影": {"dodge": 1.0, "crit": 0.9, "basic": 0.4},
    "星界法师": {"ultimate": 1.0, "heal": 0.7, "haste": 0.6},
    "丛林先知": {"spirit": 1.0, "life": 0.6, "heal": 0.5},
    "毒龙骑士": {"poison": 0.9, "haste": 0.7, "basic": 0.6},
    "烈焰巨灵": {"ultimate": 1.0, "crit": 0.8, "rage": 0.5},
    "鱼人咒术士": {"poison": 1.0, "freeze": 0.9, "ultimate": 0.4},
    "烈焰法师": {"rage": 0.9, "ultimate": 0.8, "crit": 0.4},
    "沉默守卫": {"shield": 1.0, "rage": 0.8, "life": 0.5},
    "林地女妖": {"spirit": 1.0, "heal": 0.7, "life": 0.5},
    "地精投石车": {"shield": 1.0, "crit": 0.7, "basic": 0.5},
    "苦痛狱卒": {"rage": 0.9, "heal": 0.8, "life": 0.5},
    "鬼牌希科": {"ultimate": 0.7, "spirit": 0.6, "basic": 0.5},
    "皇家骑士": {"shield": 1.0, "heal": 0.7, "life": 0.5},
    "瘟疫术士": {"poison": 1.0, "vulnerable": 0.7, "heal": 0.7},
    "白虎射手": {"basic": 1.0, "haste": 0.8, "ultimate": 0.5},
    "霜影暴君": {"freeze": 0.9, "crit": 0.9, "basic": 0.5},
    "冰霜法师": {"freeze": 1.0, "ultimate": 0.7, "haste": 0.5},
    "炼金术士": {"vulnerable": 1.0, "heal": 0.8, "life": 0.5},
    "地精工匠": {"shield": 1.0, "vulnerable": 0.8, "dodge": 0.5, "freeze": 0.45, "heal": 0.45},
    "破魔者": {"dodge": 1.0, "basic": 0.8, "crit": 0.6},
    "树精守卫": {"spirit": 1.0, "shield": 0.9, "life": 0.5},
    "月隐猎手": {"basic": 0.9, "heal": 0.8, "haste": 0.5},
    "骸骨鸦医": {"vulnerable": 0.9, "shield": 0.8, "heal": 0.5},
    "赤刀修罗": {"rage": 1.0, "basic": 0.9, "haste": 0.5},
    "缝合巨怪": {"spirit": 1.0, "life": 0.8, "shield": 0.4},
    "长生梨妖": {"life": 0.8, "ultimate": 0.8, "heal": 0.5},
    "企鹅船长": {"heal": 1.0, "freeze": 0.8, "life": 0.5},
    "觅血蛛王": {"poison": 1.0, "crit": 0.7, "vulnerable": 0.4},
    "冰雪魔灵": {"freeze": 1.0, "basic": 0.8, "haste": 0.6},
    "辣椒射手": {"rage": 0.9, "vulnerable": 0.7, "basic": 0.5},
    "恶魔公爵": {"life": 0.9, "heal": 0.8, "shield": 0.4},
    "恶灵主母": {"ultimate": 1.0, "life": 0.7, "heal": 0.6},
    "矮人老兵": {"crit": 1.0, "basic": 0.8, "haste": 0.6},
    "赏金猎人": {"basic": 0.6, "spirit": 0.6, "life": 0.5, "ultimate": 0.5},
    "苍穹飓风": {"haste": 1.0, "ultimate": 0.7, "basic": 0.5},
    "先锋士兵": {"shield": 1.0, "crit": 0.8, "basic": 0.5},
    "罪恶克星": {"crit": 0.7, "ultimate": 0.6, "basic": 0.5},
    "星涡语者": {"ultimate": 0.9, "shield": 0.6, "haste": 0.5},
    "疾影剑卫": {"haste": 1.0, "ultimate": 0.7, "dodge": 0.4},
    "祷言圣女": {"heal": 1.0, "shield": 0.9, "life": 0.5},
    "枯樱石灵": {"spirit": 1.0, "basic": 0.7, "haste": 0.6},
}

OLD_NAME_MAP = {"熊猫武士": "熊猫", "恶灵主母": "恶灵祖母"}

EXTRA_ALIASES = {
    "刀锋酋长": ["刀锋", "酋长"],
    "隐匿之刃": ["隐匿", "隐刃"],
    "狂暴战将": ["狂暴", "战将"],
    "熊猫武士": ["熊猫", "熊猫人"],
    "神秘法师": ["大法师", "法师"],
    "剧毒巫师": ["毒法", "毒巫师"],
    "精灵牧师": ["精灵牧", "牧师"],
    "森林游侠": ["游侠", "森林"],
    "地精工匠": ["地精", "工匠"],
    "恶灵主母": ["恶灵祖母", "祖母", "主母"],
    "守财奴": ["财奴", "钱奴"],
    "星界法师": ["星界"],
    "赏金猎人": ["赏金"],
    "烈焰巨灵": ["巨灵", "火人"],
    "疾影剑卫": ["剑卫", "疾影"],
    "破魔者": ["破魔"],
    "矮人领主": ["矮人"],
}

ROLE_BY_SCHOOL = {
    "basic": "普攻输出",
    "ultimate": "大招法核",
    "poison": "中毒法系",
    "freeze": "冰冻控制",
    "shield": "护盾坦克",
    "heal": "回复辅助",
    "spirit": "精灵召唤",
    "crit": "暴击爆发",
    "dodge": "闪避刺客",
    "life": "生命战士",
    "rage": "怒气战士",
    "vulnerable": "易伤增幅",
    "haste": "急速频率",
}

COUNTERS = {
    "basic": ["freeze", "dodge"],
    "crit": ["shield", "dodge"],
    "ultimate": ["freeze", "crit"],
    "poison": ["crit"],
    "freeze": ["heal", "shield"],
    "shield": ["poison", "vulnerable"],
    "heal": ["vulnerable", "freeze"],
    "spirit": ["freeze", "vulnerable"],
    "dodge": ["poison", "vulnerable"],
    "rage": ["freeze", "shield"],
    "vulnerable": ["heal", "shield"],
    "haste": ["freeze", "shield"],
    "life": ["poison", "vulnerable"],
}

SCHOOL_MECHANICS = {
    "basic": "以普攻、攻速与攻击力为核心的持续输出；普攻触发类卡牌收益最高。",
    "ultimate": "能量满 100 自动释放大招；失去生命也会回复能量，围绕回能与大招频率构筑。",
    "shield": "每层护盾减少 1 点伤害（神圣伤害除外），减伤后层数降低，与易伤相互抵消。",
    "rage": "损失生命增加怒气；怒气达到 100 进入 2.5 秒狂怒，伤害增幅最高 85%。",
    "heal": "治疗、吸血与回复转伤；需要站场时间，怕易伤的高倍率爆发。",
    "poison": "每 0.7 秒受到等于当前中毒层数的中毒伤害，同时层数降低；适合处理高生命坦克。",
    "spirit": "学习精灵流技能后默认召唤 50 生命的小精灵，与英雄灵魂链分担 30% 伤害，多精灵共同分担。",
    "haste": "每层急速增加周期技能释放速度，每秒降低层数，与冰冻相互抵消。",
    "dodge": "每点闪避 = 1% 闪避率；默认只有物理伤害能被闪避。",
    "crit": "每点暴击 = 1% 暴击率；默认只有物理伤害可暴击，暴击伤害 200%。",
    "life": "提升最大生命、生命偷取与生命转伤，兼顾坦度与成长。",
    "freeze": "每层冰冻降低攻速与弹道速度，每秒降低层数，与急速相互抵消。",
    "vulnerable": "每层易伤使每次伤害额外 +1，结算后层数降低，与护盾相互抵消。",
}

RULES = {
    "source": "游戏规则.txt",
    "attributes": [
        {"name": "生命值", "text": "为 0 时战斗失败。"},
        {"name": "能量", "text": "初始 0，满 100 自动释放大招；失去生命也会回复能量。"},
        {"name": "攻击力", "text": "普攻伤害。"},
        {"name": "攻击速度", "text": "每秒普攻次数。"},
        {"name": "暴击", "text": "1 点 = 1% 暴击率；默认只有物理伤害可暴击，暴击伤害 200%。"},
        {"name": "闪避", "text": "1 点 = 1% 闪避率；默认只有物理伤害可被闪避。"},
    ],
    "economy": [
        "第一回合基础 300 金币；每轮自动获得 300~400 金币，随回合数增长。",
        "利息：每留存 100 金币，下一轮 +10 金币，上限 50。",
        "胜利 +50 金币；连胜每次 +10，最多 +30。",
        "败补：每被敌方玩家打掉 1 点玩家生命，+30 金币。",
        "金币用于购买技能（卡牌）。",
    ],
    "schools": SCHOOL_MECHANICS,
}

NEED_CLEAN = re.compile(r"\s+")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return NEED_CLEAN.sub("", str(value)).strip()


def fmt_number(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return text


def render_desc(template: str, base: Optional[float]) -> Tuple[str, bool]:
    if base is None:
        return template, False
    scaled = False

    def repl(match: re.Match) -> str:
        nonlocal scaled
        token = match.group(1)
        if token == "val":
            mult = 1
        elif token.startswith("val") and token[3:].isdigit():
            mult = int(token[3:])
        else:
            return match.group(0)
        if mult != 1:
            scaled = True
        return fmt_number(float(base) * mult)

    return re.sub(r"\{([^}]+)\}", repl, template), scaled


def panel_power(stats: Dict[str, float]) -> Tuple[float, float]:
    hp = max(0.0, min(1.0, (stats["hp"] - 1000) / 400.0))
    attack = max(0.0, min(1.0, (stats["attack"] - 17) / 9.0))
    speed = max(0.0, min(1.0, (stats["attack_speed"] - 1.6) / 1.4))
    energy = max(0.0, min(1.0, (stats["energy_regen"] - 9) / 6.0))
    dodge = max(0.0, min(1.0, (stats["dodge"] - 10) / 14.0))
    crit = max(0.0, min(1.0, (stats["crit"] - 12) / 12.0))
    panel = 0.28 * hp + 0.28 * attack + 0.18 * speed + 0.14 * energy + 0.06 * dodge + 0.06 * crit
    return round(70.0 + 18.0 * panel, 1), round(panel, 3)


def tier_for(power: float) -> str:
    if power >= 87:
        return "S"
    if power >= 82:
        return "A"
    if power >= 76:
        return "B"
    return "C"


def main() -> int:
    hero_wb = openpyxl.load_workbook(SOURCE / "选技英雄数据.xlsx", data_only=True)
    hero_rows = list(hero_wb["Sheet1"].iter_rows(min_row=2, values_only=True))
    hero_rows = [row for row in hero_rows if clean(row[0])]

    card_wb = openpyxl.load_workbook(SOURCE / "卡牌库.xlsx", data_only=True)
    card_rows = [row for row in card_wb["卡牌数据库"].iter_rows(min_row=2, values_only=True) if clean(row[1])]

    if len(hero_rows) != 60:
        raise SystemExit("expected 60 heroes, got %d" % len(hero_rows))
    if len(card_rows) != 156:
        raise SystemExit("expected 156 cards, got %d" % len(card_rows))

    old_data = json.loads((DATA / "heroes.json").read_text(encoding="utf-8"))
    old_by_name: Dict[str, Dict[str, Any]] = {}
    for hero in old_data.get("heroes", []):
        old_by_name[hero["name"]] = hero
        for alias in hero.get("aliases") or []:
            old_by_name.setdefault(alias, hero)

    heroes: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, row in enumerate(hero_rows, start=1):
        name = clean(row[0])
        stats = {
            "hp": int(row[1] or 0),
            "attack": int(row[2] or 0),
            "attack_speed": float(row[3] or 0),
            "energy_regen": int(row[4] or 0),
            "dodge": int(row[5] or 0),
            "crit": int(row[6] or 0),
        }
        talent = clean(row[7])
        ultimate = clean(row[8])
        schools = HERO_SCHOOLS.get(name)
        if not schools:
            raise SystemExit("missing school mapping for %s" % name)

        old = old_by_name.get(name) or old_by_name.get(OLD_NAME_MAP.get(name, ""))
        if old:
            hero_id = old["id"]
            tier = old.get("tier", "B")
            power = old.get("power", 75)
            role = old.get("role") or ROLE_BY_SCHOOL.get(max(schools, key=schools.get), "战士")
            difficulty = old.get("difficulty", 2)
            weak_to = old.get("weak_to") or COUNTERS.get(max(schools, key=schools.get), [])
            summary = old.get("summary") or ""
            portrait = old.get("portrait") or ""
            aliases = list(old.get("aliases") or [])
            tier_source = "社区示例"
        else:
            hero_id = "hero_%02d" % index
            power, panel = panel_power(stats)
            tier = tier_for(power)
            role = ROLE_BY_SCHOOL.get(max(schools, key=schools.get), "战士")
            difficulty = 3 if name in {"守财奴", "鬼牌希科", "罪恶克星", "赏金猎人", "长生梨妖"} else 2
            weak_to = COUNTERS.get(max(schools, key=schools.get), [])
            summary = "%s。天赋：%s；大招：%s" % (
                role,
                talent[:34].rstrip("。；， "),
                ultimate[:34].rstrip("。；， "),
            )
            portrait = ""
            aliases = []
            tier_source = "面板估算"

        if name == "矮人领主":
            role = "生命/护盾坦克"
            summary = "生命与护盾的坦克体系，靠最大生命成长和护盾拖后期；怕毒和易伤的高倍率伤害。"

        if not portrait:
            candidate = DATA / "templates" / "heroes" / (hero_id + ".png")
            if candidate.exists():
                portrait = "data/templates/heroes/%s.png" % hero_id

        for alias in EXTRA_ALIASES.get(name, []):
            aliases.append(alias)
        aliases = [a for a in dict.fromkeys(aliases) if a and a != name]
        if summary and "熊猫" in summary and name == "熊猫武士":
            summary = summary.replace("熊猫", "熊猫武士")
        if summary and "恶灵祖母" in summary and name == "恶灵主母":
            summary = summary.replace("恶灵祖母", "恶灵主母")

        if hero_id in seen_ids:
            raise SystemExit("duplicate hero id %s" % hero_id)
        seen_ids.add(hero_id)

        heroes.append(
            {
                "id": hero_id,
                "name": name,
                "aliases": aliases,
                "role": role,
                "difficulty": difficulty,
                "tier": tier,
                "tier_source": tier_source,
                "power": power,
                "schools": schools,
                "weak_to": weak_to,
                "summary": summary,
                "portrait": portrait,
                "stats": stats,
                "talent": talent,
                "ultimate": ultimate,
                "source": "选技英雄数据.xlsx / 卡牌库.xlsx / 游戏规则.txt",
            }
        )

    missing = set(HERO_SCHOOLS) - {h["name"] for h in heroes}
    if missing:
        raise SystemExit("school mapping has extra heroes: %s" % missing)

    (DATA / "heroes.json").write_text(
        json.dumps(
            {
                "meta": {
                    "patch": "2026.11",
                    "count": len(heroes),
                    "note": "英雄基础属性、天赋、大招来自选技英雄数据.xlsx；流派契合与强度为初始整理/面板估算，可在本文件中校正。",
                    "sources": ["选技英雄数据.xlsx", "卡牌库.xlsx", "游戏规则.txt"],
                },
                "heroes": heroes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cards: List[Dict[str, Any]] = []
    by_rarity: Dict[str, int] = {}
    by_school: Dict[str, int] = {sid: 0 for sid in SCHOOL_IDS.values()}
    for row in card_rows:
        card_id = int(row[0])
        name = clean(row[1])
        rarity = int(row[2]) if row[2] is not None else 1
        f1 = int(row[3]) if row[3] is not None else None
        f2 = int(row[4]) if row[4] is not None else None
        pool = int(row[5]) if row[5] is not None else 0
        base = float(row[6]) if row[6] is not None else None
        template = clean(row[7])
        desc, scaled = render_desc(template, base)
        faction_ids = [SCHOOL_IDS[x] for x in (f1, f2) if x in SCHOOL_IDS]
        faction_names = [SCHOOL_NAMES[x] for x in (f1, f2) if x in SCHOOL_NAMES]
        for sid in faction_ids:
            by_school[sid] = by_school.get(sid, 0) + 1
        by_rarity[RARITY_NAMES[rarity]] = by_rarity.get(RARITY_NAMES[rarity], 0) + 1
        cards.append(
            {
                "id": card_id,
                "name": name,
                "rarity": rarity,
                "rarity_name": RARITY_NAMES.get(rarity, "普通"),
                "faction_ids": faction_ids,
                "factions": faction_names,
                "primary_faction": SCHOOL_IDS.get(f1),
                "secondary_faction": SCHOOL_IDS.get(f2),
                "pool": pool,
                "base_value": base,
                "desc_template": template,
                "desc": desc,
                "scaled_values": scaled,
                "value_note": (
                    "源表只提供基础值；{valN} 按基础值 × N 展示，实际以游戏内卡牌等级为准。"
                    if scaled
                    else ""
                ),
            }
        )

    (DATA / "cards.json").write_text(
        json.dumps(
            {
                "meta": {
                    "count": len(cards),
                    "rarity_names": RARITY_NAMES,
                    "faction_map": {str(k): SCHOOL_IDS[k] for k in SCHOOL_IDS},
                    "faction_names": {str(k): SCHOOL_NAMES[k] for k in SCHOOL_NAMES},
                    "by_rarity": by_rarity,
                    "by_school": by_school,
                    "note": "卡牌数据来自卡牌库.xlsx；源表只提供基础值，{valN} 按基础值乘 N 展示。",
                },
                "cards": cards,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    school_data = json.loads((DATA / "schools.json").read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in school_data["schools"]}
    for fid, name in SCHOOL_NAMES.items():
        school = by_name[name]
        school["faction_id"] = fid
        school["mechanics"] = SCHOOL_MECHANICS[SCHOOL_IDS[fid]]
        school["card_count"] = by_school.get(SCHOOL_IDS[fid], 0)
    school_data.setdefault("meta", {})["source"] = "游戏规则.txt / 卡牌库.xlsx"
    (DATA / "schools.json").write_text(json.dumps(school_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (DATA / "rules.json").write_text(json.dumps(RULES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    old_guide = DATA / "guides" / "熊猫.md"
    new_guide = DATA / "guides" / "熊猫武士.md"
    if old_guide.exists():
        text = old_guide.read_text(encoding="utf-8")
        text = re.sub(r"熊猫(?!武士)", "熊猫武士", text)
        new_guide.write_text(text, encoding="utf-8")
        old_guide.unlink()

    print("heroes:", len(heroes))
    print("cards:", len(cards), "by rarity", by_rarity, "per school", by_school)
    print("schools:", len(school_data["schools"]))
    print("guides:", sorted(p.name for p in (DATA / "guides").glob("*.md")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
