import unittest

from app.kb.guides import load_guides, parse_frontmatter, split_sections
from app.kb.recommend import Advisor

ENABLED = ["basic", "ultimate", "shield", "rage", "heal", "poison", "spirit", "haste"]
BANNED = ["dodge", "crit", "life", "freeze", "vulnerable"]


class GuideParsingTest(unittest.TestCase):
    def test_frontmatter(self):
        meta, body = parse_frontmatter("---\nhero: 测试\nschools: 普攻流, 急速流\n---\n\n## 结论\n你好")
        self.assertEqual(meta["hero"], "测试")
        self.assertEqual(meta["schools"], ["普攻流", "急速流"])
        self.assertIn("## 结论", body)

    def test_sections(self):
        sections = split_sections("# 标题\n\n## 一句话结论\n很强\n\n## 开局抓牌顺序\n- 拿攻击")
        self.assertEqual([s[0] for s in sections], ["一句话结论", "开局抓牌顺序"])
        self.assertIn("拿攻击", sections[1][1])

    def test_guides_loaded(self):
        guides = load_guides()
        self.assertIn("神秘法师", guides)
        self.assertGreaterEqual(len(guides), 8)


class AdvisorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = Advisor()

    def test_recommendation_order(self):
        result = self.advisor.recommend(["森林游侠", "神秘法师", "魔镜"], ENABLED, BANNED)
        self.assertEqual(result["recommendations"][0]["name"], "神秘法师")
        self.assertGreater(result["recommendations"][0]["score"], result["recommendations"][1]["score"])
        self.assertEqual(len(result["draft"]["enabled"]), 8)
        self.assertEqual(len(result["draft"]["banned"]), 5)
        self.assertEqual(result["recommendations"][0]["confidence"], "high")

    def test_evidence_is_hero_specific(self):
        result = self.advisor.recommend(["神秘法师"], ENABLED, BANNED)
        evidence = result["recommendations"][0]["evidence"]
        self.assertTrue(evidence)
        self.assertTrue(all(item["same_hero"] for item in evidence))

    def test_banned_core_school_lowers_score(self):
        normal = self.advisor.recommend(["神秘法师"], ENABLED, BANNED)["recommendations"][0]
        banned = self.advisor.recommend(
            ["神秘法师"],
            ["basic", "shield", "rage", "heal", "poison", "spirit", "haste", "crit"],
            ["ultimate", "dodge", "life", "freeze", "vulnerable"],
        )["recommendations"][0]
        self.assertLess(banned["score"], normal["score"])
        self.assertTrue(any("大招流" in r for r in banned["reasons"]) or any("大招流" in r for r in banned["risks"]))

    def test_unknown_hero_is_safe(self):
        result = self.advisor.recommend(["不存在的英雄", "神秘法师", "魔镜"], ENABLED, BANNED)
        unknown = [c for c in result["recommendations"] if c["name"] == "不存在的英雄"][0]
        self.assertIn(unknown["confidence"], ("low", "backup"))
        self.assertIn("攻略库暂无", " ".join(unknown["reasons"]))

    def test_environment_notes(self):
        result = self.advisor.recommend(["神秘法师"], ENABLED, BANNED)
        notes = result["environment"]["notes"]
        self.assertTrue(any("冰冻流" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
