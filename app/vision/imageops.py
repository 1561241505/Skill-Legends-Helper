"""Lightweight image helpers built on Pillow + NumPy (no OpenCV needed)."""
from __future__ import annotations

import base64
import io
from typing import Iterable, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Box = Tuple[int, int, int, int]


def open_image(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    return im


def fit_width(im: Image.Image, width: int) -> Tuple[Image.Image, float]:
    """Scale so that the image width equals *width*; returns (image, scale)."""
    if im.width == width:
        return im, 1.0
    scale = width / float(im.width)
    height = max(1, int(round(im.height * scale)))
    return im.resize((width, height), Image.LANCZOS), scale


def gray_mask(arr: np.ndarray, lo: int = 80, hi: int = 208, spread: int = 30) -> np.ndarray:
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    return (mx - mn < spread) & (mx > lo) & (mx < hi)


def white_mask(arr: np.ndarray, lo: int = 190, spread: int = 45) -> np.ndarray:
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    return (mn > lo) & (mx - mn < spread)


def red_mask(arr: np.ndarray) -> np.ndarray:
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    return (r > 135) & (r - g > 45) & (r - b > 45)


def components(mask: np.ndarray, min_area: int = 30, eight: bool = True) -> List[Tuple[int, int, int, int, int]]:
    """4/8-connected components. Returns (x0, y0, x1, y1, area)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out: List[Tuple[int, int, int, int, int]] = []
    ys, xs = np.nonzero(mask)
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if eight:
        offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        minx = maxx = x0
        miny = maxy = y0
        area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            if x < minx:
                minx = x
            elif x > maxx:
                maxx = x
            if y < miny:
                miny = y
            elif y > maxy:
                maxy = y
            for dy, dx in offsets:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if area >= min_area:
            out.append((minx, miny, maxx + 1, maxy + 1, area))
    return out


def block_any(mask: np.ndarray, factor: int) -> np.ndarray:
    """Downscale a boolean mask by `factor`, keeping any foreground pixel."""
    h = (mask.shape[0] // factor) * factor
    w = (mask.shape[1] // factor) * factor
    if h == 0 or w == 0:
        return mask.copy()
    m = mask[:h, :w]
    return m.reshape(h // factor, factor, w // factor, factor).any(axis=(1, 3))


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(a, b) / denom)


def image_to_data_url(im: Image.Image, fmt: str = "PNG", max_width: int = None, quality: int = 88) -> str:
    out = im
    if max_width and out.width > max_width:
        h = max(1, int(round(out.height * max_width / out.width)))
        out = out.resize((max_width, h), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        out.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        out.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(buf.getvalue()).decode("ascii"))


def decode_data_url(data_url: str) -> bytes:
    if not data_url:
        raise ValueError("empty image")
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


def crop(im: Image.Image, box: Sequence[int]) -> Image.Image:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0 = max(0, min(im.width, x0))
    x1 = max(0, min(im.width, x1))
    y0 = max(0, min(im.height, y0))
    y1 = max(0, min(im.height, y1))
    if x1 <= x0 or y1 <= y0:
        return Image.new("RGB", (1, 1), (0, 0, 0))
    return im.crop((x0, y0, x1, y1))


def draw_boxes(im: Image.Image, boxes: Iterable[Tuple[Box, Tuple[int, int, int], str]], width: int = 3) -> Image.Image:
    out = im.copy()
    draw = ImageDraw.Draw(out)
    for box, color, label in boxes:
        x0, y0, x1, y1 = box
        draw.rectangle([x0, y0, x1, y1], outline=color, width=width)
        if label:
            tw = max(60, len(label) * 10)
            draw.rectangle([x0, max(0, y0 - 22), x0 + tw, y0], fill=color)
            draw.text((x0 + 6, max(0, y0 - 20)), label, fill=(15, 17, 21))
    return out


def sharpen_for_match(im: Image.Image, size: Tuple[int, int]) -> np.ndarray:
    gray = im.convert("L").resize(size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.1))
    return np.asarray(gray, dtype=np.float32)
