# -*- coding: utf-8 -*-
"""lab img —— 本地生图统一入口（ComfyUI / FLUX 3 Klein）

一个入口管住原来散在 tools\\ 下的四个脚本 + 服务启停 + 加字：

  lab img status                      服务在不在、显存占多少
  lab img serve [--stop] [--background]  启动 / 关闭 ComfyUI
  lab img gen   "prompt"              文生图（可叠加 Lora、--draft 草稿档）
  lab img i2i   <图> --prompt "..."   图生图 / 整图重绘
  lab img up    <图>                  放大到 2048
  lab img refine <图> --prompt "..."  锁脸精修（脸不参与采样）
  lab img text  <图> "文字"           底部加白色圆角字条
  lab img list                        本地有哪些 Lora

设计原则：这里只做「参数映射 + 转发」，真正的采样逻辑仍在 tools\\comfy_*.py。
所以那些脚本还能单独跑（调试时直连更清楚），lab img 是给日常调用用的稳定入口。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent          # D:\work\tools
PY = sys.executable
HOST = "http://127.0.0.1:8188"
FONT = r"C:\Windows\Fonts\msyhbd.ttc"

# 每个动作 → 底层脚本
SCRIPT = {
    "gen": TOOLS / "comfy_lora.py",
    "i2i": TOOLS / "comfy_img2img.py",
    "up": TOOLS / "comfy_upscale.py",
    "refine": TOOLS / "comfy_refine.py",
}


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _warn(msg: str) -> None:
    print(f"[!] {msg}")


def _forward(script: Path, argv: list[str]) -> int:
    """调用底层脚本，原样转发输出。"""
    if not script.exists():
        print(f"[失败] 找不到脚本 {script}", file=sys.stderr)
        return 2
    cmd = [PY, str(script)] + argv
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run(cmd, cwd=str(TOOLS), env=env)
    return r.returncode


# ---------------------------------------------------------------- status / serve

def _alive(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(HOST + "/system_stats", timeout=timeout):
            return True
    except Exception:
        return False


def _gpu_line() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip().splitlines()
        if out:
            used, total, temp, util = [x.strip() for x in out[0].split(",")]
            return f"显存 {used}/{total} MiB · {temp}°C · 利用率 {util}%"
    except Exception:
        pass
    return "显存信息不可用（nvidia-smi 没响应）"


def cmd_status(_a) -> int:
    up = _alive()
    print(f"ComfyUI: {'在跑' if up else '没在跑'}  ({HOST})")
    print(f"GPU    : {_gpu_line()}")
    if up:
        try:
            with urllib.request.urlopen(HOST + "/system_stats", timeout=5) as r:
                d = json.loads(r.read())
            dev = (d.get("devices") or [{}])[0]
            if dev.get("name"):
                print(f"设备   : {dev['name']}")
        except Exception:
            pass
    else:
        print("提示   : lab img serve 启动（约 18 秒就绪）")
    return 0 if up else 1


def _stop() -> int:
    ps = (
        "$c = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue;"
        "if ($c) { $c.OwningProcess | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force } ;"
        "Start-Sleep -Seconds 2 };"
        "if (Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue) {'still'} else {'gone'}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    tail = (r.stdout or "").strip().splitlines()
    tail = tail[-1] if tail else ""
    if tail == "gone":
        _ok("ComfyUI 已关闭")
        return 0
    _warn("关闭后 8188 仍在监听，检查一下")
    return 1


def cmd_serve(a) -> int:
    if a.stop:
        return _stop()
    if _alive():
        _warn(f"已经在跑（{HOST}），不重复启动")
        return 0
    script = TOOLS / "start-comfy.ps1"
    if not script.exists():
        print(f"[失败] 找不到 {script}", file=sys.stderr)
        return 2
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if a.background:
        cmd.append("-Background")
        # 后台模式：Popen 不等待，且把子进程 stdio 全部丢弃
        # （ComfyUI 会继承句柄，若继承到调用方的管道，调用方会永远等 EOF）
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
    else:
        subprocess.run(cmd)
    # 等就绪
    for _ in range(60):
        time.sleep(1.5)
        if _alive(1.5):
            _ok(f"服务就绪 {HOST}")
            return 0
    _warn("等了 90 秒还没就绪，去看 E:\\DS公作区\\ComfyUI\\logs\\*.err.log")
    return 1


# ---------------------------------------------------------------- 出图四个动作

def cmd_gen(a) -> int:
    argv = [a.prompt]
    for item in a.lora or []:
        argv += ["--lora", item]
    if a.strength is not None and not a.lora:
        argv += ["--strength", str(a.strength)]
    if a.negative:
        argv += ["--negative", a.negative]
    argv += ["--size", str(a.size), "--steps", str(a.steps),
             "--cfg", str(a.cfg), "--seed", str(a.seed), "--prefix", a.prefix]
    if a.draft:
        argv.append("--draft")
    if a.dry:
        argv.append("--dry")
    return _forward(SCRIPT["gen"], argv)


def cmd_i2i(a) -> int:
    argv = [a.source, "--prompt", a.prompt]
    if a.negative:
        argv += ["--negative", a.negative]
    argv += ["--denoise", str(a.denoise), "--steps", str(a.steps),
             "--cfg", str(a.cfg), "--seed", str(a.seed), "--prefix", a.prefix]
    if a.protect_face:
        argv.append("--protect-face")
        if a.feather != 24:
            argv += ["--feather", str(a.feather)]
    if a.draft:
        argv.append("--draft")
    if a.dry:
        argv.append("--dry")
    return _forward(SCRIPT["i2i"], argv)


def cmd_up(a) -> int:
    argv = [a.source, "--size", str(a.size), "--denoise", str(a.denoise),
            "--steps", str(a.steps), "--cfg", str(a.cfg),
            "--seed", str(a.seed), "--prefix", a.prefix]
    if a.dry:
        argv.append("--dry")
    return _forward(SCRIPT["up"], argv)


def cmd_refine(a) -> int:
    argv = [a.source, "--prompt", a.prompt]
    if a.negative:
        argv += ["--negative", a.negative]
    argv += ["--denoise", str(a.denoise), "--steps", str(a.steps),
             "--cfg", str(a.cfg), "--seed", str(a.seed),
             "--prefix", a.prefix, "--expand", str(a.expand)]
    if a.no_fallback:
        argv.append("--no-fallback")
    if a.dry:
        argv.append("--dry")
    return _forward(SCRIPT["refine"], argv)


def cmd_list(_a) -> int:
    return _forward(SCRIPT["gen"], ["--list"])


# ---------------------------------------------------------------- 加字条

def _add_text(img, text: str, size: int | None, pos: str):
    from PIL import ImageDraw, ImageFont

    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    if size is None:
        size = 118 if len(text) <= 3 else 104 if len(text) <= 4 else 92
    font = ImageFont.truetype(FONT, size)
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 42, 22
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    x0 = (W - bw) // 2
    y0 = 44 if pos == "top" else H - bh - 44
    d.rounded_rectangle([x0 + 4, y0 + 6, x0 + bw + 4, y0 + bh + 6],
                        radius=bh // 2, fill=(30, 58, 120, 40))
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh // 2,
                        fill=(255, 255, 255, 240), outline=(40, 90, 170, 255), width=4)
    tx = x0 + pad_x - bbox[0]
    ty = y0 + pad_y - bbox[1]
    for dx in (-3, -2, 0, 2, 3):
        for dy in (-3, -2, 0, 2, 3):
            d.text((tx + dx, ty + dy), text, font=font, fill=(255, 255, 255, 255))
    d.text((tx, ty), text, font=font, fill=(26, 58, 122, 255))
    return img


def cmd_text(a) -> int:
    from PIL import Image

    src = Path(a.image)
    if not src.exists():
        print(f"[失败] 图不存在: {src}", file=sys.stderr)
        return 2
    img = Image.open(src).convert("RGB")
    img = _add_text(img, a.text, a.size, a.pos)
    out = Path(a.out) if a.out else src.with_name(src.stem + "_text.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    _ok(f"{out}  ({img.size[0]}×{img.size[1]}, {out.stat().st_size:,} B)")
    if a.small:
        sm = img.resize((200, 200), Image.LANCZOS)
        smp = out.with_name(out.stem + "_200px.png")
        sm.save(smp, "PNG")
        print(f"     小图 {smp}")
    return 0


# ---------------------------------------------------------------- 注册

def register(sub) -> None:
    p = sub.add_parser(
        "img",
        help="本地生图统一入口：status / serve / gen / i2i / up / refine / text / list",
    )
    s = p.add_subparsers(dest="img_cmd", required=True, metavar="<动作>")

    # status
    st = s.add_parser("status", help="ComfyUI 在不在跑 + 显存占用")
    st.set_defaults(func=cmd_status)

    # serve
    sv = s.add_parser("serve", help="启动 ComfyUI（--stop 关闭）")
    sv.add_argument("--stop", action="store_true", help="关闭而不是启动")
    sv.add_argument("--background", action="store_true", help="后台运行（不占当前窗口）")
    sv.set_defaults(func=cmd_serve)

    # gen
    g = s.add_parser("gen", help="文生图（默认 er_sde + sgm_uniform，20 步 CFG 3.5）")
    g.add_argument("prompt", help="画面描述")
    g.add_argument("--lora", action="append", metavar="名字[:强度]",
                   help="叠加 Lora，可多次（如 --lora tarot:0.85 --lora angles:0.8）")
    g.add_argument("--strength", type=float, default=None,
                   help="只给一个 Lora 时的默认强度（默认 0.85）")
    g.add_argument("--negative", default=None, help="负向词（不给则用脚本默认）")
    g.add_argument("--size", type=int, default=1024)
    g.add_argument("--steps", type=int, default=20)
    g.add_argument("--cfg", type=float, default=3.5)
    g.add_argument("--seed", type=int, default=0, help="0 = 随机")
    g.add_argument("--prefix", default="img")
    g.add_argument("--draft", action="store_true", help="草稿档（CFG 1.0，约 19 秒，负向词失效）")
    g.add_argument("--dry", action="store_true", help="只打印参数，不提交")
    g.set_defaults(func=cmd_gen)

    # i2i
    ii = s.add_parser("i2i", help="图生图 / 整图重绘（denoise 0.40 保脸，0.55 换甲，0.70 换人）")
    ii.add_argument("source", help="源图路径")
    ii.add_argument("--prompt", required=True, help="重画成什么样（不是修改指令）")
    ii.add_argument("--negative", default=None)
    ii.add_argument("--denoise", type=float, default=0.40)
    ii.add_argument("--steps", type=int, default=20)
    ii.add_argument("--cfg", type=float, default=3.5)
    ii.add_argument("--seed", type=int, default=0)
    ii.add_argument("--prefix", default="img2img")
    ii.add_argument("--protect-face", action="store_true",
                    help="事后贴脸兜底（有接缝；正常精修用 refine）")
    ii.add_argument("--feather", type=int, default=24)
    ii.add_argument("--draft", action="store_true")
    ii.add_argument("--dry", action="store_true")
    ii.set_defaults(func=cmd_i2i)

    # up
    u = s.add_parser("up", help="放大到 2048（denoise 0.45 以上会改脸）")
    u.add_argument("source")
    u.add_argument("--size", type=int, default=2048)
    u.add_argument("--denoise", type=float, default=0.40)
    u.add_argument("--steps", type=int, default=8)
    u.add_argument("--cfg", type=float, default=1.0)
    u.add_argument("--seed", type=int, default=0)
    u.add_argument("--prefix", default="upscale")
    u.add_argument("--dry", action="store_true")
    u.set_defaults(func=cmd_up)

    # refine
    r = s.add_parser("refine", help="锁脸精修（MediaPipe 检测脸 → 脸区不参与采样）")
    r.add_argument("source")
    r.add_argument("--prompt", required=True, help="非脸区域重画成什么样")
    r.add_argument("--negative", default=None)
    r.add_argument("--denoise", type=float, default=0.65)
    r.add_argument("--steps", type=int, default=20)
    r.add_argument("--cfg", type=float, default=3.5)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--prefix", default="refine")
    r.add_argument("--expand", type=int, default=24, help="脸部 mask 外扩像素")
    r.add_argument("--no-fallback", action="store_true", help="检测不到脸时不自动退回 img2img")
    r.add_argument("--dry", action="store_true")
    r.set_defaults(func=cmd_refine)

    # text
    t = s.add_parser("text", help="底部加白色圆角字条（表情包那种）")
    t.add_argument("image", help="图片路径")
    t.add_argument("text", help="要加的字")
    t.add_argument("--size", type=int, default=None, help="字号（默认按字数 118/104/92）")
    t.add_argument("--pos", choices=["bottom", "top"], default="bottom")
    t.add_argument("--out", default=None, help="输出路径（默认原图旁 <名>_text.png）")
    t.add_argument("--small", action="store_true", help="同时导一张 200×200 小图")
    t.set_defaults(func=cmd_text)

    # list
    ls = s.add_parser("list", help="本地有哪些 Lora")
    ls.set_defaults(func=cmd_list)

    p.set_defaults(img_parser=p)


def run(a) -> int:
    return a.func(a)
