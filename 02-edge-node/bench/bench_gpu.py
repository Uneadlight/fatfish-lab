"""真机验收：采样 → 预检 → 真推理 → 峰值显存 → 卸载回位。

跑法（在 task1_local 目录）：
    ..\\.venv\\Scripts\\python.exe -m bench.bench_gpu
    ..\\.venv\\Scripts\\python.exe -m bench.bench_gpu qwen2.5:3b
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guard.gpu import GpuSampler  # noqa: E402
from guard.local_llm import LocalLLMError, ModelNotPulled, OllamaClient, VramRefused  # noqa: E402
from guard.monitor import PressureGuard  # noqa: E402
from guard.policy import MODEL_VRAM_MIB, VramPolicy  # noqa: E402

PROMPT = "用三句话解释 B+ 树为什么比红黑树更适合存磁盘索引。中文回答。"


def _hr(title: str) -> None:
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


def main(argv: list[str]) -> int:
    model = argv[1] if len(argv) > 1 else "qwen2.5:3b"
    sampler = GpuSampler()
    report: dict[str, object] = {"model": model, "steps": {}}

    _hr("1) 静态基线")
    base = sampler.sample()
    print(f"   {base.as_row()}  (used_ratio={base.used_ratio:.1%})")
    policy = VramPolicy(total_mib=base.total_mib)
    print(f"   红线 {policy.ratio:.0%} → 上限 {policy.limit_mib} MiB，"
          f"当前余量 {policy.headroom_mib(base.used_mib)} MiB")
    report["steps"]["baseline"] = {
        "used_mib": base.used_mib,
        "total_mib": base.total_mib,
        "util_pct": base.util_pct,
        "temp_c": base.temp_c,
        "limit_mib": policy.limit_mib,
    }

    _hr("2) 预检表（这份表才是能不能跑的唯一依据）")
    precheck = {}
    for name, est in MODEL_VRAM_MIB.items():
        d = policy.check(name, base.used_mib)
        mark = "OK " if d.allowed else "拒绝"
        print(f"   [{mark}] {name:<14} 估 {est:>5} MiB → 预计总占用 "
              f"{d.projected_total_mib:>5} MiB  ({d.projected_total_mib / base.total_mib:.0%})")
        precheck[name] = d.allowed
    report["steps"]["precheck"] = precheck

    _hr("3) 实时采样（10 × 200ms）+ 压力守卫")
    guard = PressureGuard()
    samples = []
    for _ in range(10):
        s = sampler.sample()
        samples.append(s)
        events = guard.observe(s)
        print(f"   {s.as_row()}" + (f"  ← {events}" if events else ""))
        time.sleep(0.2)
    utils = [s.util_pct for s in samples]
    temps = [s.temp_c for s in samples]
    print(f"   util min/max = {min(utils)}/{max(utils)}%   temp min/max = {min(temps)}/{max(temps)}C")
    report["steps"]["sampling"] = {
        "util_min": min(utils),
        "util_max": max(utils),
        "temp_min": min(temps),
        "temp_max": max(temps),
    }

    _hr(f"4) 真推理：{model}")
    client = OllamaClient(policy=policy, sampler=sampler)
    try:
        print(f"   Ollama {client.version()}，本地模型：{client.models()}")
    except LocalLLMError as exc:
        print(f"   ✗ {exc}")
        report["steps"]["inference"] = {"error": str(exc)}
        Path("reports").mkdir(exist_ok=True)
        Path("reports/gpu_bench.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    peak = {"used": 0, "util": 0, "temp": 0}
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            try:
                s = sampler.sample()
                peak["used"] = max(peak["used"], s.used_mib)
                peak["util"] = max(peak["util"], s.util_pct)
                peak["temp"] = max(peak["temp"], s.temp_c)
            except Exception:
                pass
            time.sleep(0.1)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        res = client.generate(PROMPT, model=model)
        print(f"   ✓ {res.as_row()}")
        print(f"   回答前 60 字：{res.text.strip()[:60]!r}")
        inference = {
            "ok": True,
            "eval_count": res.eval_count,
            "prompt_eval_count": res.prompt_eval_count,
            "tokens_per_sec": round(res.tokens_per_sec, 2),
            "wall_s": round(res.wall_s, 3),
        }
    except (VramRefused, ModelNotPulled, LocalLLMError) as exc:
        print(f"   ✗ {exc}")
        inference = {"ok": False, "error": str(exc)}
    finally:
        stop.set()
        watcher.join(2)

    print(f"   推理期间峰值：显存 {peak['used']} MiB "
          f"({peak['used'] / base.total_mib:.0%})  util {peak['util']}%  {peak['temp']}C")
    limit = policy.limit_mib
    verdict = "PASS" if peak["used"] <= limit else "FAIL"
    print(f"   红线 {limit} MiB → {verdict}")
    inference.update(
        {
            "peak_used_mib": peak["used"],
            "peak_used_ratio": round(peak["used"] / base.total_mib, 4),
            "peak_util_pct": peak["util"],
            "peak_temp_c": peak["temp"],
            "limit_mib": limit,
            "verdict": verdict,
        }
    )
    report["steps"]["inference"] = inference

    _hr("5) 卸载模型，确认显存回位")
    try:
        client.unload(model)
        time.sleep(3.0)
        after = sampler.sample()
        print(f"   {after.as_row()}  (退回 {after.used_mib - base.used_mib:+d} MiB vs 基线)")
        report["steps"]["after_unload"] = {
            "used_mib": after.used_mib,
            "util_pct": after.util_pct,
            "temp_c": after.temp_c,
        }
    except LocalLLMError as exc:
        print(f"   卸载失败（不影响结论）：{exc}")

    out = ROOT / "reports" / "gpu_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    return 0 if report["steps"].get("inference", {}).get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
