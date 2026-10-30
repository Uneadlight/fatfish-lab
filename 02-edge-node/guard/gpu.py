"""GPU 采样：不装 pynvml，直接解析 nvidia-smi 的 csv 输出。

为什么不用 pynvml：多一个二进制依赖、要 CUDA 库；而 nvidia-smi 一定跟着
驱动装好了，`--query-gpu=... --format=csv,noheader,nounits` 的输出稳定且好解析。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["GpuError", "GpuSample", "GpuSampler", "DEFAULT_QUERY"]

DEFAULT_QUERY = "memory.used,memory.total,utilization.gpu,temperature.gpu"


class GpuError(RuntimeError):
    """采样失败（没装驱动、被拦、输出无法解析）。"""


@dataclass(frozen=True)
class GpuSample:
    used_mib: int
    total_mib: int
    util_pct: int
    temp_c: int

    @property
    def used_ratio(self) -> float:
        return self.used_mib / self.total_mib if self.total_mib else 0.0

    def as_row(self) -> str:
        return (
            f"{self.used_mib}/{self.total_mib} MiB "
            f"util={self.util_pct}% temp={self.temp_c}C"
        )


class GpuSampler:
    """一次采样 = 跑一次 nvidia-smi（约 50–200ms）。"""

    def __init__(
        self,
        runner: Callable[[], str] | None = None,
        nvidia_smi: str = "nvidia-smi",
        timeout: float = 5.0,
    ) -> None:
        self.nvidia_smi = nvidia_smi
        self.timeout = timeout
        self._runner = runner or self._default_runner

    def _default_runner(self) -> str:
        proc = subprocess.run(
            [
                self.nvidia_smi,
                f"--query-gpu={DEFAULT_QUERY}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise GpuError(
                f"nvidia-smi 退出码 {proc.returncode}：{(proc.stderr or '').strip()[:200]}"
            )
        return proc.stdout

    def sample(self) -> GpuSample:
        try:
            raw = self._runner()
        except GpuError:
            raise
        except OSError as exc:
            raise GpuError(f"无法执行 nvidia-smi：{exc}") from exc
        except subprocess.SubprocessError as exc:
            raise GpuError(f"nvidia-smi 调用失败：{exc}") from exc
        return self.parse(raw)

    @staticmethod
    def parse(text: str) -> GpuSample:
        if not text or not text.strip():
            raise GpuError("nvidia-smi 输出为空")
        first = text.strip().splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        if len(parts) < 4:
            raise GpuError(f"nvidia-smi 输出字段不足（要 4 个）：{first!r}")
        values = []
        for raw in parts[:4]:
            try:
                values.append(int(raw))
            except ValueError as exc:
                raise GpuError(f"nvidia-smi 输出非数字：{first!r}") from exc
        used, total, util, temp = values
        if total <= 0:
            raise GpuError(f"nvidia-smi 报告的总显存非法：{total}")
        return GpuSample(
            used_mib=used, total_mib=total, util_pct=util, temp_c=temp
        )
