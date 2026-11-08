import json
import unittest
from pathlib import Path

from PIL import Image

from app.kb.guides import load_guides
from app.kb.recommend import Advisor

ROOT = Path(__file__).resolve().parent.parent


class GameDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = Advisor()

    def test_counts(self):
        self.assertEqual(len(self.advisor.heroes), 60)
        self.assertEqual(len(self.advisor.cards.get("cards", [])), 156)
        self.assertEqual(len(self.advisor.schools), 13)

    def test_school_metadata(self):
        by_name = {s["name"]: s for s in self.advisor.schools}
        self.assertEqual(by_name["中毒流"]["faction_id"], 7)
        self.assertIn("0.7", by_name["中毒流"]["mechanics"])
        self.assertEqual(by_name["精灵流"]["faction_id"], 11)

    def test_hero_stats_and_skills(self):
        hero, _ = self.advisor.resolve_hero("神秘法师")
        self.assertEqual(hero["stats"]["hp"], 1100)
        self.assertEqual(hero["stats"]["energy_regen"], 15)
        self.assertIn("大招", hero["talent"])
        self.assertIn("法球", hero["ultimate"])
        mirror, _ = self.advisor.resolve_hero("魔镜")
        self.assertEqual(mirror["stats"]["attack"], 26)
        self.assertEqual(mirror["stats"]["attack_speed"], 0)

    def test_cards_are_rendered(self):
        cards = {c["id"]: c for c in self.advisor.cards["cards"]}
        self.assertIn("中毒", cards[102]["desc"])
        self.assertEqual(cards[102]["factions"], ["普攻流", "中毒流"])
        self.assertTrue(cards[110]["scaled_values"])
        self.assertIn("12", cards[110]["desc"])

    def test_core_cards(self):
        hero, _ = self.advisor.resolve_hero("神秘法师")
        cards = self.advisor.core_cards(hero)
        self.assertGreaterEqual(len(cards), 5)
        names = [c["name"] for c in cards]
        self.assertTrue(any(c["rarity"] == 3 for c in cards))
        self.assertTrue(any(c["name"] in {"先发制人", "双子精灵", "弦月圣痕"} for c in cards))
        hero_schools = set(hero["schools"])
        for card in cards:
            self.assertTrue(set(card["factions"]) & {self.advisor.school_by_id[s]["name"] for s in hero_schools})

    def test_art_and_skill_icons(self):
        for hero in self.advisor.heroes:
            for key, size in (("art", (300, 300)), ("talent_icon", (128, 128)), ("ultimate_icon", (128, 128))):
                value = hero.get(key)
                self.assertTrue(value, "%s missing %s" % (hero["name"], key))
                path = ROOT / value
                self.assertTrue(path.exists(), "%s missing file %s" % (hero["name"], path))
                with Image.open(path) as image:
                    self.assertEqual(image.size, size)
            with Image.open(ROOT / hero["art"]) as image:
                self.assertEqual(image.mode, "RGB")
            with Image.open(ROOT / hero["talent_icon"]) as image:
                self.assertEqual(image.mode, "RGBA")

    def test_asset_name_aliases(self):
        for name, alias in (("渣客鼠王", "渣克鼠王"), ("炼金术士", "炼金术师"), ("月隐猎手", "月影猎手")):
            hero, _ = self.advisor.resolve_hero(alias)
            self.assertIsNotNone(hero)
            self.assertEqual(hero["name"], name)

    def test_guide_migrated(self):
        guides = load_guides()
        self.assertIn("熊猫武士", guides)
        self.assertNotIn("熊猫", guides)

    def test_json_files_exist(self):
        for name in ("heroes.json", "cards.json", "schools.json", "rules.json"):
            path = ROOT / "data" / name
            self.assertTrue(path.exists(), name)
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
