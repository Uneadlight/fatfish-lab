"""路由规则表：用显式规则判断"这活该谁干"，绝不调模型来判断要不要调模型。

三层判定（顺序即优先级）：

1. **硬约束**（不看分数）：
   - `offline=True` → 本地闭环，不许尝试云端（断网/灾备）
   - 命中隐私标记 → 本地先行，不许把原始私密文本送云端（脱敏网关）
   - 命中架构/裁决标记 → 云端收口（3b 不负责最终架构与合并）
2. **脏活优先本地**：命中机械任务标记 → 优先本地（零边际成本层）
3. **兜底打分**，分数 ≥ 2 走云端：
   - 长文本（>2000 字）+1：3b 的上下文和注意力都不够，容易丢中间内容
   - 含代码块 +1：但不单独触发（简单代码 3b 能写）
   - 需外部知识 +2：本地模型没有联网，知识截止就瞎编
   - 高并发（≥5）+1：本地是串行队列，堆排队不如甩云端

`allow_cloud_fallback=False` 表示"首选失败也绝不换云端"，只用于离线与隐私两条硬约束。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "LONG_PROMPT_CHARS",
    "CLOUD_THRESHOLD",
    "PRIVACY_MARKERS",
    "MECHANICAL_MARKERS",
    "ARCHITECTURE_MARKERS",
    "RouteDecision",
    "classify",
]

LONG_PROMPT_CHARS = 2000
CODE_FENCE = "```"
SCORE_LENGTH = 1
SCORE_CODE = 1
SCORE_EXTERNAL = 2
SCORE_CONCURRENCY = 1
CONCURRENCY_THRESHOLD = 5
CLOUD_THRESHOLD = 2

#: 出现这些词就按"隐私优先"处理：**原始文本不出本机**。
PRIVACY_MARKERS: tuple[str, ...] = (
    "密码",
    "口令",
    "身份证",
    "银行卡",
    "信用卡",
    "私钥",
    "密钥",
    "api key",
    "apikey",
    "access token",
    "日记",
    "私密",
    "病历",
    "家庭住址",
    "手机号",
    "脱敏",
)

#: 低智、高频、机械 —— 零边际成本层的主体。
MECHANICAL_MARKERS: tuple[str, ...] = (
    "格式化",
    "清洗",
    "正则",
    "提取",
    "抽取",
    "分类",
    "打标",
    "标签",
    "摘要",
    "概括",
    "转成 json",
    "转成json",
    "转json",
    "转 yaml",
    "转yaml",
    "转yaml",
    "结构化",
    "去重",
    "洗数据",
    "snake_case",
    "驼峰",
)

#: 需要判断力与一致性的活 —— 小模型写得出字，但写不对结构。
ARCHITECTURE_MARKERS: tuple[str, ...] = (
    "架构",
    "设计方案",
    "重构方案",
    "最终审查",
    "代码评审",
    "技术选型",
    "合并冲突",
    "发布方案",
    "对外接口设计",
)


def _hit(text: str, markers: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [m for m in markers if m.lower() in low]


@dataclass(frozen=True)
class RouteDecision:
    target: str
    score: int
    reasons: tuple[str, ...]
    rule: str = "score"
    matched: tuple[str, ...] = field(default_factory=tuple)
    allow_cloud_fallback: bool = True

    @property
    def is_local(self) -> bool:
        return self.target == "local"


def classify(
    prompt: str,
    *,
    needs_external_knowledge: bool = False,
    concurrency: int = 1,
    offline: bool = False,
    sensitive: bool | None = None,
) -> RouteDecision:
    text = prompt or ""

    # -- 1. 硬约束 --------------------------------------------------------- #
    if offline:
        return RouteDecision(
            target="local",
            score=0,
            reasons=("离线/灾备模式：只许本地闭环，不尝试外网",),
            rule="offline",
            allow_cloud_fallback=False,
        )

    privacy_hits = _hit(text, PRIVACY_MARKERS)
    if sensitive is True or (sensitive is None and privacy_hits):
        return RouteDecision(
            target="local",
            score=0,
            reasons=(
                "隐私优先：原始文本不出本机（先本地脱敏/处理，只把摘要外发）",
                f"命中隐私标记：{', '.join(privacy_hits) or '调用方声明 sensitive'}",
            ),
            rule="privacy",
            matched=tuple(privacy_hits),
            allow_cloud_fallback=False,
        )

    arch_hits = _hit(text, ARCHITECTURE_MARKERS)
    if arch_hits:
        return RouteDecision(
            target="cloud",
            score=SCORE_EXTERNAL,
            reasons=(f"架构/裁决类任务交云端收口（命中：{', '.join(arch_hits)}）",),
            rule="architecture",
            matched=tuple(arch_hits),
        )

    # -- 2. 脏活优先本地 --------------------------------------------------- #
    mech_hits = _hit(text, MECHANICAL_MARKERS)
    if mech_hits and not needs_external_knowledge:
        reasons = [f"机械任务优先本地（命中：{', '.join(mech_hits)}）"]
        return RouteDecision(
            target="local",
            score=0,
            reasons=tuple(reasons),
            rule="mechanical",
            matched=tuple(mech_hits),
        )

    # -- 3. 兜底打分 ------------------------------------------------------- #
    score = 0
    reasons = []
    if len(text) > LONG_PROMPT_CHARS:
        score += SCORE_LENGTH
        reasons.append(f"长文本 {len(text)} 字 > {LONG_PROMPT_CHARS}")
    if CODE_FENCE in text:
        score += SCORE_CODE
        reasons.append("含代码块")
    if needs_external_knowledge:
        score += SCORE_EXTERNAL
        reasons.append("需外部知识")
    if concurrency >= CONCURRENCY_THRESHOLD:
        score += SCORE_CONCURRENCY
        reasons.append(f"高并发 {concurrency}")

    target = "cloud" if score >= CLOUD_THRESHOLD else "local"
    if not reasons:
        reasons.append("短问答、无代码、无外部依赖、非高并发")
    return RouteDecision(target=target, score=score, reasons=tuple(reasons))
