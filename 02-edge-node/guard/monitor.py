"""压力与温度守卫。

两件事：
1. 利用率连续 N 个采样都超过 70% → 报一次 `util_pressure`（只报一次，别刷屏）。
   注意这是**告警**不是**拦截**：Ollama 一提交推理 SM 就是满的，拦不住也不该拦。
2. 温度超过 86℃ → 冷却 60 秒（`thermal_cooldown`），期间 is_cooling() 为真，
   调用方据此拒绝新请求（这才是真正能执行的那道闸）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .gpu import GpuSample

__all__ = ["PressureGuard"]

DEFAULT_UTIL_RATIO = 0.70
DEFAULT_TEMP_LIMIT_C = 86
DEFAULT_CONSECUTIVE = 3
DEFAULT_COOLDOWN_S = 60.0


class PressureGuard:
    def __init__(
        self,
        util_ratio: float = DEFAULT_UTIL_RATIO,
        temp_limit_c: int = DEFAULT_TEMP_LIMIT_C,
        consecutive: int = DEFAULT_CONSECUTIVE,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if consecutive < 1:
            raise ValueError("consecutive 至少为 1")
        self._util_ratio = float(util_ratio)
        self._temp_limit_c = int(temp_limit_c)
        self._consecutive = int(consecutive)
        self._cooldown_s = float(cooldown_s)
        self._clock = clock or time.monotonic
        self._hot_streak = 0
        self._pressure_announced = False
        self._cooldown_until = 0.0

    def observe(self, sample: GpuSample) -> list[str]:
        events: list[str] = []
        now = self._clock()

        if sample.util_pct / 100.0 > self._util_ratio:
            self._hot_streak += 1
            if self._hot_streak >= self._consecutive and not self._pressure_announced:
                self._pressure_announced = True
                events.append("util_pressure")
        else:
            self._hot_streak = 0
            self._pressure_announced = False

        if sample.temp_c > self._temp_limit_c and now >= self._cooldown_until:
            self._cooldown_until = now + self._cooldown_s
            events.append("thermal_cooldown")

        return events

    def is_cooling(self) -> bool:
        return self._clock() < self._cooldown_until

    def cooldown_remaining_s(self) -> float:
        return max(0.0, self._cooldown_until - self._clock())
