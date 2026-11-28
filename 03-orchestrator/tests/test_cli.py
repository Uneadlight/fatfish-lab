"""CLI 入口的验收：三道闸、参数默认值、main() 的返回码。

cli.py 之前只有 45% 覆盖——入口参数解析一行没测。这里补上：
进程退出的返回值（0/1/2）是它唯一对外承诺的契约，不能靠"跑起来看着对"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator import cli


# --------------------------------------------------------------------------- #
# build_agents：mock / live 三分支
# --------------------------------------------------------------------------- #
def test_build_agents_mock_returns_dev_and_qa():
    dev, qa = cli.build_agents("mock")
    try:
        assert dev.spec.name == "dev"
        assert qa.spec.name == "qa"
        # mock 模式用当前解释器跑 mock_agent.py，不是真 LLM
        assert dev.spec.cmd[0] == sys.executable
        assert dev.spec.cmd[-1].endswith("mock_agent.py")
    finally:
        dev.cleanup()
        qa.cleanup()


def test_build_agents_mock_honours_script_dir(tmp_path):
    dev, qa = cli.build_agents("mock", mock_script_dir=str(tmp_path))
    try:
        assert dev.home == tmp_path / "dev"
        assert qa.home == tmp_path / "qa"
    finally:
        dev.cleanup()
        qa.cleanup()


def test_build_agents_rejects_unknown_mode():
    with pytest.raises(ValueError, match="未知 mode"):
        cli.build_agents("dummy")


def test_build_agents_live_refuses_without_cost_ack():
    with pytest.raises(cli.LiveModeRefused, match="i-know-the-cost"):
        cli.build_agents("live", i_know_the_cost=False)


def test_build_agents_live_refuses_when_env_missing(monkeypatch):
    monkeypatch.delenv("DSH_LIVE_DEV_CMD", raising=False)
    monkeypatch.delenv("DSH_LIVE_QA_CMD", raising=False)
    with pytest.raises(cli.LiveModeRefused, match="DSH_LIVE_DEV_CMD"):
        cli.build_agents("live", i_know_the_cost=True)


def test_build_agents_live_refuses_when_only_qa_missing(monkeypatch):
    monkeypatch.setenv("DSH_LIVE_DEV_CMD", "dev-cli --x")
    monkeypatch.delenv("DSH_LIVE_QA_CMD", raising=False)
    with pytest.raises(cli.LiveModeRefused, match="DSH_LIVE_QA_CMD"):
        cli.build_agents("live", i_know_the_cost=True)


def test_build_agents_live_builds_agents_when_all_gates_pass(monkeypatch):
    monkeypatch.setenv("DSH_LIVE_DEV_CMD", "dev-cli --x 1")
    monkeypatch.setenv("DSH_LIVE_QA_CMD", "qa-cli --y")
    dev, qa = cli.build_agents("live", i_know_the_cost=True)
    try:
        assert dev.spec.cmd == ("dev-cli", "--x", "1")
        assert qa.spec.cmd == ("qa-cli", "--y")
        # live 模式单轮超时放宽到 600 秒
        assert dev.spec.timeout_s == 600
        assert qa.spec.timeout_s == 600
    finally:
        dev.cleanup()
        qa.cleanup()


def test_build_agents_live_ignores_blank_env(monkeypatch):
    monkeypatch.setenv("DSH_LIVE_DEV_CMD", "   ")
    monkeypatch.setenv("DSH_LIVE_QA_CMD", "qa-cli")
    with pytest.raises(cli.LiveModeRefused):
        cli.build_agents("live", i_know_the_cost=True)


# --------------------------------------------------------------------------- #
# build_parser：默认值就是文档承诺
# --------------------------------------------------------------------------- #
def test_parser_defaults():
    args = cli.build_parser().parse_args(["--task", "做点什么"])
    assert args.task == "做点什么"
    assert args.mode == "mock"
    assert args.i_know_the_cost is False
    assert args.seed_dir is None
    assert args.seed_rel == "."
    assert args.max_rounds == 6
    assert args.wall_clock == 15 * 60.0
    assert args.token_budget == 200_000
    assert args.keep is False


def test_parser_requires_task():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_parser_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--task", "x", "--mode", "prod"])


def test_parser_accepts_live_with_cost_flag():
    args = cli.build_parser().parse_args(
        ["--task", "x", "--mode", "live", "--i-know-the-cost", "--max-rounds", "2"]
    )
    assert args.mode == "live"
    assert args.i_know_the_cost is True
    assert args.max_rounds == 2


# --------------------------------------------------------------------------- #
# main()：对外只有返回码是承诺
# --------------------------------------------------------------------------- #
def test_main_live_without_ack_returns_2_and_writes_stderr(capsys):
    code = cli.main(["--task", "x", "--mode", "live"])
    assert code == 2
    err = capsys.readouterr().err
    assert "拒绝启动" in err
    assert "i-know-the-cost" in err


def test_main_live_without_env_returns_2(monkeypatch, capsys):
    monkeypatch.delenv("DSH_LIVE_DEV_CMD", raising=False)
    monkeypatch.delenv("DSH_LIVE_QA_CMD", raising=False)
    code = cli.main(["--task", "x", "--mode", "live", "--i-know-the-cost"])
    assert code == 2
    assert "DSH_LIVE_DEV_CMD" in capsys.readouterr().err


def test_main_mock_runs_one_round_and_reports(capsys):
    """mock 模式下真的跑一遍（--max-rounds 1 收敛），返回码只能是 0 或 1。"""
    code = cli.main(["--task", "给 BPlusTree 加 range_delete", "--max-rounds", "1", "--wall-clock", "60"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    # 跑完必须打出工作区路径
    assert "工作区：" in out


def test_main_with_seed_dir_copies_files(tmp_path, capsys):
    (tmp_path / "seed_a.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "seed_b.py").write_text("Y = 2\n", encoding="utf-8")
    code = cli.main(
        [
            "--task", "把种子文件补全",
            "--max-rounds", "1",
            "--wall-clock", "60",
            "--seed-dir", str(tmp_path),
            "--seed-rel", "src",
        ]
    )
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "起始代码：2 个文件" in out
