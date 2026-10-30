"""Mock 模式演示：给 Task 2 的 `BPlusTree` 加「范围删除 + 迭代器」。

两个角色都是脚本化的假人（0 成本），目的只有一个：
**用真代码、真 pytest、真熔断 跑一遍完整对抗**，证明编排链路是通的。

剧本：
- 第 1 轮 Dev 只加 `range_delete`，QA 的 5 条测试里有 2 条要求 `__iter__` → 红；
- 第 2 轮 Dev 补 `__iter__` → 全绿。

运行：`..\\.venv\\Scripts\\python.exe demo/run_mock_demo.py`
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from orchestrator.agent import Agent, AgentSpec
from orchestrator.budget import Caps
from orchestrator.loop import Orchestrator
from orchestrator.tmpdir import default_tmp_root
from orchestrator.workspace import RunWorkspace

MOCK = PROJECT / "tests" / "agents" / "mock_agent.py"
TASK2 = PROJECT.parent / "task2_lowlevel"
ANCHOR = "    def check_invariants(self) -> None:"

RANGE_DELETE = '''    def range_delete(self, lo: Any = None, hi: Any = None) -> int:
        """删掉 [lo, hi] 闭区间内的所有键，返回删掉的个数。"""
        victims = [k for k in self.keys() if (lo is None or k >= lo) and (hi is None or k <= hi)]
        for key in victims:
            self.delete(key)
        return len(victims)

'''

ITER = '''    def __iter__(self) -> Iterator[Any]:
        """按升序迭代键（委托叶子链，不另建列表）。"""
        return self.keys()

'''

QA_TESTS = '''import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bplus.memory import BPlusTree


def _tree(n=20, order=4):
    t = BPlusTree(order=order)
    for i in range(n):
        t.insert(i, i * 10)
    return t


def test_range_delete_basic():
    t = _tree()
    assert t.range_delete(5, 10) == 6
    assert list(t.keys()) == [k for k in range(20) if not 5 <= k <= 10]
    t.check_invariants()


def test_range_delete_bounds_inclusive():
    t = _tree()
    assert t.range_delete(0, 0) == 1
    assert 0 not in t
    t.check_invariants()


def test_range_delete_empty_result():
    t = _tree()
    assert t.range_delete(100, 200) == 0
    assert len(t) == 20


def test_iter_is_sorted():
    t = _tree()
    assert [k for k in t] == list(range(20))


def test_iter_after_delete():
    t = _tree()
    t.range_delete(3, 7)
    assert [k for k in t] == [k for k in range(20) if not 3 <= k <= 7]
'''


def _home(base: Path, name: str, script: dict) -> Agent:
    home = base / f"home-{name}"
    home.mkdir(parents=True, exist_ok=True)
    (home / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    return Agent(AgentSpec(name=name, cmd=(sys.executable, str(MOCK)), timeout_s=120), home=home)


def main() -> int:
    # 不用系统 Temp：本机那份建文件会卡死（见 orchestrator/tmpdir.py）
    tmp = Path(tempfile.mkdtemp(prefix="orch-demo-", dir=str(default_tmp_root())))
    dev_script = {
        "1": {"replace": {"bplus/memory.py": [[ANCHOR, RANGE_DELETE + ANCHOR]]}, "tokens": 4_200},
        "default": {"replace": {"bplus/memory.py": [[ANCHOR, ITER + RANGE_DELETE + ANCHOR]]}, "tokens": 3_100},
    }
    qa_script = {"default": {"writes": {"tests/test_bplus_extra.py": QA_TESTS}, "tokens": 2_600}}

    dev = _home(tmp, "dev", dev_script)
    qa = _home(tmp, "qa", qa_script)

    ws = RunWorkspace.create()
    try:
        ws.copy_tree(TASK2 / "bplus", "bplus", "*.py")
        ws.write("bplus/__init__.py", "")
        print(f"起始代码：{len(ws.list_files())} 个 py → {ws.root}")

        orch = Orchestrator(
            dev,
            qa,
            ws,
            caps=Caps(max_rounds=6, wall_clock_s=15 * 60, token_budget=200_000),
        )
        report = orch.run("给 BPlusTree 加 range_delete(lo, hi) 闭区间批量删除，并让它可被 for 迭代（升序）")
        print()
        print("\n".join(report.lines()))
        print()
        print(f"判定：{'通过' if report.passed else '未通过'}（判定依据只有 pytest 退出码）")
        return 0 if report.passed else 1
    finally:
        dev.cleanup()
        qa.cleanup()
        ws.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
