"""命令行入口：默认 mock（0 成本），真 LLM 必须显式承认花费才开。

    python -m orchestrator.cli --task "给 BPlusTree 加 range_delete 和迭代器"
    python -m orchestrator.cli --mode live --i-know-the-cost --task "..."

live 模式下 dev/qa 的命令从环境变量读：
    DSH_LIVE_DEV_CMD / DSH_LIVE_QA_CMD   （含参数的完整命令行，空格分隔）
没配就不许开——宁可报错，也不要偷偷烧钱。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agent import Agent, AgentSpec
from .budget import Caps
from .loop import Orchestrator
from .workspace import RunWorkspace

DEFAULT_MOCK_AGENT = str(Path(__file__).resolve().parents[1] / "tests" / "agents" / "mock_agent.py")


class LiveModeRefused(RuntimeError):
    pass


def build_agents(mode: str, i_know_the_cost: bool = False, mock_script_dir: str | None = None) -> tuple[Agent, Agent]:
    """造两个角色。live 模式的三道闸：显式开关 + 两条命令都配了 + 预算仍在。"""
    if mode not in {"mock", "live"}:
        raise ValueError(f"未知 mode：{mode}")

    if mode == "mock":
        base = Path(mock_script_dir) if mock_script_dir else None
        dev = Agent(AgentSpec("dev", (sys.executable, DEFAULT_MOCK_AGENT)), home=base / "dev" if base else None)
        qa = Agent(AgentSpec("qa", (sys.executable, DEFAULT_MOCK_AGENT)), home=base / "qa" if base else None)
        return dev, qa

    if not i_know_the_cost:
        raise LiveModeRefused("live 模式会真的调模型烧钱：加 --i-know-the-cost 才允许启动")
    cmds = {}
    for role in ("dev", "qa"):
        raw = os.environ.get(f"DSH_LIVE_{role.upper()}_CMD", "").strip()
        if not raw:
            raise LiveModeRefused(f"缺环境变量 DSH_LIVE_{role.upper()}_CMD（live 模式必须显式给命令）")
        cmds[role] = tuple(raw.split())
    return (
        Agent(AgentSpec("dev", cmds["dev"], timeout_s=600)),
        Agent(AgentSpec("qa", cmds["qa"], timeout_s=600)),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestrator", description="Dev/QA 对抗编排器（默认 mock，0 成本）")
    p.add_argument("--task", required=True, help="要 Dev 实现的题目")
    p.add_argument("--mode", choices=("mock", "live"), default="mock")
    p.add_argument("--i-know-the-cost", action="store_true", help="live 模式必须显式确认会花钱")
    p.add_argument("--seed-dir", default=None, help="把该目录下的 .py 拷进工作区当起始代码")
    p.add_argument("--seed-rel", default=".", help="拷到工作区的哪个子目录（默认根）")
    p.add_argument("--max-rounds", type=int, default=6)
    p.add_argument("--wall-clock", type=float, default=15 * 60.0)
    p.add_argument("--token-budget", type=int, default=200_000)
    p.add_argument("--keep", action="store_true", help="跑完保留工作区（默认删除）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dev, qa = build_agents(args.mode, args.i_know_the_cost)
    except LiveModeRefused as exc:
        print(f"[拒绝启动] {exc}", file=sys.stderr)
        return 2

    ws = RunWorkspace.create()
    try:
        if args.seed_dir:
            seeded = ws.copy_tree(Path(args.seed_dir), args.seed_rel if args.seed_rel != "." else "")
            print(f"起始代码：{len(seeded)} 个文件（{args.seed_dir}）")
        orch = Orchestrator(
            dev,
            qa,
            ws,
            caps=Caps(max_rounds=args.max_rounds, wall_clock_s=args.wall_clock, token_budget=args.token_budget),
        )
        report = orch.run(args.task)
        print("\n".join(report.lines()))
        print(f"工作区：{ws.root}")
        return 0 if report.passed else 1
    finally:
        dev.cleanup()
        qa.cleanup()
        if not args.keep:
            ws.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
