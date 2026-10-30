"""显存红线：70% 硬上限，超了就不许起模型。

前提（写在代码里就是为了以后别忘）：
- 显存**能**硬拦（预检 + num_ctx + 单模型 + 串行），算力利用率**拦不住**，
  所以红线只管显存，util 只做告警。
- 模型显存按"运行态"估（权重 + KV + 上下文），不是只看文件大小。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "RED_LINE_RATIO",
    "MODEL_VRAM_MIB",
    "VramDecision",
    "VramPolicy",
]

RED_LINE_RATIO = 0.70
DEFAULT_TOTAL_MIB = 8188

# 运行态估算（MiB）：权重 + KV(2K ctx) + 运行时缓冲
MODEL_VRAM_MIB: dict[str, int] = {
    "qwen2.5:3b": 2500,
    "qwen2.5:7b": 5500,
    "qwen2.5vl:7b": 6700,
}


@dataclass(frozen=True)
class VramDecision:
    allowed: bool
    limit_mib: int
    projected_total_mib: int
    reason: str

    @property
    def headroom_mib(self) -> int:
        return self.limit_mib - self.projected_total_mib


class VramPolicy:
    def __init__(
        self,
        total_mib: int = DEFAULT_TOTAL_MIB,
        ratio: float = RED_LINE_RATIO,
        model_table: dict[str, int] | None = None,
    ) -> None:
        if total_mib <= 0:
            raise ValueError("total_mib 必须为正")
        if not 0 < ratio <= 1:
            raise ValueError("ratio 必须在 (0, 1] 之间")
        self.total_mib = int(total_mib)
        self.ratio = float(ratio)
        self._models = dict(MODEL_VRAM_MIB if model_table is None else model_table)

    @property
    def limit_mib(self) -> int:
        return int(round(self.total_mib * self.ratio))

    def headroom_mib(self, used_mib: int) -> int:
        return self.limit_mib - int(used_mib)

    def check(
        self, model: str, used_mib: int, already_loaded_mib: int = 0
    ) -> VramDecision:
        """预检：这次加载会不会把总占用顶过红线。

        `already_loaded_mib` 是这个模型**已经在显存里**的部分（/api/ps 的 size_vram）。
        不传它就是错的口径：暖机状态下 used 里已经包含该模型，再加一遍估算值会
        把一次"零增长的命中"判成超线（2026-10-29 实测踩到，3283+2500=5783 > 5732）。
        """
        limit = self.limit_mib
        estimate = self._models.get(model)
        if estimate is None:
            return VramDecision(
                allowed=False,
                limit_mib=limit,
                projected_total_mib=int(used_mib),
                reason=f"未知模型 {model!r}：没有显存估量，拒绝（失败即关闭）",
            )
        growth = max(0, int(estimate) - max(0, int(already_loaded_mib)))
        projected = int(used_mib) + growth
        if projected > limit:
            return VramDecision(
                allowed=False,
                limit_mib=limit,
                projected_total_mib=projected,
                reason=(
                    f"预估总占用 {projected} MiB 超出红线 {limit} MiB"
                    f"（模型 {model} 估 {estimate} MiB，"
                    f"已驻留 {already_loaded_mib} MiB，系统已用 {used_mib} MiB）"
                ),
            )
        return VramDecision(
            allowed=True,
            limit_mib=limit,
            projected_total_mib=projected,
            reason=f"预估总占用 {projected} MiB ≤ 红线 {limit} MiB",
        )
