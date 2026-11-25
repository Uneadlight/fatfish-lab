#!/usr/bin/env python3
r"""把 dsh-* 插件发布到 npm 官方源。

用法：
    python tools/publish-npm.py                    # 发默认三个包
    python tools/publish-npm.py dsh-env-doctor     # 只发一个
    python tools/publish-npm.py --dry-run          # 干跑看打包内容
    python tools/publish-npm.py --check            # 只查线上版本对不对

为什么要有这个脚本（2026-11-25 踩坑记录）：
  1. 本机 npm registry 指向淘宝镜像 `registry.npmmirror.com`，发布必须显式
     `--registry https://registry.npmjs.org`，否则推不上去。
  2. 账号 2FA 是 `auth-and-writes`（安全密钥，不是 TOTP），`--otp` 拿不到码；
     网页登录又要求「用另一台有 passkey 的设备扫码」，单机场景走不通。
     唯一可靠的路 = Granular Access Token（网页创建时勾「绕过 2FA」），存
     `C:\Users\Administrator\.dsh\secrets\npm-token.txt`。
  3. 恢复码不能用于发布（npm 政策：用一个会冻结发布 72 小时）。
  4. token 末尾常被聊天里的标点污染（比如句号），用前必须核对长度 40
     （`npm_` + 36 字符）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET = Path(r"C:\Users\Administrator\.dsh\secrets\npm-token.txt")
REGISTRY = "https://registry.npmjs.org"

DEFAULT_PKGS = ["dsh-env-doctor", "dsh-vision", "dsh-chat-background"]


def read_token() -> str:
    if not SECRET.exists():
        raise SystemExit(f"[FAIL] 找不到 token 文件：{SECRET}")
    token = SECRET.read_text(encoding="utf-8").strip()
    if token.startswith("npm_") is False or len(token) != 40:
        raise SystemExit(
            f"[FAIL] token 格式不对（长度 {len(token)}，应为 40 且以 npm_ 开头）。"
            "常见原因：复制时把末尾标点也带进来了。"
        )
    return token


def read_pkg_version(pkg_dir: Path) -> str:
    import json

    data = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
    return f"{data['name']}@{data['version']}"


def run(cmd: list[str], cwd: Path, timeout: int = 180) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode, out


def publish(pkg: str, token: str, dry: bool) -> bool:
    pkg_dir = ROOT / pkg
    if not (pkg_dir / "package.json").exists():
        print(f"[SKIP] {pkg}：目录或 package.json 不存在")
        return False
    ver = read_pkg_version(pkg_dir)
    cmd = [
        "npm.cmd", "publish",
        "--registry", REGISTRY,
        f"--//{REGISTRY.replace('https:', '')}/:_authToken={token}",
    ]
    if dry:
        cmd.append("--dry-run")
    code, out = run(cmd, pkg_dir)
    ok = code == 0
    tail = "\n".join(out.splitlines()[-3:])
    print(f"[{'OK' if ok else 'FAIL'}] {ver}{'（dry-run）' if dry else ''}")
    if not ok:
        print("    " + tail.replace("\n", "\n    "))
    return ok


def check(pkgs: list[str]) -> bool:
    all_ok = True
    for pkg in pkgs:
        pkg_dir = ROOT / pkg
        if not (pkg_dir / "package.json").exists():
            continue
        local = read_pkg_version(pkg_dir)
        name, version = local.rsplit("@", 1)
        code, out = run(
            ["npm.cmd", "view", name, "version", "--registry", REGISTRY], ROOT, timeout=60
        )
        remote = out.splitlines()[-1].strip() if out else "?"
        ok = code == 0 and remote == version
        all_ok = all_ok and ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}  本地 {version} / 线上 {remote}")
    return all_ok


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    check_mode = "--check" in argv
    pkgs = [a for a in argv if not a.startswith("--")] or DEFAULT_PKGS

    if check_mode:
        return 0 if check(pkgs) else 1

    token = read_token()
    results = [publish(p, token, dry) for p in pkgs]
    if dry:
        return 0 if all(results) else 1

    print("\n=== 复核线上 ===")
    return 0 if check(pkgs) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
