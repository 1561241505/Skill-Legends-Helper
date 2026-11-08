"""Entry point: python run.py

Starts the local web UI on 127.0.0.1 and opens the browser.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_dependencies() -> bool:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception as exc:
        print("缺少运行依赖：%s" % exc)
        print("请用带 numpy / Pillow 的 Python 运行，或执行：")
        print("  python -m pip install numpy pillow")
        print("Windows 上也可以直接双击「启动助手.bat」。")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="选技大乱斗 · 开局助手")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8777, help="端口，默认 8777")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    if not check_dependencies():
        raise SystemExit(1)
    from app.server import main as server_main

    server_main(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
