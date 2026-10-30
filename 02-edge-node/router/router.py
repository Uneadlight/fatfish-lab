"""ModelRouter：规则分流 + 超时降级 + 熔断 + 串行闸门。

一次 call 的流程：
    classify → 定顺序 [首选, 备用]
    → 要跑本地？先过温度闸门（采样 + PressureGuard.is_cooling）→ 冷却中就直接跳云端
    → 首选熔断中？→ 记 circuit_open，直接试备用
    → 串行队列里跑（线程 + join(timeout) 实现超时）
    → 超时/异常：记失败，试备用
    → 成功：返回 CallResult（带完整 fallback_chain，能回溯这次绕了几道弯）

熔断：连续 failure_threshold 次失败 → 打开 open_seconds 秒；到期后半开放一次探针，
探针失败立刻重新打开。这样"本地模型崩了"不会让每个请求都白等 60s。

温度闸门：guard 给了就在每次跑本地前采样一次（sampler 可选），把样本喂给守卫；
守卫说在冷却（>86℃ 触发 60s）就跳过本地走云端 —— 这是唯一真正能执行的
"别把卡烤了"的手段（利用率 util% 拦不住，见 guard/monitor.py 的说明）。
采样失败按 fail-open 处理：放行本地，但链上记 `guard:sample_error`，不让
nvidia-smi 抽风把整个推理链打死。
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from guard.queue import SerialQueue

from .rules import classify

__all__ = [
    "AllTargetsFailed",
    "CallResult",
    "ModelRouter",
    "RouterTimeout",
]

DEFAULT_TIMEOUT_LOCAL = 60.0
DEFAULT_TIMEOUT_CLOUD = 120.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_OPEN_SECONDS = 60.0


class RouterTimeout(TimeoutError):
    """某个目标超时。"""


class AllTargetsFailed(RuntimeError):
    """首选和备用都死了。"""


@dataclass
class CallResult:
    target: str
    value: Any
    latency_s: float
    fallback_chain: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_est: float = 0.0


class _Breaker:
    """单个目标的熔断器。"""

    def __init__(self, threshold: int, open_seconds: float) -> None:
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.failures = 0
        self.opened_at: float | None = None

    def is_open(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        return (now - self.opened_at) < self.open_seconds

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self, now: float) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = now

    def state(self, now: float) -> str:
        if self.opened_at is None:
            return "closed"
        return "open" if self.is_open(now) else "half_open"


class ModelRouter:
    def __init__(
        self,
        local_fn: Callable[[str], Any],
        cloud_fn: Callable[[str], Any],
        *,
        clock: Callable[[], float] | None = None,
        timeout_local: float = DEFAULT_TIMEOUT_LOCAL,
        timeout_cloud: float = DEFAULT_TIMEOUT_CLOUD,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        open_seconds: float = DEFAULT_OPEN_SECONDS,
        concurrency: int = 1,
        needs_external_knowledge: bool = False,
        offline: bool = False,
        guard: Any | None = None,
        sampler: Any | None = None,
    ) -> None:
        self._fns = {"local": local_fn, "cloud": cloud_fn}
        self._timeouts = {"local": float(timeout_local), "cloud": float(timeout_cloud)}
        self._clock = clock or time.monotonic
        self._queue = SerialQueue(capacity=concurrency)
        self._breakers = {
            "local": _Breaker(failure_threshold, open_seconds),
            "cloud": _Breaker(failure_threshold, open_seconds),
        }
        self._needs_external = bool(needs_external_knowledge)
        self._offline = bool(offline)
        self._guard = guard
        self._sampler = sampler
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "calls": 0,
            "by_target": {"local": 0, "cloud": 0},
            "failures": {"local": 0, "cloud": 0},
            "timeouts": {"local": 0, "cloud": 0},
            "skipped": {"local": 0, "cloud": 0},
            "blocked": {"local": 0, "cloud": 0},
            "rules": {},
        }

    # -- 内部 -------------------------------------------------------------- #
    def _invoke(self, name: str, prompt: str) -> Any:
        fn = self._fns[name]
        timeout = self._timeouts[name]
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["value"] = fn(prompt)
            except BaseException as exc:  # noqa: BLE001 - 原样转交给调用线程
                box["error"] = exc

        t = threading.Thread(target=target, name=f"router-{name}", daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise RouterTimeout(f"{name} 超过 {timeout}s 未返回")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _bump(self, bucket: str, name: str) -> None:
        with self._lock:
            self._stats[bucket][name] += 1

    def _gate_local(self, chain: list[str]) -> bool:
        """温度闸门：返回 True 表示"现在不许跑本地"。

        采样 → 喂守卫 → 看是否冷却。采样失败不阻断（fail-open），只留痕。
        """
        guard = self._guard
        if guard is None:
            return False
        if self._sampler is not None:
            try:
                events = guard.observe(self._sampler.sample())
            except Exception as exc:  # noqa: BLE001 - 采样失败不许影响主链路
                chain.append(f"guard:sample_error:{type(exc).__name__}")
            else:
                if "thermal_cooldown" in events:
                    chain.append("guard:thermal_cooldown")
        if not guard.is_cooling():
            return False
        remaining = 0.0
        with contextlib.suppress(Exception):  # 守卫可能没实现 cooldown_remaining_s
            remaining = float(guard.cooldown_remaining_s())
        chain.append(f"local:thermal_blocked({remaining:.0f}s)")
        return True

    # -- 对外 -------------------------------------------------------------- #
    def call(self, prompt: str, prefer: str = "auto") -> CallResult:
        started = time.monotonic()
        decision = classify(
            prompt,
            needs_external_knowledge=self._needs_external,
            concurrency=1,
            offline=self._offline,
        )

        if prefer == "local":
            order = ["local", "cloud"]
        elif prefer == "cloud":
            order = ["cloud", "local"]
        elif prefer not in ("auto",):
            raise ValueError(f"prefer 只能是 auto/local/cloud，收到 {prefer!r}")
        else:
            order = ["local", "cloud"] if decision.is_local else ["cloud", "local"]

        # 隐私 / 离线两条硬约束：即使用户点了 prefer="cloud" 也不许外发
        if not decision.allow_cloud_fallback:
            order = [name for name in order if name != "cloud"]

        chain = [f"route:{decision.target}(score={decision.score})"]
        if decision.rule != "score":
            chain.append(f"rule:{decision.rule}")
        if not decision.allow_cloud_fallback:
            chain.append("cloud:forbidden(privacy/offline)")
        errors: list[str] = []
        with self._lock:
            self._stats["calls"] += 1
            rules = self._stats["rules"]
            rules[decision.rule] = rules.get(decision.rule, 0) + 1

        for name in order:
            now = self._clock()
            if name == "local" and self._gate_local(chain):
                self._bump("blocked", name)
                continue
            if self._breakers[name].is_open(now):
                self._bump("skipped", name)
                chain.append(f"{name}:circuit_open")
                continue
            try:
                value = self._queue.run(self._invoke, name, prompt)
            except RouterTimeout as exc:
                self._bump("timeouts", name)
                self._bump("failures", name)
                self._breakers[name].record_failure(self._clock())
                chain.append(f"{name}:timeout")
                errors.append(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - 任何异常都算该目标失败
                self._bump("failures", name)
                self._breakers[name].record_failure(self._clock())
                chain.append(f"{name}:error:{type(exc).__name__}")
                errors.append(f"{name}: {exc}")
                continue
            else:
                self._breakers[name].record_success()
                self._bump("by_target", name)
                chain.append(f"{name}:ok")
                return CallResult(
                    target=name,
                    value=value,
                    latency_s=time.monotonic() - started,
                    fallback_chain=chain,
                )

        raise AllTargetsFailed("首选与备用都不可用：" + "；".join(errors + chain))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            snapshot = {
                "calls": self._stats["calls"],
                "by_target": dict(self._stats["by_target"]),
                "failures": dict(self._stats["failures"]),
                "timeouts": dict(self._stats["timeouts"]),
                "skipped": dict(self._stats["skipped"]),
                "blocked": dict(self._stats["blocked"]),
                "rules": dict(self._stats["rules"]),
            }
        now = self._clock()
        snapshot["circuits"] = {
            name: b.state(now) for name, b in self._breakers.items()
        }
        snapshot["queue"] = self._queue.stats()
        return snapshot
