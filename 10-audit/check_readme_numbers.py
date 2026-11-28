"""README 里的测试数字 vs 实际收集到的用例数。

起因：2026-11-28 发现 README 写「151 个用例（51 护栏 + 71 底层 + 29 编排器）」，
实际跑出来是 51 + 111 + 29 = 191——底层那栏从 71 涨到 111，README 没跟着改。
根因不是「忘了改」，是那个数字**手写在一个永远不会被检查的地方**。

用法：
    python 10-audit/check_readme_numbers.py          # 只检查，不一致返回 1
    python 10-audit/check_readme_numbers.py --fix    # 顺便把 README 改对
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# (目录, README 里给它起的名字)
DIRS = [
    ("01-lowlevel", "底层"),
    ("02-edge-node", "护栏"),
    ("03-orchestrator", "编排器"),
]

PATTERN = re.compile(r"测试规模\s*\*\*(\d+)\s*个用例\*\*（([^）]+)）")

# 跑 pytest 用哪个解释器。默认当前解释器，可用 CHECK_PYTHON 覆盖。
# 必须可指定：同一个仓库在 3.10 下收集到 72 个、3.12 下收集到 111 个，
# 数字取决于用哪个 Python 跑——这不是小事，是「这个数字能不能复现」的前提。
PYTHON = os.environ.get("CHECK_PYTHON", sys.executable)


BADGE_ALT = re.compile(r"(Tests: )(\d+)( passed)")
BADGE_URL = re.compile(r"(Tests-)(\d+)(%20passed)")


def collected(path: Path) -> int:
    """-q --collect-only 的最后一行形如 `111 tests collected in 0.05s`。"""
    r = subprocess.run(
        [PYTHON, "-m", "pytest", "-q", "--collect-only"],
        cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    m = re.search(r"(\d+)\s+tests? collected", r.stdout)
    if not m:
        raise RuntimeError(f"{path.name}: 拿不到用例数\n{r.stdout[-400:]}")
    return int(m.group(1))


def main() -> int:
    text = README.read_bytes().decode("utf-8")
    m = PATTERN.search(text)
    if not m:
        print("[FAIL] README 里找不到「测试规模 **N 个用例**（...）」这句话")
        return 1

    claimed_total = int(m.group(1))
    claimed_parts = {}
    for part in m.group(2).split("+"):
        mm = re.match(r"\s*(\d+)\s*(\S+)", part)
        if mm:
            claimed_parts[mm.group(2)] = int(mm.group(1))

    actual = {}
    for dirname, label in DIRS:
        actual[label] = collected(ROOT / dirname)
    actual_total = sum(actual.values())
    print(f"[解释器] {PYTHON}")

    ok = True
    for label, n in actual.items():
        old = claimed_parts.get(label)
        mark = "OK  " if old == n else "DIFF"
        if old != n:
            ok = False
        print(f"[{mark}] {label}: README 写 {old} / 实际 {n}")
    if claimed_total != actual_total:
        ok = False
    print(f"[{'OK  ' if claimed_total == actual_total else 'DIFF'}] 合计: README 写 {claimed_total} / 实际 {actual_total}")

    if ok:
        print("\nREADME 的测试数字与实际一致。")
        return 0

    print("\n不一致。修法：`--fix` 自动改，或手工改 README 那一行。")
    if "--fix" in sys.argv:
        fixed = PATTERN.sub(
            f"测试规模 **{actual_total} 个用例**（"
            + " + ".join(f"{actual[label]} {label}" for _, label in DIRS)
            + "）",
            text, count=1,
        )
        # 徽章是 URL 编码的 `Tests-191%20passed`，正文正则是抓不到的，单独同步
        n_badge = 0
        for pat in (BADGE_ALT, BADGE_URL):
            fixed, k = pat.subn(lambda mm: mm.group(1) + str(actual_total) + mm.group(3), fixed, count=1)
            n_badge += k
        README.write_bytes(fixed.encode("utf-8"))
        print(f"已写回 README（正文 + {n_badge} 处徽章）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
