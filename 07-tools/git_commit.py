"""通用 git 提交：中文 message 走 UTF-8 文件 + commit -F，避免 GBK 转码。

为什么需要它：`git commit -m "中文"` 在 Windows 上会被按 GBK 转码，
终端看着正常，`git cat-file commit HEAD` 出来的是乱码——判据永远是原始字节。

推送默认带 GitHub token（从 `~/.dsh/github-token.txt` 读），走
`http.extraheader` 注入，token 不会落进 `.git/config`；同时清空 credential
helper，避免 git 在无凭据时去弹框（那会报
`could not read Username for 'https://github.com'`）。

用法：
  py tools/lab/git_commit.py --repo "E:\\DS公作区\\架构文档" \\
     --files a.md b.md --msg-file tools/lab/_msg_docs.txt
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import time
from pathlib import Path

GIT = r"D:\work\tools\git\cmd\git.exe"
TOKEN_FILE = Path.home() / ".dsh" / "github-token.txt"

PUSH_TRIES = 3
PUSH_BACKOFF_SECONDS = 5


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(
        [GIT, "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and p.returncode != 0:
        print("[FAIL] git " + " ".join(args))
        print(p.stdout.strip())
        print(p.stderr.strip())
        sys.exit(1)
    return p


def auth_args() -> list[str]:
    """token 注入参数；没有 token 就返回空（公开仓库只读推送会失败，由调用方兜底）。"""
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not token:
        return []
    b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return [
        "-c",
        f"http.extraheader=AUTHORIZATION: basic {b64}",
        # 清空 credential helper：带 extraheader 就不需要它，留着反而会弹框
        "-c",
        "credential.helper=",
        # GitHub 上 HTTP/2 偶发 "Connection was reset"，固定 1.1 更稳
        "-c",
        "http.version=HTTP/1.1",
        "-c",
        "http.postBuffer=524288000",
    ]


def push_branch(repo: Path, branch: str, tries: int = PUSH_TRIES) -> bool:
    extra = auth_args()
    for attempt in range(1, tries + 1):
        p = run(repo, *extra, "push", "origin", branch, check=False)
        if p.returncode == 0:
            print(f"[push] OK（第 {attempt} 次）")
            return True
        last = (p.stderr.strip().splitlines() or ["?"])[-1]
        print(f"[push] 第 {attempt}/{tries} 次失败: {last}")
        if attempt < tries:
            time.sleep(PUSH_BACKOFF_SECONDS * attempt)
    print("[push] 全部失败。手动重试：")
    print(f"  git -C {repo} " + " ".join(extra) + f" push origin {branch}")
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--msg-file", required=True)
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--allow-empty", action="store_true")
    a = ap.parse_args(argv)

    repo = Path(a.repo)
    if not (repo / ".git").exists():
        print(f"[FAIL] 不是 git 仓库: {repo}")
        return 1

    for f in a.files:
        if not (repo / f).exists():
            print(f"[FAIL] 文件不存在: {f}")
            return 1

    msg = Path(a.msg_file).read_text(encoding="utf-8").strip()
    if not msg:
        print("[FAIL] message 为空")
        return 1

    run(repo, "add", "--", *a.files)
    staged = run(repo, "diff", "--cached", "--name-only").stdout.strip()
    if not staged and not a.allow_empty:
        print("[SKIP] 暂存区为空，没有可提交的改动")
        return 0
    print(f"[add] {len(staged.splitlines())} 个文件")

    # -c 必须在子命令前：i18n.commitEncoding=utf-8 保证 message 按 UTF-8 落盘
    run(
        repo,
        "-c",
        "i18n.commitEncoding=utf-8",
        "commit",
        "-F",
        str(Path(a.msg_file).resolve()),
    )

    head = run(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    raw = run(repo, "cat-file", "commit", "HEAD").stdout
    # 头部固定 4 行（tree/parent/author/committer）+ 1 空行，subject 在第 5 行起第一个非空行
    subject = next((line for line in raw.splitlines()[4:] if line.strip()), "")
    print(f"[commit] {head}  {subject}")

    pushed = True
    if not a.no_push:
        remotes = run(repo, "remote").stdout.split()
        if not remotes:
            print("[push] 无 remote，跳过")
        else:
            branch = run(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            pushed = push_branch(repo, branch)

    status = run(repo, "status", "--short").stdout.strip()
    print(f"[status] {'干净' if not status else status}")
    # 提交成功但推送失败必须返回非 0，否则调用方会以为闭环了
    return 0 if pushed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
