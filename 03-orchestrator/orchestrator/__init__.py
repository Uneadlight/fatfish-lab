"""Task 3：AgentOrchestrator —— 让两个"人"互相掐，但掐不出预算和规则之外。

设计底线（见 `进阶-20261029/RFC.md` §3.3）：

1. **角色隔离**：Dev / QA 各起独立子进程，各自有独立家目录（家目录互不在同一父目录下，
   彼此不可枚举）、独立 prompt、独立日志；orchestrator 只做转发。
2. **判定权只给 pytest 退出码**：QA 说"我觉得好了"不算数，`returncode == 0` 才算。
3. **三重熔断**：轮数 ≤6、墙钟 ≤15min、token ≤200K；任一超限立刻停，报原因而不是报成功。
4. **卡死判定**：连续两轮失败用例集完全相同 → 判 stall，提前终止并给诊断。
5. **默认 mock 0 成本**：真 LLM 只在 `--mode live --i-know-the-cost` 下才开。
"""

from .agent import Agent, AgentResult, AgentSpec
from .budget import Budget, BudgetExhausted, Caps
from .judge import Outcome, run_pytest
from .loop import Orchestrator, RoundRecord, RunReport
from .workspace import RunWorkspace

__all__ = [
    "Agent",
    "AgentResult",
    "AgentSpec",
    "Budget",
    "BudgetExhausted",
    "Caps",
    "Orchestrator",
    "Outcome",
    "RoundRecord",
    "RunReport",
    "RunWorkspace",
    "run_pytest",
]
