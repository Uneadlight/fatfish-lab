"""Task 3 验收：编排器的契约（熔断、判定权、隔离、卡死）。

这里是"先写断言再写实现"的那一半——每个用例都对应 RFC §3.3 里的一条硬要求。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.agent import Agent, AgentSpec
from orchestrator.budget import Budget, BudgetExhausted, Caps
from orchestrator.judge import run_pytest
from orchestrator.loop import Orchestrator
from orchestrator.workspace import RunWorkspace, WorkspaceError

MOCK = Path(__file__).resolve().parent / "agents" / "mock_agent.py"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
class FakeClock:
    def __init__(self, step: float = 0.0) -> None:
        self.t = 1000.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def make_agent(tmp: Path, name: str, script: dict, cmd=None) -> Agent:
    home = tmp / f"home-{name}"
    home.mkdir(parents=True, exist_ok=True)
    (home / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    spec = AgentSpec(name=name, cmd=cmd or (sys.executable, str(MOCK)), timeout_s=60)
    return Agent(spec, home=home)


CALC_GOOD = "def add_range(n):\n    return sum(range(n + 1))\n"
CALC_BAD = "def add_range(n):\n    return 0\n"
TEST_CALC = (
    "import sys, pathlib\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
    "from calc import add_range\n\n"
    "def test_zero():\n    assert add_range(0) == 0\n\n"
    "def test_ten():\n    assert add_range(10) == 55\n"
)


# --------------------------------------------------------------------------- #
# 预算
# --------------------------------------------------------------------------- #
def test_budget_rounds_exhausted():
    budget = Budget(Caps(max_rounds=2))
    budget.start()
    assert budget.begin_round() == 1
    assert budget.begin_round() == 2
    with pytest.raises(BudgetExhausted) as err:
        budget.begin_round()
    assert err.value.reason == "rounds_exhausted"


def test_budget_token_and_time_exhausted():
    clock = FakeClock(step=10.0)
    budget = Budget(Caps(max_rounds=99, wall_clock_s=25, token_budget=1000), clock=clock)
    budget.start()
    budget.start()          # 记起点
    budget.add_tokens(600)
    budget.check()          # 未超
    budget.add_tokens(600)
    with pytest.raises(BudgetExhausted) as err:
        budget.check()
    assert err.value.reason == "budget_exhausted"

    clock2 = FakeClock(step=30.0)
    budget2 = Budget(Caps(wall_clock_s=25), clock=clock2)
    budget2.start()
    with pytest.raises(BudgetExhausted) as err2:
        budget2.check()
    assert err2.value.reason == "time_exhausted"


def test_budget_negative_tokens_ignored():
    budget = Budget(Caps())
    budget.start()
    budget.add_tokens(-500, "dev")
    assert budget.tokens == 0


# --------------------------------------------------------------------------- #
# 工作区
# --------------------------------------------------------------------------- #
def test_workspace_rejects_escape(tmp_path):
    ws = RunWorkspace.create()
    try:
        with pytest.raises(WorkspaceError):
            ws.write("../逃出去.txt", "x")
        with pytest.raises(WorkspaceError):
            ws.write("C:/Windows/x.txt", "x")
        ws.seed({"pkg/a.py": "x = 1\n"})
        assert ws.read("pkg/a.py") == "x = 1\n"
        snap = ws.snapshot()
        assert "pkg/a.py" in snap
    finally:
        ws.cleanup()


# --------------------------------------------------------------------------- #
# 裁判：只认退出码
# --------------------------------------------------------------------------- #
def test_judge_green_and_red(tmp_path):
    (tmp_path / "calc.py").write_text(CALC_GOOD, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    green = run_pytest(tmp_path)
    assert green.ran and green.passed and green.returncode == 0

    (tmp_path / "calc.py").write_text(CALC_BAD, encoding="utf-8")
    red = run_pytest(tmp_path)
    assert red.ran and not red.passed
    assert any("test_ten" in t for t in red.failed_ids)


def test_judge_no_tests_is_not_pass(tmp_path):
    outcome = run_pytest(tmp_path)
    assert outcome.returncode == 5
    assert not outcome.passed
    assert outcome.failed_ids == ("no-tests-collected",)


def test_judge_not_fooled_by_stale_bytecode(tmp_path):
    """同一秒内改成"同样大小"的新源码：不删 __pycache__ 就会拿旧字节码判决。"""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
        "from calc import add_range\n\n"
        "def test_ten():\n    assert add_range(10) == 55\n",
        encoding="utf-8",
    )
    good = "def add_range(n):\n    return 55\n"
    bad = "def add_range(n):\n    return -1\n"
    (tmp_path / "calc.py").write_text(good, encoding="utf-8")
    first = run_pytest(tmp_path)
    assert first.passed, first.tail

    import compileall

    compileall.compile_dir(str(tmp_path), quiet=1)   # 先造出 calc.cpython-*.pyc
    assert len(bad) == len(good)
    (tmp_path / "calc.py").write_text(bad, encoding="utf-8")
    again = run_pytest(tmp_path)
    assert not again.passed, "读到旧字节码了：judge 没清 __pycache__"
    assert any("test_ten" in t for t in again.failed_ids)


# --------------------------------------------------------------------------- #
# 编排器：主流程
# --------------------------------------------------------------------------- #
def _orchestrator(tmp_path, dev_script, qa_script, **kwargs):
    ws = RunWorkspace.create()
    ws.seed({"calc.py": CALC_BAD})
    dev = make_agent(tmp_path, "dev", dev_script)
    qa = make_agent(tmp_path, "qa", qa_script)
    caps = kwargs.pop("caps", Caps())
    orch = Orchestrator(dev, qa, ws, caps=caps, **kwargs)
    return orch, ws


def test_passes_on_second_round(tmp_path):
    dev = {"1": {"writes": {"calc.py": CALC_BAD}, "tokens": 800},
           "default": {"writes": {"calc.py": CALC_GOOD}, "tokens": 900}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 700}}
    orch, ws = _orchestrator(tmp_path, dev, qa)
    try:
        report = orch.run("实现 add_range(n) = 0..n 的和")
        assert report.status == "passed", report.lines()
        assert report.rounds_used == 2
        assert report.tokens == (800 + 700) + (900 + 700)
        assert report.rounds[0].outcome.passed is False
        assert report.rounds[1].outcome.passed is True
    finally:
        ws.cleanup()


def test_stalled_when_failures_repeat(tmp_path):
    dev = {"default": {"writes": {"calc.py": CALC_BAD}, "tokens": 100}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 100}}
    orch, ws = _orchestrator(tmp_path, dev, qa, caps=Caps(max_rounds=6))
    try:
        report = orch.run("实现 add_range")
        assert report.status == "stalled", report.lines()
        assert report.rounds_used == 2
        assert "连续 2 轮" in report.reason
    finally:
        ws.cleanup()


def test_max_rounds_exhausted(tmp_path):
    # 每轮换一种"错法"→ 失败集不同 → 不判卡死，让轮数上限来收场
    dev = {
        "1": {"writes": {"calc.py": CALC_BAD}, "tokens": 10},
        "2": {"writes": {"calc.py": "def add_range(n):\n    return 55\n"}, "tokens": 10},
        "default": {"writes": {"calc.py": "def add_range(n):\n    return -1\n"}, "tokens": 10},
    }
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 10}}
    orch, ws = _orchestrator(tmp_path, dev, qa, caps=Caps(max_rounds=3))
    try:
        report = orch.run("实现 add_range")
        assert report.status == "rounds_exhausted", report.lines()
        assert report.rounds_used == 3
    finally:
        ws.cleanup()


def test_token_budget_stops_the_loop(tmp_path):
    dev = {"default": {"writes": {"calc.py": CALC_BAD}, "tokens": 150_000}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 150_000}}
    orch, ws = _orchestrator(tmp_path, dev, qa, caps=Caps(max_rounds=6, token_budget=200_000))
    try:
        report = orch.run("实现 add_range")
        assert report.status == "budget_exhausted", report.lines()
        assert report.rounds_used == 1
        assert report.tokens == 300_000
    finally:
        ws.cleanup()


def test_wall_clock_stops_the_loop(tmp_path):
    dev = {"default": {"writes": {"calc.py": CALC_BAD}, "tokens": 10}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 10}}
    orch, ws = _orchestrator(tmp_path, dev, qa, caps=Caps(max_rounds=6, wall_clock_s=25), clock=FakeClock(10.0))
    try:
        report = orch.run("实现 add_range")
        assert report.status == "time_exhausted", report.lines()
        assert report.rounds_used == 1
    finally:
        ws.cleanup()


def test_agent_failure_aborts(tmp_path):
    dev = {"default": {"writes": {}, "tokens": 10, "fail": True}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 10}}
    orch, ws = _orchestrator(tmp_path, dev, qa)
    try:
        report = orch.run("实现 add_range")
        assert report.status == "agent_failed", report.lines()
        assert "dev" in report.reason
    finally:
        ws.cleanup()


# --------------------------------------------------------------------------- #
# 隔离
# --------------------------------------------------------------------------- #
def test_agent_homes_are_separate_and_not_leaked(tmp_path):
    dev = {"default": {"writes": {}, "tokens": 5, "probe": True}}
    qa = {"default": {"writes": {"tests/test_calc.py": TEST_CALC}, "tokens": 5}}
    orch, ws = _orchestrator(tmp_path, dev, qa)
    try:
        orch.run("实现 add_range")
    finally:
        ws.cleanup()
    dev_home, qa_home = orch.dev.home, orch.qa.home
    assert dev_home != qa_home
    assert qa_home not in dev_home.parents and dev_home not in qa_home.parents
    probe = json.loads((dev_home / "probe-1.json").read_text(encoding="utf-8"))
    # 环境里不许出现另一个角色的家目录
    assert probe["leaked_env"] == []
    assert probe["other_keys"] == []


# --------------------------------------------------------------------------- #
# 命令行闸门
# --------------------------------------------------------------------------- #
def test_live_mode_requires_explicit_cost_flag():
    from orchestrator.cli import LiveModeRefused, build_agents

    with pytest.raises(LiveModeRefused) as err:
        build_agents("live", i_know_the_cost=False)
    assert "--i-know-the-cost" in str(err.value)


def test_live_mode_needs_commands_even_with_flag(monkeypatch):
    from orchestrator.cli import LiveModeRefused, build_agents

    monkeypatch.delenv("DSH_LIVE_DEV_CMD", raising=False)
    monkeypatch.delenv("DSH_LIVE_QA_CMD", raising=False)
    with pytest.raises(LiveModeRefused) as err:
        build_agents("live", i_know_the_cost=True)
    assert "DSH_LIVE_DEV_CMD" in str(err.value)


def test_mock_mode_builds_two_roles(tmp_path):
    from orchestrator.cli import build_agents

    dev, qa = build_agents("mock", mock_script_dir=str(tmp_path))
    try:
        assert dev.spec.name == "dev" and qa.spec.name == "qa"
        assert dev.home != qa.home
    finally:
        dev.cleanup()
        qa.cleanup()
