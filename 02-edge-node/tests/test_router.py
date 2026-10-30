"""Task 1 路由验收：规则分类 / 超时降级 / 熔断 / 并发串行。"""

from __future__ import annotations

import threading
import time

import pytest
from router.router import AllTargetsFailed, CallResult, ModelRouter
from router.rules import classify


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --------------------------------------------------------------------------
# 规则表分类（不许"再调一次模型来判断要不要用模型"）
# --------------------------------------------------------------------------
def test_short_prompt_routes_local():
    d = classify("1+1 等于几")
    assert d.target == "local"
    assert d.score == 0


def test_long_prompt_with_code_routes_cloud():
    d = classify("x" * 2500 + "\n```python\nprint(1)\n```")
    assert d.score >= 2
    assert d.target == "cloud"


def test_external_knowledge_alone_routes_cloud():
    d = classify("今天官网的涨价公告怎么说的", needs_external_knowledge=True)
    assert d.target == "cloud"
    assert "需外部知识" in "".join(d.reasons)


def test_high_concurrency_adds_score():
    assert classify("你好", concurrency=8).score >= 1


def test_code_block_alone_stays_local():
    d = classify("```python\nprint('hi')\n```")
    assert d.score == 1
    assert d.target == "local"


# --------------------------------------------------------------------------
# 超时降级 / 熔断 / 串行
# --------------------------------------------------------------------------
def test_local_timeout_falls_back_to_cloud():
    def local(prompt: str) -> str:
        time.sleep(0.5)
        return "slow"

    def cloud(prompt: str) -> str:
        return "fast:" + prompt

    r = ModelRouter(local_fn=local, cloud_fn=cloud, timeout_local=0.05)
    res = r.call("hi")
    assert res.target == "cloud"
    assert res.value == "fast:hi"
    assert any("timeout" in step for step in res.fallback_chain)


def test_local_exception_falls_back_to_cloud():
    def local(prompt: str) -> str:
        raise RuntimeError("GPU 挂了")

    r = ModelRouter(local_fn=local, cloud_fn=lambda p: "cloud-ok", timeout_local=5)
    res = r.call("hi")
    assert res.target == "cloud"
    assert res.value == "cloud-ok"


def test_three_failures_open_circuit_then_half_open():
    clock = FakeClock()
    fails = {"n": 0}

    def local(prompt: str) -> str:
        fails["n"] += 1
        raise RuntimeError("boom")

    r = ModelRouter(
        local_fn=local,
        cloud_fn=lambda p: "cloud-ok",
        clock=clock,
        failure_threshold=3,
        open_seconds=60.0,
        timeout_local=5.0,
    )
    for _ in range(3):
        r.call("hi")
    assert fails["n"] == 3

    res = r.call("hi")  # 第 4 次：熔断中，直接走云端
    assert fails["n"] == 3
    assert any("circuit_open" in step for step in res.fallback_chain)

    clock.advance(61)  # 过了冷却窗口 → 半开，放一次探针
    r.call("hi")
    assert fails["n"] == 4


def test_both_targets_down_raises():
    def boom(prompt: str) -> str:
        raise RuntimeError("all down")

    r = ModelRouter(local_fn=boom, cloud_fn=boom, timeout_local=5, timeout_cloud=5)
    with pytest.raises(RuntimeError):
        r.call("hi")


def test_twenty_concurrent_calls_run_serially():
    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def local(prompt: str) -> str:
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.01)
        with lock:
            state["active"] -= 1
        return "local:" + prompt

    r = ModelRouter(local_fn=local, cloud_fn=lambda p: "cloud", concurrency=1)
    out: list[CallResult] = []
    threads = [threading.Thread(target=lambda: out.append(r.call("p"))) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(out) == 20
    assert state["max"] == 1
    assert all(res.target == "local" for res in out)


def test_stats_records_targets():
    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=lambda p: "C")
    r.call("hi")
    st = r.stats()
    assert st["calls"] == 1
    assert st["by_target"]["local"] == 1


def test_prefer_overrides_rules():
    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=lambda p: "C")
    assert r.call("hi", prefer="cloud").target == "cloud"
    assert r.call("x" * 3000, prefer="local").target == "local"


def test_result_carries_latency_and_chain():
    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=lambda p: "C")
    res = r.call("hi")
    assert isinstance(res.latency_s, float)
    assert res.latency_s >= 0.0
    assert res.fallback_chain


# --------------------------------------------------------------------------
# 温度闸门：PressureGuard.is_cooling() 期间不许跑本地（86℃ 冷却真正生效）
# --------------------------------------------------------------------------
class FakeGuard:
    """假守卫，只回答"在不在冷却"，并记录 observe 调用。"""

    def __init__(self, cooling: bool = False, remaining: float = 30.0) -> None:
        self.cooling = cooling
        self.remaining = remaining
        self.observed: list[object] = []

    def is_cooling(self) -> bool:
        return self.cooling

    def cooldown_remaining_s(self) -> float:
        return self.remaining if self.cooling else 0.0

    def observe(self, sample: object) -> list[str]:
        self.observed.append(sample)
        return ["thermal_cooldown"] if getattr(sample, "temp_c", 0) > 86 else []


def test_router_skips_local_while_cooling():
    guard = FakeGuard(cooling=True, remaining=42.0)
    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=lambda p: "C", guard=guard)
    res = r.call("hi")
    assert res.target == "cloud"
    assert any("thermal_blocked" in s for s in res.fallback_chain)
    assert r.stats()["blocked"]["local"] == 1


def test_router_uses_local_when_not_cooling():
    guard = FakeGuard(cooling=False)
    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=lambda p: "C", guard=guard)
    res = r.call("hi")
    assert res.target == "local"
    assert not any("thermal" in s for s in res.fallback_chain)
    assert r.stats()["blocked"]["local"] == 0


def test_router_hard_fails_when_local_blocked_and_cloud_down():
    guard = FakeGuard(cooling=True)

    def cloud(prompt: str) -> str:
        raise RuntimeError("云端挂了")

    r = ModelRouter(local_fn=lambda p: "L", cloud_fn=cloud, guard=guard)
    with pytest.raises(AllTargetsFailed) as ei:
        r.call("hi", prefer="local")
    assert "thermal_blocked" in str(ei.value)


def test_router_samples_gpu_before_local_and_enters_cooldown():
    """真守卫 + 采样器：采样读到 91℃ → 进入冷却 → 这次走云端；冷却到期后恢复本地。"""
    from guard.gpu import GpuSample
    from guard.monitor import PressureGuard

    clock = FakeClock()
    guard = PressureGuard(temp_limit_c=86, cooldown_s=60.0, clock=clock)

    class Sampler:
        temp = 91

        def sample(self) -> GpuSample:
            return GpuSample(
                used_mib=3000, total_mib=8188, util_pct=99, temp_c=self.temp
            )

    sampler = Sampler()
    r = ModelRouter(
        local_fn=lambda p: "L",
        cloud_fn=lambda p: "C",
        guard=guard,
        sampler=sampler,
        clock=clock,
    )
    res = r.call("hi")
    assert guard.is_cooling() is True
    assert res.target == "cloud"
    assert any("thermal" in s for s in res.fallback_chain)

    # 冷却期过了 + 卡也真凉下来（不然采样还是 91℃，会立刻再触发一轮冷却，这是对的）
    clock.advance(61.0)
    sampler.temp = 62
    assert guard.is_cooling() is False
    assert r.call("hi").target == "local"


def test_router_survives_sampler_error():
    """采样失败不能把请求打死：放行本地（fail-open），但链上留痕。"""
    guard = FakeGuard(cooling=False)

    class BadSampler:
        def sample(self) -> object:
            raise RuntimeError("nvidia-smi 挂了")

    r = ModelRouter(
        local_fn=lambda p: "L", cloud_fn=lambda p: "C", guard=guard, sampler=BadSampler()
    )
    res = r.call("hi")
    assert res.target == "local"
    assert any("guard:sample_error" in s for s in res.fallback_chain)

# --------------------------------------------------------------------------
# 边缘节点四大定位（2026-10-29 用户转达，硬性路由法则）
# --------------------------------------------------------------------------
def test_privacy_marker_keeps_text_local_and_forbids_cloud():
    d = classify("帮我整理这段日记，里面有我的身份证号和密码")
    assert d.rule == "privacy"
    assert d.target == "local"
    assert d.allow_cloud_fallback is False

    called: list[str] = []

    def local(prompt: str) -> str:
        called.append("local")
        return "local"

    def cloud(prompt: str) -> str:  # noqa: ARG001 - 只关心有没有被调用
        called.append("cloud")
        return "cloud"

    r = ModelRouter(local, cloud, timeout_local=1, timeout_cloud=1)
    res = r.call("我的密码是 hunter2，帮我记一下", prefer="cloud")
    assert res.target == "local"
    assert called == ["local"]
    assert any("cloud:forbidden" in c for c in res.fallback_chain)
    assert r.stats()["rules"]["privacy"] == 1


def test_offline_mode_never_touches_cloud():
    called: list[str] = []

    def local(prompt: str) -> str:
        called.append("local")
        return "local"

    def cloud(prompt: str) -> str:  # noqa: ARG001
        called.append("cloud")
        return "cloud"

    r = ModelRouter(local, cloud, offline=True, timeout_local=1, timeout_cloud=1)
    res = r.call("随便问点啥", prefer="cloud")
    assert res.target == "local"
    assert "cloud" not in called


def test_privacy_offline_still_raises_when_local_dead():
    def local(prompt: str) -> str:  # noqa: ARG001
        raise RuntimeError("本地模型没起")

    def cloud(prompt: str) -> str:  # noqa: ARG001
        raise AssertionError("隐私任务绝不允许外发到云端")

    r = ModelRouter(local, cloud, timeout_local=1, timeout_cloud=1)
    with pytest.raises(AllTargetsFailed) as ei:
        r.call("我的身份证号是 110101199001011234")
    assert "cloud" not in str(ei.value) or "forbidden" in str(ei.value)


def test_mechanical_task_prefers_local():
    d = classify("把这段文本清洗一下，提取所有邮箱，转成 json")
    assert d.rule == "mechanical"
    assert d.target == "local"


def test_architecture_task_goes_cloud():
    d = classify("帮我做最终审查和架构设计，决定这个模块怎么合并")
    assert d.rule == "architecture"
    assert d.target == "cloud"


def test_rule_counter_records_score_fallback():
    def local(prompt: str) -> str:  # noqa: ARG001
        return "local"

    def cloud(prompt: str) -> str:  # noqa: ARG001
        return "cloud"

    r = ModelRouter(local, cloud, timeout_local=1, timeout_cloud=1)
    r.call("你好")
    assert r.stats()["rules"]["score"] == 1
