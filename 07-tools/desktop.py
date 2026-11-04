#!/usr/bin/env python
"""桌面输入：鼠标移动/点击、键盘按键（Win32 API，纯标准库 ctypes）。

为什么需要它（P3 的「另一半」）：`lab cdp` 只能操作浏览器里的 DOM；
要动真正的桌面窗口（资源管理器、IDE、桌面图标、非 Chromium 的应用），
只有 Win32 的 SetCursorPos + mouse_event / keybd_event 这条路。

安全边界（默认不干）：
  - 所有会改变系统状态的动作默认 dry-run，只打印「要做什么、当前在哪」，
    加 `--yes` 才真执行。理由：桌面坐标会漂、窗口会动，点错是有破坏性后果的。
  - 不做拖拽（需要 按下-移动-抬起 三段，先不引入）、不隐藏窗口、不碰开始菜单。
  - 不 sleep：调用方自己控制节奏（连续动作是独立命令，不在一次调用里串）。

退出码：0 成功 / 2 参数错 / 4 系统调用失败。
"""
import argparse
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
KEYEVENTF_KEYUP = 0x0002

BUTTONS = {
    'left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    'right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    'middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

VK = {
    'enter': 0x0D, 'tab': 0x09, 'esc': 0x1B, 'space': 0x20,
    'backspace': 0x08, 'delete': 0x2E,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'win': 0x5B, 'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10,
}
VK.update({f'f{i}': 0x6F + i for i in range(1, 13)})


class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


def cursor_pos() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move(x: int, y: int) -> bool:
    return bool(user32.SetCursorPos(int(x), int(y)))


def click(button: str = 'left', double: bool = False) -> None:
    down, up = BUTTONS[button]
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)
    if double:
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)


def resolve(combo: str) -> list[int]:
    """把 'ctrl+s' 解析成 VK 码列表（不发送）。"""
    parts = [p.strip().lower() for p in combo.split('+') if p.strip()]
    if not parts:
        raise ValueError('空组合键')
    codes: list[int] = []
    for p in parts:
        if len(p) == 1:
            codes.append(ord(p.upper()))
        elif p in VK:
            codes.append(VK[p])
        else:
            raise ValueError(f'不认识的键: {p}（单字符或 {"/".join(sorted(VK))} 之一）')
    return codes


def send(codes: list[int]) -> None:
    """先按下再逆序抬起——顺序反了组合键就不成立。"""
    for c in codes:
        user32.keybd_event(c, 0, 0, 0)
    for c in reversed(codes):
        user32.keybd_event(c, 0, KEYEVENTF_KEYUP, 0)


def do_pos(a) -> int:
    x, y = cursor_pos()
    w, h = screen_size()
    print(f'[MOUSE] 当前 ({x}, {y}) · 屏幕 {w}×{h}')
    return 0


def do_move(a) -> int:
    cx, cy = cursor_pos()
    w, h = screen_size()
    if not (0 <= a.x < w and 0 <= a.y < h):
        print(f'[FAIL] ({a.x}, {a.y}) 不在屏幕范围内（0–{w - 1}, 0–{h - 1}）')
        return 2
    if not a.yes:
        print(f'[DRY] 会把鼠标从 ({cx}, {cy}) 移到 ({a.x}, {a.y})；加 --yes 才真动')
        return 0
    ok = move(a.x, a.y)
    nx, ny = cursor_pos()
    print(f'[MOUSE] ({cx}, {cy}) -> ({nx}, {ny})' + ('' if ok else '  [FAIL] SetCursorPos 返回 False'))
    return 0 if ok else 4


def do_click(a) -> int:
    cx, cy = cursor_pos()
    x = a.x if a.x is not None else cx
    y = a.y if a.y is not None else cy
    w, h = screen_size()
    if not (0 <= x < w and 0 <= y < h):
        print(f'[FAIL] ({x}, {y}) 不在屏幕范围内（0–{w - 1}, 0–{h - 1}）')
        return 2
    what = f'{a.button} 键双击' if a.double else f'{a.button} 键单击'
    if not a.yes:
        print(f'[DRY] 会先把鼠标移到 ({x}, {y})（当前 ({cx}, {cy})），再 {what}；加 --yes 才真点')
        return 0
    move(x, y)
    click(a.button, a.double)
    print(f'[MOUSE] 在 ({x}, {y}) {what}')
    return 0


def do_key(a) -> int:
    try:
        codes = resolve(a.combo)
    except ValueError as exc:
        print(f'[FAIL] {exc}')
        return 2
    vk = ', '.join(str(c) for c in codes)
    if not a.yes:
        print(f'[DRY] 会发出 {a.combo}（VK: {vk}）；加 --yes 才真按')
        return 0
    send(codes)
    print(f'[KEY] 发出 {a.combo}（VK: {vk}）')
    return 0


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--yes', action='store_true', help='真执行（默认只预览）')

    ap = argparse.ArgumentParser(description='桌面输入：鼠标移动/点击、键盘按键（默认 dry-run）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('pos', help='打印当前鼠标坐标和屏幕尺寸').set_defaults(func=do_pos)

    m = sub.add_parser('move', parents=[common], help='把鼠标移到 (x, y)')
    m.add_argument('x', type=int)
    m.add_argument('y', type=int)
    m.set_defaults(func=do_move)

    c = sub.add_parser('click', parents=[common], help='在 (x, y) 点一下；不给坐标 = 当前位置')
    c.add_argument('x', type=int, nargs='?')
    c.add_argument('y', type=int, nargs='?')
    c.add_argument('--button', default='left', choices=sorted(BUTTONS))
    c.add_argument('--double', action='store_true')
    c.set_defaults(func=do_click)

    k = sub.add_parser('key', parents=[common], help='发按键，如 ctrl+s / enter / alt+tab')
    k.add_argument('combo')
    k.set_defaults(func=do_key)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == '__main__':
    sys.exit(main())
