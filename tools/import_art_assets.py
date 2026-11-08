"""Import the supplied hero art and skill icons.

Source layout (outside the repo, or pass --source):
  选技图片素材/英雄头像/<英雄名>.jpg   300x300
  选技图片素材/天赋图片/<英雄名>.jpg   125x125 圆形图标，浅黄底
  选技图片素材/大招图片/<英雄名>.jpg   114x115 六边形图标，浅黄底

Output:
  data/art/heroes/<hero_id>.png          300x300, RGB
  data/art/skills/<hero_id>_talent.png   128x128, RGBA, transparent corners
  data/art/skills/<hero_id>_ultimate.png 128x128, RGBA, transparent corners

The supplied hero images are display art, NOT in-game nameplate crops, so they
are stored in `art` and never used as recognition templates.  The existing
147x224 `portrait` files remain the recognition templates.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HEROES_PATH = DATA / "heroes.json"
ART_DIR = DATA / "art"
HERO_ART_DIR = ART_DIR / "heroes"
SKILL_ART_DIR = ART_DIR / "skills"
DEFAULT_SOURCE = Path(r"C:\Users\garcey\Desktop\选技图片素材")

# Some source files use a near-miss spelling.  These aliases are also written
# into heroes.json so the web search / manual picker accepts both spellings.
NAME_FIXES = {
    "渣客鼠王": "渣克鼠王",
    "炼金术士": "炼金术师",
    "月隐猎手": "月影猎手",
}


def remove_background(im: Image.Image, tolerance: int = 38) -> Image.Image:
    """Remove the flat pale-yellow sheet behind a circular/hex skill icon.

    Flood-fill from the outer border only, so pale pixels *inside* the icon
    are preserved.  The frame is closed, so the fill stops at the icon edge.
    """
    im = im.convert("RGB")
    width, height = im.size
    pixels = im.load()

    border = (
        [pixels[x, 0] for x in range(width)]
        + [pixels[x, height - 1] for x in range(width)]
        + [pixels[0, y] for y in range(height)]
        + [pixels[width - 1, y] for y in range(height)]
    )
    border.sort(key=lambda c: c[0] + c[1] + c[2])
    bg = border[len(border) // 2]
    tolerance_sq = tolerance * tolerance

    def is_bg(color) -> bool:
        return (
            (color[0] - bg[0]) ** 2
            + (color[1] - bg[1]) ** 2
            + (color[2] - bg[2]) ** 2
        ) <= tolerance_sq

    seen = [[False] * width for _ in range(height)]
    queue: deque[Tuple[int, int]] = deque()

    def push(x: int, y: int) -> None:
        if not seen[y][x] and is_bg(pixels[x, y]):
            seen[y][x] = True
            queue.append((x, y))

    for x in range(width):
        push(x, 0)
        push(x, height - 1)
    for y in range(height):
        push(0, y)
        push(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height:
                push(nx, ny)

    alpha = Image.new("L", (width, height), 255)
    alpha_pixels = alpha.load()
    for y in range(height):
        row = seen[y]
        for x in range(width):
            if row[x]:
                alpha_pixels[x, y] = 0

    out = im.convert("RGBA")
    out.putalpha(alpha)
    return out


def normalize_icon(im: Image.Image, size: int = 128) -> Image.Image:
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    width, height = im.size
    scale = min(size / width, size / height)
    resized = im.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def source_for(hero: Dict, source_stems: Dict[str, Path]) -> str | None:
    names = [hero["name"]] + list(hero.get("aliases") or [])
    for name in names:
        if name in source_stems:
            return name
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_dir():
        print("找不到素材目录：%s" % source)
        return 2

    folders = {
        "hero": source / "英雄头像",
        "talent": source / "天赋图片",
        "ultimate": source / "大招图片",
    }
    for label, folder in folders.items():
        if not folder.is_dir():
            print("缺少子目录：%s" % folder)
            return 2

    hero_stems = {p.stem: p for p in folders["hero"].glob("*.jpg")}
    talent_stems = {p.stem: p for p in folders["talent"].glob("*.jpg")}
    ultimate_stems = {p.stem: p for p in folders["ultimate"].glob("*.jpg")}
    print("source:", {k: len(v) for k, v in (("hero", hero_stems), ("talent", talent_stems), ("ultimate", ultimate_stems))})

    data = json.loads(HEROES_PATH.read_text(encoding="utf-8"))
    heroes: List[Dict] = data["heroes"]

    # Add the near-miss spellings as aliases.
    by_name = {hero["name"]: hero for hero in heroes}
    for target, alias in NAME_FIXES.items():
        hero = by_name[target]
        aliases = list(hero.get("aliases") or [])
        if alias not in aliases:
            aliases.append(alias)
        hero["aliases"] = aliases

    HERO_ART_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_ART_DIR.mkdir(parents=True, exist_ok=True)

    missing = []
    for hero in heroes:
        hero_name = source_for(hero, hero_stems)
        talent_name = source_for(hero, talent_stems)
        ultimate_name = source_for(hero, ultimate_stems)
        if not (hero_name and talent_name and ultimate_name):
            missing.append(
                "%s (hero=%s talent=%s ultimate=%s)"
                % (hero["name"], hero_name, talent_name, ultimate_name)
            )
            continue

        hero_id = hero["id"]
        hero_art_path = HERO_ART_DIR / (hero_id + ".png")
        talent_path = SKILL_ART_DIR / (hero_id + "_talent.png")
        ultimate_path = SKILL_ART_DIR / (hero_id + "_ultimate.png")

        art = Image.open(hero_stems[hero_name]).convert("RGB")
        if art.size != (300, 300):
            art = art.resize((300, 300), Image.LANCZOS)
        art.save(hero_art_path, optimize=True)

        talent = normalize_icon(remove_background(Image.open(talent_stems[talent_name])))
        talent.save(talent_path, optimize=True)

        ultimate = normalize_icon(remove_background(Image.open(ultimate_stems[ultimate_name])))
        ultimate.save(ultimate_path, optimize=True)

        hero["art"] = "data/art/heroes/%s.png" % hero_id
        hero["talent_icon"] = "data/art/skills/%s_talent.png" % hero_id
        hero["ultimate_icon"] = "data/art/skills/%s_ultimate.png" % hero_id

    if missing:
        print("有 %d 个英雄没有配齐素材：" % len(missing))
        for item in missing:
            print("  -", item)
        return 1

    data.setdefault("meta", {})["art_note"] = (
        "art/talent_icon/ultimate_icon 来自选技图片素材；portrait 仍是 147x224 游戏内识别模板。"
    )
    HEROES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    art_count = len(list(HERO_ART_DIR.glob("*.png")))
    skill_count = len(list(SKILL_ART_DIR.glob("*.png")))
    print("hero art:", art_count, "skill icons:", skill_count)
    print("sample:", heroes[0]["name"], heroes[0].get("art"), heroes[0].get("talent_icon"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
