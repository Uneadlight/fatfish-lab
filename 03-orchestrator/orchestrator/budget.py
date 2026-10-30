"""三重熔断：轮数 / 墙钟 / token。

为什么三个都要：轮数管"最多折腾几次"，墙钟管"别把我挂在那"，token 管"别烧钱"。
任何一条失效都可能让对抗变成黑洞——RFC 里就是因为原指令没写终止条件才加的这块。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


class BudgetExhausted(Exception):
    """预算用尽。`reason` 是机读的短标识，报告里直接展示。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass
class Caps:
    max_rounds: int = 6
    wall_clock_s: float = 15 * 60.0
    token_budget: int = 200_000

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds 至少 1")
        if self.wall_clock_s <= 0:
            raise ValueError("wall_clock_s 必须 > 0")
        if self.token_budget < 1:
            raise ValueError("token_budget 至少 1")


class Budget:
    """记账本。时钟可注入，测试里用假时钟推进，不靠 sleep 拖时间。"""

    def __init__(self, caps: Caps | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.caps = caps or Caps()
        self._clock = clock
        self._started_at: float | None = None
        self._round = 0
        self.tokens = 0
        self.dev_tokens = 0
        self.qa_tokens = 0

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self) -> None:
        self._started_at = self._clock()

    @property
    def elapsed_s(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    @property
    def round_index(self) -> int:
        return self._round

    def begin_round(self) -> int:
        """开一轮。超轮数直接抛，调用方把它翻译成 `rounds_exhausted`。"""
        if self._started_at is None:
            raise RuntimeError("先 start()")
        if self._round >= self.caps.max_rounds:
            raise BudgetExhausted("rounds_exhausted", f"已用 {self._round}/{self.caps.max_rounds} 轮")
        self._round += 1
        return self._round

    def add_tokens(self, n: int, who: str = "") -> None:
        """记 token。负数按 0 处理（子进程报了怪数字时不要把账算反）。"""
        n = max(0, int(n))
        self.tokens += n
        if who == "dev":
            self.dev_tokens += n
        elif who == "qa":
            self.qa_tokens += n

    # -- 检查 -------------------------------------------------------------- #
    def check(self) -> None:
        """每轮结束调一次；超墙钟或超 token 立刻抛。"""
        if self.elapsed_s > self.caps.wall_clock_s:
            raise BudgetExhausted(
                "time_exhausted", f"已用 {self.elapsed_s:.1f}s / 上限 {self.caps.wall_clock_s:.0f}s"
            )
        if self.tokens > self.caps.token_budget:
            raise BudgetExhausted("budget_exhausted", f"已用 {self.tokens} / 上限 {self.caps.token_budget} token")

    def projected(self) -> dict[str, float]:
        """给报告用的用量快照。"""
        return {
            "rounds": self._round,
            "max_rounds": self.caps.max_rounds,
            "tokens": self.tokens,
            "token_budget": self.caps.token_budget,
            "elapsed_s": round(self.elapsed_s, 3),
            "wall_clock_s": self.caps.wall_clock_s,
        }
