"""Rebuild the seed templates from the bundled sample screenshot.

The bundled sample contains 森林游侠 / 神秘法师 / 魔镜 and all 13 schools.
This is only used to regenerate the shipped templates; day-to-day learning
happens automatically through the web UI.

    python tools/build_templates.py
    python tools/build_templates.py --out temp_templates --debug
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from app.config import SAMPLES_DIR, TEMPLATE_DIR  # noqa: E402
from app.vision import imageops  # noqa: E402
from app.vision.recognizer import Recognizer  # noqa: E402

SEED_HEROES = [
    ("forest_ranger", "森林游侠"),
    ("mystic_mage", "神秘法师"),
    ("magic_mirror", "魔镜"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=str(SAMPLES_DIR / "draft_001.png"))
    parser.add_argument("--out", default=str(TEMPLATE_DIR))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print("找不到截图：%s" % image_path)
        return 2
    out = Path(args.out)
    schools_dir = out / "schools"
    heroes_dir = out / "heroes"
    schools_dir.mkdir(parents=True, exist_ok=True)
    heroes_dir.mkdir(parents=True, exist_ok=True)

    recognizer = Recognizer()
    image = imageops.open_image(image_path.read_bytes())
    image, scale = imageops.fit_width(image, 1800)

    rings = recognizer._detect_ban_rings(image)
    centers = recognizer._grid_from_rings(rings)
    if not centers:
        print("未检测到 5 个禁用环，无法定位 13 宫格。请确认截图是否完整。")
        return 1
    school_ids = [s["id"] for s in recognizer.schools]
    if len(school_ids) != 13:
        print("schools.json 中的流派数量不是 13，无法生成。")
        return 1

    for sid, (cx, cy) in zip(school_ids, centers):
        icon_box = (int(cx - 42), int(cy - 42), int(cx + 42), int(cy + 42))
        label_box = (int(cx + 34), int(cy - 28), int(min(image.width, cx + 212)), int(cy + 28))
        image.crop(icon_box).save(schools_dir / (sid + ".png"))
        image.crop(label_box).save(schools_dir / (sid + "_label.png"))
        if args.debug:
            print("school %-11s icon=%s label=%s" % (sid, icon_box, label_box))

    plates = recognizer._detect_nameplates(image)
    if len(plates) < 3:
        print("只检测到 %d 个名牌，无法生成 3 个英雄头像。" % len(plates))
        return 1
    for (hid, name), plate in zip(SEED_HEROES, plates[:3]):
        box = recognizer._hero_portrait_box(plate)
        image.crop(box).save(heroes_dir / (hid + ".png"))
        if args.debug:
            print("hero %-12s plate=%s crop=%s" % (name, plate, box))

    print("模板已生成：%s（缩放 %.3f）" % (out, scale))
    print("共 %d 个流派、%d 个英雄。" % (len(school_ids), len(SEED_HEROES)))
    print("重启服务或刷新页面即可生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
