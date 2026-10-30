"""编排循环：Dev 改 → QA 写测试 → pytest 判决 → 复盘 → 下一轮。

顺序固定，判定权交给 judge，不交给任何一句话。
三轮之后还红就按"卡死"或"轮数用尽"收场，绝不允许它自己宣布成功。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .agent import Agent, AgentResult
from .budget import Budget, BudgetExhausted, Caps
from .judge import Outcome, run_pytest
from .workspace import RunWorkspace

DEV_PROMPT = """你是 Dev（实现者）。任务：
{task}

第 {round_no} 轮。规矩：
1. 只改 `{workspace}` 里的实现代码，**不要动 `tests/`**（测试由 QA 写）。
2. 上一轮判据（仅供参考，不能自己宣布通过）：
{last_judge}
3. 改完就停，不要自言自语汇报"已完成"。
"""

QA_PROMPT = """你是 QA（验收者）。任务：
{task}

第 {round_no} 轮。规矩：
1. 在 `{workspace}/tests/` 下写 pytest 用例，覆盖任务要求的边界。
2. 你**没有判定权**：绿不绿由 pytest 退出码决定，你说"没问题"不算数。
3. 不要修改实现代码，只写测试。
"""


@dataclass
class RoundRecord:
    n: int
    dev: AgentResult
    qa: AgentResult
    outcome: Outcome
    tokens: int
    elapsed_s: float

    def line(self) -> str:
        return (
            f"#{self.n} dev={'ok' if self.dev.ok else 'fail'} qa={'ok' if self.qa.ok else 'fail'} "
            f"{self.outcome.summary()} tokens={self.tokens}"
        )


@dataclass
class RunReport:
    status: str
    rounds: list[RoundRecord] = field(default_factory=list)
    reason: str = ""
    workspace: str = ""
    elapsed_s: float = 0.0
    tokens: int = 0
    budget: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def rounds_used(self) -> int:
        return len(self.rounds)

    def lines(self) -> list[str]:
        out = [f"状态：{self.status}" + (f"（{self.reason}）" if self.reason else "")]
        out += [f"  {r.line()}" for r in self.rounds]
        out.append(
            f"用量：{self.tokens} token / {self.elapsed_s:.1f}s / {self.rounds_used} 轮"
        )
        return out


class Orchestrator:
    def __init__(
        self,
        dev: Agent,
        qa: Agent,
        workspace: RunWorkspace,
        caps: Caps | None = None,
        clock: Callable[[], float] = time.monotonic,
        judge: Callable[[object], Outcome] = run_pytest,
        stall_repeats: int = 2,
    ) -> None:
        self.dev = dev
        self.qa = qa
        self.ws = workspace
        self.budget = Budget(caps or Caps(), clock=clock)
        self._judge = judge
        self.stall_repeats = max(2, stall_repeats)

    # -- 主循环 ------------------------------------------------------------ #
    def run(self, task: str) -> RunReport:
        self.budget.start()
        report = RunReport(status="rounds_exhausted", workspace=str(self.ws.root))
        last_failed: tuple[str, ...] = ()
        same_streak = 0
        last_judge = "（第一轮，还没有判据）"

        try:
            while True:
                n = self.budget.begin_round()
                round_started = self.budget.elapsed_s

                dev = self.dev.run(
                    DEV_PROMPT.format(task=task, round_no=n, workspace=self.ws.root, last_judge=last_judge),
                    workspace=self.ws.root,
                    round_no=n,
                )
                self.budget.add_tokens(dev.tokens, "dev")
                qa = self.qa.run(
                    QA_PROMPT.format(task=task, round_no=n, workspace=self.ws.root),
                    workspace=self.ws.root,
                    round_no=n,
                )
                self.budget.add_tokens(qa.tokens, "qa")

                outcome = self._judge(self.ws.root)
                tokens = dev.tokens + qa.tokens
                report.rounds.append(
                    RoundRecord(
                        n=n,
                        dev=dev,
                        qa=qa,
                        outcome=outcome,
                        tokens=tokens,
                        elapsed_s=round(self.budget.elapsed_s - round_started, 3),
                    )
                )
                last_judge = f"{outcome.summary()}\n{outcome.tail[-800:]}"

                if not dev.ok or not qa.ok:
                    failing = dev if not dev.ok else qa
                    report.status = "agent_failed"
                    report.reason = f"{failing.name} 退出码 {failing.returncode}"
                    break

                if outcome.passed:
                    report.status = "passed"
                    break

                if outcome.failed_ids and outcome.failed_ids == last_failed:
                    same_streak += 1
                    if same_streak >= self.stall_repeats - 1:
                        report.status = "stalled"
                        report.reason = (
                            f"连续 {same_streak + 1} 轮失败用例集不变：{', '.join(outcome.failed_ids[:4])}"
                        )
                        break
                else:
                    same_streak = 0
                last_failed = outcome.failed_ids

                self.budget.check()
        except BudgetExhausted as exc:
            report.status = exc.reason
            report.reason = exc.detail
        finally:
            report.elapsed_s = round(self.budget.elapsed_s, 3)
            report.tokens = self.budget.tokens
            report.budget = self.budget.projected()
        return report
