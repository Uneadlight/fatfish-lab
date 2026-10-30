"""模型路由：规则分类 + 超时降级 + 熔断 + 串行。"""

from .router import AllTargetsFailed, CallResult, ModelRouter
from .rules import RouteDecision, classify

__all__ = [
    "AllTargetsFailed",
    "CallResult",
    "ModelRouter",
    "RouteDecision",
    "classify",
]
