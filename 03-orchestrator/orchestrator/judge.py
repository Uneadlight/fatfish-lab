"""裁判：只认 pytest 退出码。

这条是整个编排器的地基——QA 是 LLM，它会说"我觉得已经没问题了"。
所以判定权从自然语言手里拿走，交给 `returncode`：0 才算绿，其余一律红，
连"没收集到测试"（exit 5）也算红，否则空测试集会被误判成通过。
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR)\s+([^\s:]+(?:::[^\s]+)?)", re.MULTILINE)
_COUNT_LINE = re.compile(r"(\d+) (passed|failed|error|errors|collected)")


@dataclass
class Outcome:
    ran: bool
    returncode: int
    passed: bool
    failed_ids: tuple[str, ...] = ()
    tail: str = ""
    duration_s: float = 0.0
    extra: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        if not self.ran:
            return f"pytest 没跑起来（rc={self.returncode}）"
        if self.passed:
            return f"pytest 全绿（rc=0, {self.duration_s:.2f}s）"
        ids = ", ".join(self.failed_ids[:4]) or "?"
        more = "" if len(self.failed_ids) <= 4 else f" 等 {len(self.failed_ids)} 个"
        return f"pytest 红（rc={self.returncode}）：{ids}{more}"


def _tail(text: str, limit: int = 4000) -> str:
    text = text.strip()
    return text if len(text) <= limit else "…\n" + text[-limit:]


def purge_bytecode(root: str | Path) -> int:
    """删掉工作区里的 `__pycache__`，返回删掉的目录数。

    为什么必须在判决前做：CPython 的 `.pyc` 校验用 (mtime 秒级, 文件大小)。
    Dev 在**同一秒内**改出一个大小相同的新文件时，大小和 mtime 都没变，
    解释器会复用旧字节码 —— 于是 pytest 判的是**上一轮**的代码。
    这个坑不删缓存就会随机出现，归因还很花时间（实测踩到：return 55 → return -1 同为 31 字节）。
    """
    import shutil

    removed = 0
    for p in Path(root).rglob("__pycache__"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
    return removed


def run_pytest(
    cwd: str | Path,
    args: tuple[str, ...] = ("-q", "--no-header", "-p", "no:cacheprovider"),
    timeout_s: float = 180.0,
    python: str = sys.executable,
) -> Outcome:
    cwd = Path(cwd)
    purge_bytecode(cwd)     # 见函数注释：不删就会拿旧字节码判决
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [python, "-m", "pytest", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env={**_base_env(), "PYTHONPATH": str(cwd)},
        )
    except subprocess.TimeoutExpired:
        return Outcome(
            ran=True,
            returncode=-9,
            passed=False,
            failed_ids=("pytest-timeout",),
            tail=f"pytest 超过 {timeout_s:.0f}s 未结束，杀掉了",
            duration_s=round(time.monotonic() - started, 3),
        )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    failed = tuple(dict.fromkeys(_FAIL_LINE.findall(output)))
    counts = " ".join(f"{n}{kind}" for n, kind in _COUNT_LINE.findall(output))
    ran = bool(failed) or "passed" in output or "failed" in output or "error" in output or proc.returncode != 5
    passed = proc.returncode == 0 and bool(counts) and "no tests ran" not in output
    if proc.returncode == 5:
        failed = ("no-tests-collected",)
        passed = False
    return Outcome(
        ran=ran,
        returncode=proc.returncode,
        passed=passed,
        failed_ids=failed,
        tail=_tail(output),
        duration_s=round(time.monotonic() - started, 3),
        extra={"counts": counts},
    )


def _base_env() -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH"}}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env
