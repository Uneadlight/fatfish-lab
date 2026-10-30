"""端到端演示：真本地模型 + 规则路由 + 故障降级 + 串行闸门。

云端通道用 stub（不打真 API、不花钱），只为演示"降级链"真的会走；
真实云端接入留给 P4 的编排器统一做。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guard.gpu import GpuSampler  # noqa: E402
from guard.local_llm import OllamaClient  # noqa: E402
from guard.policy import VramPolicy  # noqa: E402
from router.router import ModelRouter  # noqa: E402


def hr(title: str) -> None:
    print("\n" + "-" * 66)
    print(title)
    print("-" * 66)


def main() -> int:
    sampler = GpuSampler()
    policy = VramPolicy(total_mib=sampler.sample().total_mib)
    client = OllamaClient(policy=policy, sampler=sampler)

    def local(prompt: str) -> str:
        return client.generate(prompt, model="qwen2.5:3b").text.strip()

    def cloud_stub(prompt: str) -> str:
        time.sleep(0.2)
        return f"[云端 stub] {prompt[:24]}…"

    hr("1) 短问答 → 规则判 local，真跑 3b")
    r = ModelRouter(local_fn=local, cloud_fn=cloud_stub, timeout_local=60, timeout_cloud=10)
    res = r.call("用一句话说明什么是 B+ 树的扇出。")
    print(f"   路由: {res.fallback_chain}  耗时 {res.latency_s:.2f}s")
    print(f"   本地回答: {res.value[:70]}")

    hr("2) 需外部知识 → 规则判 cloud（stub 顶替，不花钱）")
    r = ModelRouter(
        local_fn=local, cloud_fn=cloud_stub, timeout_local=60, timeout_cloud=10,
        needs_external_knowledge=True,
    )
    res = r.call("今天 DeepSeek 官网公布的最新价格是多少？")
    print(f"   路由: {res.fallback_chain}  耗时 {res.latency_s:.2f}s")
    print(f"   回答: {res.value}")

    hr("3) 本地故障 → 自动降级云端（熔断链可见）")
    def broken(prompt: str) -> str:
        raise RuntimeError("模拟：本地 Ollama 挂了")

    r = ModelRouter(local_fn=broken, cloud_fn=cloud_stub, timeout_local=5, timeout_cloud=10)
    res = r.call("随便问一句")
    print(f"   路由: {res.fallback_chain}  耗时 {res.latency_s:.2f}s")
    print(f"   回答: {res.value}")
    print(f"   熔断器: {r.stats()['circuits']}")

    hr("4) 20 并发 → 串行闸门（本地同时只跑一个）")
    r = ModelRouter(local_fn=local, cloud_fn=cloud_stub, concurrency=1)
    lat = []
    lock = threading.Lock()

    def one(i: int) -> None:
        t0 = time.monotonic()
        r.call("用五个字回答：你好")
        with lock:
            lat.append(time.monotonic() - t0)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(20)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    wall = time.monotonic() - t0
    st = r.stats()
    print(f"   20 个请求墙钟 {wall:.1f}s，平均 {sum(lat)/len(lat):.2f}s/个")
    print(f"   queue={st['queue']}  by_target={st['by_target']}")
    print(f"   max_active={st['queue']['max_active']}（必须是 1）")

    hr("5) 温度闸门 → 过热时本地被拦、自动走云端")
    from guard.monitor import PressureGuard

    # 故意把温度线压到 20℃（真机常态 45℃），一采样就进冷却，等于"卡已经烧了"
    guard = PressureGuard(temp_limit_c=20, cooldown_s=60)
    r = ModelRouter(
        local_fn=local,
        cloud_fn=cloud_stub,
        guard=guard,
        sampler=sampler,
        timeout_local=60,
        timeout_cloud=10,
    )
    res = r.call("用五个字回答：你好")
    print(f"   路由: {res.fallback_chain}")
    print(f"   冷却中={guard.is_cooling()} 剩余 {guard.cooldown_remaining_s():.0f}s")
    print(f"   blocked={r.stats()['blocked']}（local 应为 1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
