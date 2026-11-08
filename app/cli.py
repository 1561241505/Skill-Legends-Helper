"""Command line interface: analyze one screenshot without the web UI.

    python -m app.cli samples/draft_001.png
    python -m app.cli samples/draft_001.png --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .kb.recommend import Advisor
from .vision import imageops
from .vision.recognizer import Recognizer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="选技大乱斗开局截图分析")
    parser.add_argument("image", help="截图路径")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--debug", action="store_true", help="附加识别调试信息")
    args = parser.parse_args(argv)

    path = Path(args.image)
    if not path.exists():
        print("找不到文件：%s" % path)
        return 2
    recognizer = Recognizer()
    result = recognizer.analyze(imageops.open_image(path.read_bytes()), debug=args.debug)
    heroes = [h["name"] or "未知英雄" for h in result["heroes"]]
    enabled = [s["id"] for s in result["schools"]["enabled"]]
    banned = [s["id"] for s in result["schools"]["banned"]]

    advisor = Advisor()
    rec = advisor.recommend(heroes, enabled, banned)
    if args.json:
        result.pop("image", None)
        for hero in result["heroes"]:
            hero.pop("portrait", None)
        result["recommendation"] = rec
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("英雄：" + " / ".join(heroes))
    print("启用：" + "、".join(s["name"] for s in rec["draft"]["enabled"]))
    print("禁用：" + "、".join(s["name"] for s in rec["draft"]["banned"]))
    print()
    print("结论：" + rec["verdict"])
    print()
    confidence_text = {"high": "高置信", "medium": "中等", "low": "低置信", "backup": "备选"}
    for card in rec["recommendations"]:
        print("[%d] %s  %.1f 分（%s）" % (card["rank"], card["name"], card["score"], confidence_text.get(card["confidence"], card["confidence"])))
        for reason in card["reasons"][:3]:
            print("    - " + reason)
        steps = [s.replace("主路线：", "").replace("副路线：", "") for s in card["build"]["steps"][:3]]
        print("    路线：" + " → ".join(steps))
    if result["warnings"]:
        print()
        print("提示：" + "；".join(result["warnings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
