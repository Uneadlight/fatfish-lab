"""全局串行队列：同一时刻只允许一个推理在跑。

为什么必须串行：3b 模型一起跑两个，第二个会和第一个抢显存/算力，直接顶破红线；
而且笔记本 GPU 上并发只会让两个请求都变慢。所以闸门放在这里，排队超时就降级到云端。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

__all__ = ["QueueTimeout", "SerialQueue"]


class QueueTimeout(TimeoutError):
    """排队超时：调用方应降级到云端。"""


class SerialQueue:
    def __init__(self, capacity: int = 1) -> None:
        if capacity < 1:
            raise ValueError("capacity 至少为 1")
        self.capacity = int(capacity)
        self._sem = threading.Semaphore(self.capacity)
        self._lock = threading.Lock()
        self._active = 0
        self._max_active = 0
        self._completed = 0
        self._timeouts = 0

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        # 注意：Semaphore.acquire(timeout=-1) 不是"无限等"，而是"已过期立刻返回 False"
        # （CPython 里 remaining <= 0 就 break）。所以"无限等"必须走不带 timeout 的分支。
        if timeout is None:
            acquired = self._sem.acquire()
        else:
            acquired = self._sem.acquire(timeout=timeout)
        if not acquired:
            with self._lock:
                self._timeouts += 1
            raise QueueTimeout(f"等待 {timeout}s 仍未拿到执行权")
        try:
            with self._lock:
                self._active += 1
                self._max_active = max(self._max_active, self._active)
            try:
                result = fn(*args, **kwargs)
            finally:
                with self._lock:
                    self._active -= 1
            with self._lock:
                self._completed += 1
            return result
        finally:
            self._sem.release()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "capacity": self.capacity,
                "completed": self._completed,
                "timeouts": self._timeouts,
                "active": self._active,
                "max_active": self._max_active,
            }
