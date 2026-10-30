"""活体演示：让真 qwen2.5:3b 当 Dev 改代码、当真 QA 写测试，编排器用 pytest 判分。

与 mock 演示的区别：mock 是"剧本"，这里是**真的让模型读代码、写代码**，会犯错、会不符合
格式，所以更能验证熔断/卡死判定/退出码裁决这些机制在真实噪声下还站得住。

成本：本地推理，¥0（只烧电）。开跑前请确认 Ollama 在跑、qwen2.5:3b 已拉。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.agent import Agent, AgentSpec  # noqa: E402
from orchestrator.budget import Caps  # noqa: E402
from orchestrator.loop import Orchestrator  # noqa: E402
from orchestrator.workspace import RunWorkspace  # noqa: E402

AGENT = ROOT / "agents" / "ollama_agent.py"

SEED = '''"""一个小计算模块，供演示用。"""


def add(a: float, b: float) -> float:
    return a + b


def mul(a: float, b: float) -> float:
    return a * b
'''

TASK = (
    "在 calc.py 里新增两个函数：\n"
    "1. safe_div(a, b)：返回 a 除以 b；当 b 等于 0 时抛出 ValueError('division by zero')。\n"
    "2. clamp(x, lo, hi)：把 x 限制在 [lo, hi] 区间内；当 lo > hi 时抛出 ValueError。\n"
    "保持 add/mul 不变。QA 请为这两个函数各写测试，覆盖：正常值、除零、区间上下界、lo>hi。"
)


def main() -> int:
    tmp_base = ROOT / ".tmp"
    tmp_base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="orch-live-", dir=str(tmp_base)))

    ws = RunWorkspace.create(root)
    ws.write("calc.py", SEED)

    dev = Agent(AgentSpec("dev", (sys.executable, str(AGENT)), timeout_s=300))
    qa = Agent(AgentSpec("qa", (sys.executable, str(AGENT)), timeout_s=300))

    orch = Orchestrator(
        dev,
        qa,
        ws,
        caps=Caps(max_rounds=3, wall_clock_s=600.0, token_budget=200_000),
    )

    print("任务：", TASK.replace("\n", " ")[:80], "…")
    print("工作区：", ws.root)
    report = orch.run(TASK)
    for line in report.lines():
        print(line)
    print("补丁落盘：")
    for f in sorted(ws.list_files()):
        p = ws.path(f)
        print(f"  {f}  ({p.stat().st_size if p.exists() else 0} B)")

    if report.passed:
        print("\n[OK] 真模型两轮内收敛")
    else:
        print(f"\n[FAIL] 未通过：{report.status} {report.reason}")

    # 保留工作区供人工看（.tmp 下会被清理），这里打印路径
    print("工作区留在：", ws.root)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
