"""内存版 B+ 树 10 万条压测：插入 / 命中查 / 未命中查 / 范围扫描 / 删除。

指标：墙钟耗时、单次耗时、吞吐（ops/s）、树高、内存占用（tracemalloc 峰值）、每键字节数。
对照组：`dict`（哈希表，O(1) 查但不保序、不支持范围扫描）与 `list + bisect`（保序但插入 O(n)）。

用法：
    ..\\.venv\\Scripts\\python.exe bench\\bench_memory.py
"""

from __future__ import annotations

import bisect
import json
import os
import random
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bplus.memory import BPlusTree  # noqa: E402

N = 100_000
N_HIT = 20_000
N_MISS = 20_000
N_SCANS = 100
SCAN_LEN = 1_000
ORDER = 64


def timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def main() -> int:
    rng = random.Random(20261029)
    keys = list(range(N))
    rng.shuffle(keys)

    # ---------- 构建 ----------
    tracemalloc.start()
    tree = BPlusTree(order=ORDER)
    t_insert = timed(lambda: [tree.insert(k, k * 2) for k in keys])
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(tree) == N
    height_before = tree.height  # 必须在删除前量，删空后只剩一层根叶子

    d = {}
    t_dict_build = timed(lambda: [d.__setitem__(k, k * 2) for k in keys])
    sorted_list = sorted(keys)

    # ---------- 点查（命中） ----------
    hit_probes = rng.sample(keys, N_HIT)

    def hit_tree() -> None:
        for k in hit_probes:
            tree.search(k)

    def hit_dict() -> None:
        for k in hit_probes:
            d[k]

    t_hit_tree = timed(hit_tree)
    t_hit_dict = timed(hit_dict)

    # ---------- 点查（未命中） ----------
    miss_probes = list(range(N, N + N_MISS))
    t_miss_tree = timed(lambda: [tree.get(k) for k in miss_probes])

    # ---------- 范围扫描 ----------
    starts = [rng.randrange(0, N - SCAN_LEN) for _ in range(N_SCANS)]
    t_scan = timed(lambda: [tree.range_scan(s, s + SCAN_LEN - 1) for s in starts])
    t_scan_list = timed(
        lambda: [
            sorted_list[
                bisect.bisect_left(sorted_list, s) : bisect.bisect_left(sorted_list, s + SCAN_LEN)
            ]
            for s in starts
        ]
    )
    total_scanned = sum(len(tree.range_scan(s, s + SCAN_LEN - 1)) for s in starts[:10]) / 10

    # ---------- 删除 ----------
    delete_order = keys[:]
    rng.shuffle(delete_order)
    t_delete = timed(lambda: [tree.delete(k) for k in delete_order])
    assert len(tree) == 0

    def rate(n: int, seconds: float) -> str:
        return f"{n / seconds:,.0f} ops/s"

    def us(n: int, seconds: float) -> str:
        return f"{seconds / n * 1e6:.2f} µs"

    print(f"order={ORDER}（每节点最多 {ORDER - 1} 键），数据量 {N:,}")
    print()
    print(f"{'操作':26}{'总耗时':>12}{'单次':>12}{'吞吐':>16}")
    rows = [
        ("插入 100k（乱序）", t_insert, N),
        ("查找 20k（命中）", t_hit_tree, N_HIT),
        ("查找 20k（未命中）", t_miss_tree, N_MISS),
        (f"范围扫描 100×{SCAN_LEN}", t_scan, N_SCANS),
        ("删除 100k（乱序）", t_delete, N),
    ]
    for label, secs, n in rows:
        print(f"{label:26}{secs:>11.3f}s{us(n, secs):>12}{rate(n, secs):>16}")

    print()
    print("== 与 dict / 有序 list 对照 ==")
    print(f"{'dict 构建 100k':26}{t_dict_build:>11.3f}s")
    print(
        f"{'dict 查找 20k':26}{t_hit_dict:>11.3f}s{us(N_HIT, t_hit_dict):>12}{rate(N_HIT, t_hit_dict):>16}"
    )
    print(
        f"{'tree 查找 20k':26}{t_hit_tree:>11.3f}s{us(N_HIT, t_hit_tree):>12}{rate(N_HIT, t_hit_tree):>16}"
    )
    print(f"{'tree / dict 倍数':26}{t_hit_tree / t_hit_dict:>11.2f}×")
    print(f"{'list 范围扫 100×1k':26}{t_scan_list:>11.4f}s")
    print(f"{'tree 范围扫 100×1k':26}{t_scan:>11.4f}s")

    print()
    print("== 结构 ==")
    print(f"{'树高':26}{height_before:>11}")
    print(f"{'每节点最多键':26}{ORDER - 1:>11}")
    print(f"{'内存峰值(含构建)':26}{peak / 1024 / 1024:>10.1f} MB")
    print(f"{'每键字节（峰值/键）':26}{peak / N:>10.1f} B  （含 Python 对象头，非理论最小值）")
    print(f"{'平均扫描条数(应=1000)':26}{total_scanned:>11.1f}")

    payload = {
        "order": ORDER,
        "n": N,
        "insert_s": t_insert,
        "insert_us": t_insert / N * 1e6,
        "hit_us": t_hit_tree / N_HIT * 1e6,
        "miss_us": t_miss_tree / N_MISS * 1e6,
        "scan_ms_per_1k": t_scan / N_SCANS * 1000,
        "delete_us": t_delete / N * 1e6,
        "dict_hit_us": t_hit_dict / N_HIT * 1e6,
        "tree_vs_dict": t_hit_tree / t_hit_dict,
        "peak_mb": peak / 1024 / 1024,
        "bytes_per_key": peak / N,
        "height": height_before,
    }
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "tmp"), exist_ok=True)
    with open(os.path.join(here, "tmp", "bench_memory.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("\nJSON 已写入 bench/tmp/bench_memory.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
