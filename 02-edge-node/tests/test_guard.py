"""Task 1 护栏验收：显存红线 / 串行队列 / 利用率与温度守卫。

全部用假数据，不依赖真 GPU（离线可跑）；真实采样见 bench/bench_gpu.py。
"""

from __future__ import annotations

import threading
import time

import pytest
from guard.gpu import GpuError, GpuSample, GpuSampler
from guard.monitor import PressureGuard
from guard.policy import MODEL_VRAM_MIB, VramPolicy
from guard.queue import QueueTimeout, SerialQueue


# --------------------------------------------------------------------------
# 采样：解析 nvidia-smi 的 csv 输出
# --------------------------------------------------------------------------
def test_parse_nvidia_smi_typical():
    s = GpuSampler.parse("804, 8188, 67, 42")
    assert (s.used_mib, s.total_mib, s.util_pct, s.temp_c) == (804, 8188, 67, 42)


def test_parse_takes_first_line_for_multi_gpu():
    s = GpuSampler.parse("804, 8188, 67, 42\n1000, 24463, 10, 30")
    assert s.total_mib == 8188


def test_parse_tolerates_extra_spaces_and_trailing_newline():
    s = GpuSampler.parse("  804 , 8188 , 67 , 42 \r\n")
    assert s.temp_c == 42


@pytest.mark.parametrize("bad", ["", "   ", "abc, 8188, 67, 42", "804, 8188", "804, 8188, x, 42"])
def test_parse_rejects_garbage(bad):
    with pytest.raises(GpuError):
        GpuSampler.parse(bad)


def test_sampler_calls_runner_once():
    calls = []

    def runner():
        calls.append(1)
        return "1000, 8188, 5, 40"

    s = GpuSampler(runner=runner).sample()
    assert calls == [1] and s.used_mib == 1000


def test_sampler_wraps_runner_oserror():
    def runner():
        raise OSError("nvidia-smi 不在 PATH")

    with pytest.raises(GpuError, match="nvidia-smi"):
        GpuSampler(runner=runner).sample()


def test_used_ratio():
    assert GpuSample(1000, 8000, 0, 40).used_ratio == pytest.approx(0.125)


# --------------------------------------------------------------------------
# 显存红线：70% 硬上限 = 5732 MiB（8188 × 0.7）
# --------------------------------------------------------------------------
def test_red_line_is_70_percent_of_total():
    p = VramPolicy(total_mib=8188)
    assert p.limit_mib == 5732
    assert p.headroom_mib(used_mib=804) == 4928


def test_three_b_allowed_under_line():
    d = VramPolicy(total_mib=8188).check("qwen2.5:3b", used_mib=804)
    assert d.allowed is True
    assert d.projected_total_mib == 804 + MODEL_VRAM_MIB["qwen2.5:3b"]


def test_seven_b_refused_over_line():
    d = VramPolicy(total_mib=8188).check("qwen2.5:7b", used_mib=804)
    assert d.allowed is False
    assert "超出" in d.reason


def test_unknown_model_fails_closed():
    d = VramPolicy(total_mib=8188).check("llama3:70b", used_mib=804)
    assert d.allowed is False
    assert "未知模型" in d.reason


def test_tight_ratio_refuses_three_b():
    p = VramPolicy(total_mib=8188, ratio=0.10)
    assert p.limit_mib == 819
    assert p.check("qwen2.5:3b", used_mib=804).allowed is False


def test_vram_policy_does_not_double_count_already_loaded_model():
    """模型已经在显存里（used 已包含它）时，不能再加一遍估算值 —— 否则暖机后必被误拒。"""
    p = VramPolicy(total_mib=8188)
    # 真机实测：3b 驻留时 used=3283，其中 2500 就是这个模型
    d = p.check("qwen2.5:3b", used_mib=3283, already_loaded_mib=2500)
    assert d.allowed is True
    assert d.projected_total_mib == 3283
    assert d.reason.endswith(f"≤ 红线 {p.limit_mib} MiB")


def test_vram_policy_still_refuses_when_cold_load_breaks_line():
    """真冷启动（没驻留）时该拒还是拒。"""
    p = VramPolicy(total_mib=8188)
    d = p.check("qwen2.5:3b", used_mib=5000, already_loaded_mib=0)
    assert d.allowed is False
    assert d.projected_total_mib == 7500


# --------------------------------------------------------------------------
# 压力与温度守卫
# --------------------------------------------------------------------------
class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _sample(util: int = 10, temp: int = 50, used: int = 1000) -> GpuSample:
    return GpuSample(used_mib=used, total_mib=8188, util_pct=util, temp_c=temp)


def test_util_pressure_needs_three_consecutive_samples():
    g = PressureGuard(clock=FakeClock())
    assert g.observe(_sample(util=90)) == []
    assert g.observe(_sample(util=90)) == []
    assert "util_pressure" in g.observe(_sample(util=90))


def test_util_pressure_resets_on_calm_sample():
    g = PressureGuard(clock=FakeClock())
    g.observe(_sample(util=90))
    g.observe(_sample(util=90))
    assert g.observe(_sample(util=20)) == []  # 断了一次，计数归零
    g.observe(_sample(util=90))
    g.observe(_sample(util=90))
    assert "util_pressure" in g.observe(_sample(util=90))


def test_util_pressure_does_not_repeat_while_still_hot():
    g = PressureGuard(clock=FakeClock())
    for _ in range(3):
        g.observe(_sample(util=95))
    assert g.observe(_sample(util=96)) == []  # 已经报过，不再刷屏


def test_thermal_cooldown_lasts_60_seconds():
    clock = FakeClock()
    g = PressureGuard(clock=clock)
    events = g.observe(_sample(temp=88))
    assert "thermal_cooldown" in events
    assert g.is_cooling() is True
    clock.advance(59)
    assert g.is_cooling() is True
    clock.advance(2)
    assert g.is_cooling() is False


def test_cooling_not_rearmed_by_each_hot_sample():
    clock = FakeClock()
    g = PressureGuard(clock=clock)
    g.observe(_sample(temp=88))
    clock.advance(30)
    assert g.observe(_sample(temp=89)) == []  # 冷却中不重复报警、也不延长
    clock.advance(31)
    assert g.is_cooling() is False


# --------------------------------------------------------------------------
# 全局串行队列：同时只跑一个推理
# --------------------------------------------------------------------------
def test_twenty_concurrent_run_serially():
    q = SerialQueue()
    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def job(i: int) -> int:
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.01)
        with lock:
            state["active"] -= 1
        return i

    out: list[int] = []
    threads = [threading.Thread(target=lambda i=i: out.append(q.run(job, i))) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert sorted(out) == list(range(20))
    assert state["max"] == 1


def test_waiting_too_long_raises_queue_timeout():
    q = SerialQueue()
    started = threading.Event()
    release = threading.Event()

    def hog() -> None:
        started.set()
        release.wait(5)

    t = threading.Thread(target=lambda: q.run(hog))
    t.start()
    assert started.wait(2)
    try:
        with pytest.raises(QueueTimeout):
            q.run(lambda: 1, timeout=0.05)
    finally:
        release.set()
        t.join(5)


def test_exception_propagates_and_lock_is_released():
    q = SerialQueue()

    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        q.run(boom)
    assert q.run(lambda: 42) == 42


def test_stats_counts_completed_and_timeouts():
    q = SerialQueue()
    q.run(lambda: 1)
    st = q.stats()
    assert st["completed"] == 1
    assert st["max_active"] == 1
