#!/usr/bin/env python3
"""
视觉自动化助手 — 用「截图 + 视觉识别」代替固定坐标定位。

设计原则：
  1. 截图统一缩放到逻辑分辨率，图上坐标 == 点击坐标（免换算）
  2. 每个原子动作可独立调用，由视觉判断决定下一步
  3. 点完可再截图验证，形成闭环

用法:
  python3 vision.py shot [名字]          截图到 /tmp/wechat_ops/<名字>.png
  python3 vision.py click X Y            在逻辑坐标 (X,Y) 单击
  python3 vision.py dclick X Y           双击
  python3 vision.py move X Y             移动鼠标
  python3 vision.py activate 微信        激活窗口
  python3 vision.py type "文本"          输入文本（走剪贴板，支持中文）
  python3 vision.py key enter            按键，如 enter / esc / cmd+v
  python3 vision.py scroll N [X Y]       滚动（正数向上），可指定鼠标落点
  python3 vision.py pos                  打印当前鼠标位置与屏幕尺寸
"""

import sys
import os
import time
import shutil
import platform
import subprocess

import pyautogui

pyautogui.FAILSAFE = False

SHOT_DIR = "/tmp/wechat_ops"
IS_MAC = platform.system() == "Darwin"
MOD = "command" if IS_MAC else "ctrl"


def logical_size():
    return pyautogui.size()


def shot(name="cur"):
    """截图并缩放到逻辑分辨率。始终刷新 cur.png（crop/grid 的唯一数据源）。"""
    os.makedirs(SHOT_DIR, exist_ok=True)
    sw, sh = logical_size()
    raw = os.path.join(SHOT_DIR, "_raw.png")
    cur = os.path.join(SHOT_DIR, "cur.png")

    subprocess.run(["screencapture", "-x", raw], check=True)
    # 缩放到逻辑尺寸：之后图上量到的坐标可直接用于点击
    subprocess.run(
        ["sips", "-z", str(sh), str(sw), raw, "--out", cur],
        check=True, capture_output=True,
    )
    os.unlink(raw)
    if name != "cur":
        shutil.copyfile(cur, os.path.join(SHOT_DIR, f"{name}.png"))
    print(f"{cur}  ({sw}x{sh} 逻辑像素)")
    return cur


def fresh_cur():
    """确保 cur.png 是当前屏幕，返回其路径。

    只读图的命令（crop/grid）都先走这里。旧截图是最隐蔽的错误来源：
    图本身没错，错的是它描述的那个瞬间已经过去了。
    """
    return shot("cur")


def crop(x1, y1, x2, y2, name="crop", zoom=3):
    """裁剪截图局部并放大（PIL 精确裁剪）。坐标同逻辑坐标系。

    输出图左上角带该区域的原点标注，便于在放大图内换算绝对坐标。

    默认先重新截图：crop 若读到上一次动作之前的旧图，你会对着一个
    已经不存在的界面做判断（实测踩过两次）。宁可多截一张，也不要看错。
    """
    src = fresh_cur()

    from PIL import Image, ImageDraw, ImageFont

    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    im = Image.open(src).convert("RGB")
    region = im.crop((x1, y1, x2, y2))
    w, h = region.size
    if zoom != 1:
        region = region.resize((int(w * zoom), int(h * zoom)), Image.NEAREST)

    d = ImageDraw.Draw(region)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        font = ImageFont.load_default()
    # 标注原点，避免误读
    d.rectangle([0, 0, 150, 16], fill=(255, 255, 0))
    d.text((2, 2), f"origin=({x1},{y1}) x{zoom}", fill=(0, 0, 0), font=font)

    out = os.path.join(SHOT_DIR, f"{name}.png")
    region.save(out)
    print(f"{out}  裁剪自 ({x1},{y1})-({x2},{y2})  放大 {zoom}x")
    return out


def grid(name="grid", step=50):
    """截当前屏并叠加带刻度的坐标网格，消除读坐标时的估算误差。"""
    src = shot("cur")
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        font = ImageFont.load_default()

    w, h = im.size
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=(255, 60, 60), width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=(60, 140, 255), width=1)
    # 刻度标签（沿上边与左边）
    for x in range(0, w, step):
        d.text((x + 2, 2), str(x), fill=(255, 0, 0), font=font)
    for y in range(0, h, step):
        d.text((2, y + 2), str(y), fill=(0, 90, 255), font=font)

    out = os.path.join(SHOT_DIR, f"{name}.png")
    im.save(out)
    print(f"{out}  网格间隔 {step}px")
    return out


def activate(title):
    """激活标题匹配的窗口（macOS 优先 AppleScript + open -a）。"""
    if not IS_MAC:
        wins = pyautogui.getWindowsWithTitle(title)
        if not wins:
            raise SystemExit(f'窗口 "{title}" 未找到')
        wins[0].activate()
        time.sleep(0.4)
        print(f"已激活: {title}")
        return

    r = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to get name of first application '
         f'process whose (name contains "{title}" or displayed name contains "{title}")'],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        raise SystemExit(f'未找到进程 "{title}"')

    proc = r.stdout.strip()
    subprocess.run(["open", "-a", proc], capture_output=True, timeout=5)
    time.sleep(0.6)
    # 多窗口时聚焦标题匹配的那个
    subprocess.run(
        ["osascript", "-e", f'''
            tell application "System Events"
                tell process "{proc}"
                    try
                        perform action "AXRaise" of (first window whose title contains "{title}")
                    end try
                end tell
            end tell
        '''],
        capture_output=True, text=True, timeout=5,
    )
    time.sleep(0.4)
    print(f"已激活: {proc}")


def click(x, y, double=False):
    x, y = int(x), int(y)
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click(x, y, clicks=2 if double else 1, interval=0.08)
    print(f"已点击 ({x}, {y}){' 双击' if double else ''}")


def longpress(x, y, duration=1.2):
    """在 (x,y) 长按。微信朋友圈的相机图标需长按才出纯文字发布框。"""
    x, y = int(x), int(y)
    pyautogui.moveTo(x, y, duration=0.15)
    time.sleep(0.2)
    pyautogui.mouseDown()
    time.sleep(duration)
    pyautogui.mouseUp()
    time.sleep(0.2)
    print(f"已长按 ({x}, {y}) 持续 {duration}s")


def scroll(amount, x=None, y=None):
    """滚动。正数向上（看更早的内容），负数向下。

    先把鼠标移到目标区域再滚：滚轮事件发给指针所在的视图，
    指针停在别处就会滚错列表（实测：想滚朋友圈流却滚了聊天列表）。
    """
    if x is not None and y is not None:
        pyautogui.moveTo(int(x), int(y), duration=0.15)
        time.sleep(0.15)
    pyautogui.scroll(int(amount))
    time.sleep(0.3)
    print(f"已滚动 {amount}{f' @({x},{y})' if x is not None else ''}")


def type_text(text):
    """走剪贴板输入，支持中文与长文本。"""
    try:
        import pyperclip
    except ImportError:
        pyautogui.write(text, interval=0.03)
        print(f"已输入（逐字）: {text[:40]}")
        return

    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.2)

    # macOS 上用 AppleScript 发 Cmd+V：中文输入法下 pyautogui.hotkey 会把
    # 组合键退化成裸字母（实测会输入一个 "v" 并弹出候选框）
    if IS_MAC:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            pyautogui.hotkey(MOD, "v")
    else:
        pyautogui.hotkey(MOD, "v")
    time.sleep(0.3)
    # 还原剪贴板
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
    print(f"已输入（剪贴板）: {text[:40]}{'...' if len(text) > 40 else ''}")


KEYMAP = {
    "enter": "enter", "return": "enter", "esc": "esc", "escape": "esc",
    "tab": "tab", "space": "space", "delete": "delete", "backspace": "backspace",
}


def press_key(spec):
    """按键。支持 "cmd+v" / "cmd+shift+f" / "enter" 形式。"""
    parts = [p.strip().lower() for p in spec.split("+")]
    key = KEYMAP.get(parts[-1], parts[-1])
    mods = []
    for m in parts[:-1]:
        mods.append({"cmd": "command", "command": "command", "ctrl": "ctrl",
                     "control": "ctrl", "alt": "option", "opt": "option",
                     "shift": "shift"}.get(m, m))
    if mods:
        pyautogui.hotkey(*mods, key)
    else:
        pyautogui.press(key)
    print(f"已按键: {spec}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    a = sys.argv[2:]

    if cmd == "shot":
        shot(a[0] if a else "cur")
    elif cmd == "click":
        click(a[0], a[1])
    elif cmd == "dclick":
        click(a[0], a[1], double=True)
    elif cmd == "longpress":
        longpress(a[0], a[1], float(a[2]) if len(a) > 2 else 1.2)
    elif cmd == "move":
        pyautogui.moveTo(int(a[0]), int(a[1]), duration=0.15)
        print(f"已移动 ({a[0]}, {a[1]})")
    elif cmd == "grid":
        grid(a[0] if a else "grid", int(a[1]) if len(a) > 1 else 50)
    elif cmd == "crop":
        crop(a[0], a[1], a[2], a[3],
             a[4] if len(a) > 4 else "crop",
             float(a[5]) if len(a) > 5 else 3)
    elif cmd == "scroll":
        if not a:
            raise SystemExit("用法: vision.py scroll N [X Y]   N 为正数时内容上移")
        scroll(a[0], a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else None)
    elif cmd == "activate":
        activate(a[0])
    elif cmd == "type":
        type_text(a[0] if a else "")
    elif cmd == "key":
        press_key(a[0])
    elif cmd == "pos":
        sw, sh = logical_size()
        print(f"屏幕: {sw}x{sh}   鼠标: {pyautogui.position()}")
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except IndexError:
        # 参数少写一个就抛裸 IndexError，看不出是哪条命令缺什么。给出用法更省事。
        print(f"命令 {sys.argv[1] if len(sys.argv) > 1 else ''} 参数不足\n")
        print(__doc__)
        sys.exit(1)
