"""Windows screen capture and window helpers used by the floating HUD.

No third-party capture library is required: window capture uses GDI BitBlt and
falls back to PrintWindow for windows that BitBlt cannot see.  This works for
windowed and borderless-fullscreen games.  Exclusive fullscreen bypasses the
desktop compositor, so no ordinary overlay can cover it; the HUD tells the user
to switch the game to borderless mode.
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
PW_RENDERFULLCONTENT = 0x00000002
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
MONITOR_DEFAULTTONEAREST = 2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = wintypes.HWND(-1)

GAME_TITLE_HINTS = ("选技大乱斗", "skill legends", "xuanji", "选技")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


@dataclass
class CaptureResult:
    image: Image.Image
    method: str
    window_title: str
    box: Tuple[int, int, int, int]
    elapsed: float


class CaptureError(RuntimeError):
    pass


def enable_dpi_awareness() -> None:
    """Must run before Tk is created so GDI and Tk agree on pixels."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def client_box(hwnd: int) -> Tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise CaptureError("无法读取窗口客户区")
    width = int(rect.right)
    height = int(rect.bottom)
    if width <= 0 or height <= 0:
        raise CaptureError("窗口客户区为空（可能已最小化）")
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return int(point.x), int(point.y), int(point.x + width), int(point.y + height)


def window_box(hwnd: int) -> Tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise CaptureError("无法读取窗口位置")
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _dib(width: int, height: int):
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not hbmp:
        raise CaptureError("无法创建 DIB 位图")
    return hbmp, bits


def _is_black(image: Image.Image) -> bool:
    small = np.asarray(image.resize((48, 48), Image.BILINEAR), dtype=np.float32)
    return float(small.mean()) < 4.0 and float(small.max()) < 24.0


def capture_screen(box: Tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        raise CaptureError("截图区域为空")
    screen = user32.GetDC(None)
    if not screen:
        raise CaptureError("无法获取屏幕 DC")
    memdc = gdi32.CreateCompatibleDC(screen)
    if not memdc:
        user32.ReleaseDC(None, screen)
        raise CaptureError("无法创建内存 DC")
    try:
        hbmp, bits = _dib(width, height)
        old = gdi32.SelectObject(memdc, hbmp)
        ok = gdi32.BitBlt(memdc, 0, 0, width, height, screen, x0, y0, SRCCOPY | CAPTUREBLT)
        if not ok:
            gdi32.SelectObject(memdc, old)
            gdi32.DeleteObject(hbmp)
            raise CaptureError("BitBlt 截图失败")
        data = ctypes.string_at(bits, width * height * 4)
        image = Image.frombuffer("RGB", (width, height), data, "raw", "BGRX", 0, 1).copy()
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(hbmp)
        return image
    finally:
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, screen)


def capture_printwindow(hwnd: int, box: Tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    screen = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(screen)
    try:
        hbmp, bits = _dib(width, height)
        old = gdi32.SelectObject(memdc, hbmp)
        ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)
        if not ok:
            gdi32.SelectObject(memdc, old)
            gdi32.DeleteObject(hbmp)
            raise CaptureError("PrintWindow 截图失败")
        data = ctypes.string_at(bits, width * height * 4)
        image = Image.frombuffer("RGB", (width, height), data, "raw", "BGRX", 0, 1).copy()
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(hbmp)
        return image
    finally:
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, screen)


def monitor_work_area(hwnd: Optional[int] = None) -> Tuple[int, int, int, int]:
    monitor = user32.MonitorFromWindow(hwnd or 0, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        r = info.rcWork
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return 0, 0, int(width), int(height)


def find_game_window() -> Optional[int]:
    """Find a visible window whose title looks like the game.

    A matching title is not enough: minimized/child/ghost windows can report a
    zero-sized client area.  Rank candidates by their *client* area and ignore
    invalid ones.
    """
    candidates: List[Tuple[int, int, str, Tuple[int, int, int, int]]] = []
    own_pid = os.getpid()

    # The user presses F8 while looking at the game, so the foreground window is
    # normally the correct target even if its title differs from the expected
    # names.  This also prevents a background browser tab containing "选技大乱斗"
    # from winning over a windowed game.
    foreground = foreground_window()
    if foreground and window_pid(foreground) != own_pid:
        try:
            fg_box = client_box(foreground)
            if fg_box[2] - fg_box[0] >= 640 and fg_box[3] - fg_box[1] >= 360:
                return foreground
        except Exception:
            pass

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True
            # Do not skip WS_EX_TOOLWINDOW: borderless/fullscreen game windows
            # and Tk preview windows often set it.  Size/title checks below are
            # enough to reject tray/helper windows.
            title = window_title(hwnd)
            if not title:
                return True
            lower = title.lower()
            if not any(hint.lower() in lower for hint in GAME_TITLE_HINTS):
                return True
            try:
                box = client_box(hwnd)
            except Exception:
                return True
            width = box[2] - box[0]
            height = box[3] - box[1]
            if width >= 640 and height >= 360:
                candidates.append((width * height, int(hwnd), title, box))
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, 0)
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    fg = foreground_window()
    if fg and window_pid(fg) != own_pid:
        try:
            box = client_box(fg)
            if box[2] - box[0] >= 640 and box[3] - box[1] >= 360:
                return fg
        except Exception:
            pass
    return None


def foreground_window() -> int:
    return int(user32.GetForegroundWindow())


def capture(hwnd: Optional[int] = None, prefer: str = "auto") -> CaptureResult:
    """Capture the game window (client area) and return the image + metadata."""
    started = time.perf_counter()
    target = hwnd or find_game_window() or foreground_window()
    if not target:
        raise CaptureError("没有找到可捕获的窗口")
    if window_pid(target) == os.getpid():
        target = find_game_window()
        if not target:
            raise CaptureError("当前焦点在浮窗/控制台上，请先切回游戏画面再按 F8")
    title = window_title(target)
    if not title:
        title = "未命名窗口"
    try:
        box = client_box(target)
    except Exception as exc:
        raise CaptureError("窗口 %r：%s" % (title, exc))
    # Clamp to the virtual desktop.  Metric indices matter:
    # 76/77 = origin, 78/79 = width/height.
    screen_x = user32.GetSystemMetrics(76)
    screen_y = user32.GetSystemMetrics(77)
    screen_w = user32.GetSystemMetrics(78)
    screen_h = user32.GetSystemMetrics(79)
    x0, y0, x1, y1 = box
    clipped = (
        max(x0, screen_x),
        max(y0, screen_y),
        min(x1, screen_x + screen_w),
        min(y1, screen_y + screen_h),
    )
    if clipped[2] - clipped[0] < 320 or clipped[3] - clipped[1] < 240:
        raise CaptureError(
            "窗口不在可见桌面内（窗口 %r，区域 %s，桌面 %s）"
            % (title, box, (screen_x, screen_y, screen_w, screen_h))
        )
    box = clipped

    method = "screen"
    image = capture_screen(box)
    if _is_black(image) and prefer != "screen":
        try:
            alt = capture_printwindow(target, box)
            if not _is_black(alt):
                image, method = alt, "printwindow"
        except Exception:
            pass
    if _is_black(image):
        raise CaptureError(
            "捕获到黑屏。游戏可能使用了「独占全屏」；请把游戏切换为「无边框窗口」模式后重试。"
        )
    elapsed = time.perf_counter() - started
    return CaptureResult(image=image, method=method, window_title=title, box=box, elapsed=elapsed)


def apply_overlay_styles(hwnd: int, click_through: bool = False) -> None:
    """Make a Tk window topmost, no taskbar, no activation.

    click_through is off by default so the card can receive mouse drags.  It is
    kept as an option for a future "locked" mode.
    """
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if click_through:
        ex |= WS_EX_TRANSPARENT
    else:
        ex &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)


def position_topmost(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW)


def top_level_hwnd(child_hwnd: int) -> int:
    parent = user32.GetParent(child_hwnd)
    return int(parent or child_hwnd)
