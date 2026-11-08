"""Fullscreen sample viewer for testing the floating HUD without the game.

    python tools/preview_draft.py [seconds]

It shows samples/draft_001.png fullscreen with a game-like window title, so
F8 should capture it, recognize the draft and show the HUD.  Press Esc to close.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk

from PIL import Image, ImageTk

from app.overlay import capture

capture.enable_dpi_awareness()

SAMPLE = ROOT / "samples" / "draft_001.png"


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    root = tk.Tk()
    root.title("选技大乱斗 测试画面")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    width = root.winfo_screenwidth()
    height = root.winfo_screenheight()
    root.geometry("%dx%d+0+0" % (width, height))

    image = Image.open(SAMPLE).convert("RGB")
    scale = min(width / image.width, height / image.height)
    image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    canvas_image = Image.new("RGB", (width, height), (0, 0, 0))
    canvas_image.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    photo = ImageTk.PhotoImage(canvas_image)
    label = tk.Label(root, image=photo, bd=0, bg="black")
    label.pack(fill="both", expand=True)
    root.bind("<Escape>", lambda _event: root.destroy())
    root.after(int(seconds * 1000), root.destroy)
    print("viewer ready %dx%d" % (width, height), flush=True)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
