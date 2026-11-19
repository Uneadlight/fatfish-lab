"""lab blender —— 用 Blender 的 Python API 建模、渲染、导出 GLB，全程 headless。

Blender 是便携版（zip 解压即用），装在 E:\\DS公作区\\tools\\blender\\。
它自带 python 3.11 和完整的 bpy 模块，所以脚本能直接 import bpy 建几何体。

子命令：
  lab blender check                     验证安装 + 打印版本/位置
  lab blender run <script.py> [-- 参数] 跑建模脚本（--background --factory-startup）
  lab blender demo                      跑内置最小样例（建倒角立方体 → 导出 GLB）

脚本约定：
  · import bpy 直接用，不需要 sys.path 处理
  · 想把产物路径报给 lab，打印一行  OUTPUT::<绝对路径>
  · 参数用 sys.argv[sys.argv.index('--') + 1:] 取
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\work")
DEFAULT_HOME = ROOT / "tools" / "blender"
OUTPUT_RE = re.compile(r"^OUTPUT::(.+)$", re.M)


def find_blender() -> Path | None:
    """按优先级找 blender.exe：环境变量 → 本机安装目录 → Program Files 扫一遍。"""
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).is_file():
        return Path(env)

    for name in ("blender.exe",):
        p = DEFAULT_HOME / name
        if p.is_file():
            return p

    # 便携版有时多一层同名前缀目录
    for p in DEFAULT_HOME.glob("*/blender.exe"):
        if p.is_file():
            return p

    base = Path(r"C:\Program Files\Blender Foundation")
    if base.is_dir():
        cands = sorted(base.glob("Blender*/blender.exe"), reverse=True)
        if cands:
            return cands[0]
    return None


def run_blender(exe: Path, script: Path, extra: list[str], timeout: float) -> int:
    cmd = [str(exe), "--background", "--factory-startup", "--python", str(script), "--", *extra]
    print(f"[lab blender] {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, cwd=str(script.parent))
    elapsed = time.time() - t0
    out = proc.stdout or ""
    err = proc.stderr or ""

    # Blender 把进度和日志写 stdout，真正有用的错误常在 stderr
    for line in out.splitlines():
        if line.strip():
            print(line)
    if err.strip():
        print("--- stderr ---")
        print(err.strip()[-4000:])

    print(f"[lab blender] rc={proc.returncode}  {elapsed:.1f}s")

    for m in OUTPUT_RE.finditer(out):
        p = Path(m.group(1).strip())
        if p.is_file():
            print(f"[产物] {p}  {p.stat().st_size:,} bytes")
        else:
            print(f"[产物] {p}  ⚠️ 不存在")

    return proc.returncode


DEMO = r'''import bpy, os
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
obj = bpy.context.active_object
mod = obj.modifiers.new(name="Bevel", type='BEVEL')
mod.width, mod.segments = 0.12, 3
bpy.ops.object.modifier_apply(modifier=mod.name)
mat = bpy.data.materials.new(name="DemoMat")
mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.92, 0.42, 0.30, 1)
obj.data.materials.append(mat)
out = r"D:\work\.tmp\blender-demo.glb"
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB')
print("OUTPUT::" + out)
print("BLENDER " + bpy.app.version_string)
'''


def cmd_check(args) -> int:
    exe = find_blender()
    if not exe:
        print("[FAIL] 找不到 blender.exe")
        print("       装法：下载 blender-4.x-windows-x64.zip 解压到 " + str(DEFAULT_HOME))
        print("       或用 BLENDER_EXE 指向已有的 blender.exe")
        return 1
    print(f"[OK] blender.exe: {exe}")
    print(f"     目录: {exe.parent}  ({sum(f.stat().st_size for f in exe.parent.rglob('*') if f.is_file()) / 2**20:,.0f} MB)")
    proc = subprocess.run([str(exe), "--background", "--factory-startup", "--python-expr",
                           "import bpy,sys;print('VER',bpy.app.version_string);print('PY',sys.version.split()[0])"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    for line in (proc.stdout or "").splitlines():
        if line.startswith(("VER ", "PY ", "Blender ")):
            print("     " + line.strip())
    return proc.returncode


def cmd_run(args) -> int:
    exe = find_blender()
    if not exe:
        print("[FAIL] 找不到 blender.exe，先跑 lab blender check")
        return 1
    script = Path(args.script)
    if not script.is_absolute():
        script = (Path.cwd() / script).resolve()
    if not script.is_file():
        print(f"[FAIL] 脚本不存在: {script}")
        return 1
    return run_blender(exe, script, args.extra or [], args.timeout)


def cmd_demo(args) -> int:
    exe = find_blender()
    if not exe:
        print("[FAIL] 找不到 blender.exe，先跑 lab blender check")
        return 1
    tmp = ROOT / ".tmp" / "_blender_demo.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(DEMO, encoding="utf-8", newline="\n")
    return run_blender(exe, tmp, [], args.timeout)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="lab blender", description="Blender headless 建模/导出")
    sub = ap.add_subparsers(dest="action", required=True)

    c = sub.add_parser("check", help="验证安装")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("demo", help="跑内置最小样例")
    d.add_argument("--timeout", type=float, default=300.0)
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("run", help="跑建模脚本")
    r.add_argument("script", help=".py 脚本路径")
    r.add_argument("--timeout", type=float, default=600.0, help="硬超时秒数（默认 600）")
    r.add_argument("extra", nargs="*", help="透传给脚本的参数（写在 -- 之后）")
    r.set_defaults(func=cmd_run)

    ns = ap.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
