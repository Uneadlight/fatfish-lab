"""磁盘 I/O 实测：页式 B+ 树 vs 每节点一页的朴素 BST。

输出两张表：
1. 构建期（页数、写页次数、墙钟）
2. 查询期（冷池每次查找的**真实 pread 次数**、耗时；热池命中率）

用法：
    ..\\.venv\\Scripts\\python.exe bench\\bench_disk_io.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib

from bplus.naive_bst import PagedBST  # noqa: E402
from bplus.paged import PAGE_SIZE, PagedBPlusTree  # noqa: E402

N_KEYS = 100_000
N_LOOKUPS = 2_000
RANGE_LEN = 1_000
POOL_PAGES = 64


def human(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"


def bench_bpt(path: str) -> dict:
    if os.path.exists(path):
        os.remove(path)
    keys = list(range(N_KEYS))
    t0 = time.perf_counter()
    tree = PagedBPlusTree(path, pool_size=POOL_PAGES)
    for k in keys:
        tree.insert(k, k * 2)
    build_s = time.perf_counter() - t0
    build_stats = tree.stats
    height = tree.height
    file_size = os.path.getsize(path)

    rng = random.Random(42)
    probe = [rng.randrange(N_KEYS) for _ in range(N_LOOKUPS)]

    # 冷池：每次查找前清空缓冲池 → 每个页都必须真 pread
    tree.reset_counters()
    t0 = time.perf_counter()
    for k in probe:
        tree.clear_pool()
        tree.search(k)
    cold_s = time.perf_counter() - t0
    cold = tree.stats

    # 热池：不清空，模拟真实缓存命中
    tree.reset_counters()
    t0 = time.perf_counter()
    for k in probe:
        tree.search(k)
    warm_s = time.perf_counter() - t0
    warm = tree.stats

    # 范围扫描：1000 个连续 key
    tree.reset_counters()
    tree.clear_pool()
    t0 = time.perf_counter()
    got = tree.range_scan(N_KEYS // 2, N_KEYS // 2 + RANGE_LEN - 1)
    scan_s = time.perf_counter() - t0
    scan = tree.stats
    assert len(got) == RANGE_LEN, f"范围扫描拿到 {len(got)} 条"

    tree.close()
    return {
        "name": "页式 B+ 树（每页 255 键）",
        "keys": N_KEYS,
        "height": height,
        "pages": build_stats["pages"],
        "file_mb": file_size / 1024 / 1024,
        "build_s": build_s,
        "build_writes": build_stats["page_writes"],
        "writes_per_insert": build_stats["page_writes"] / N_KEYS,
        "cold_reads_per_lookup": cold["page_reads"] / N_LOOKUPS,
        "cold_us_per_lookup": cold_s / N_LOOKUPS * 1e6,
        "warm_reads_per_lookup": warm["page_reads"] / N_LOOKUPS,
        "warm_hit_rate": warm["pool_hits"] / max(1, warm["pool_hits"] + warm["pool_misses"]),
        "warm_us_per_lookup": warm_s / N_LOOKUPS * 1e6,
        "scan_reads": scan["page_reads"],
        "scan_ms": scan_s * 1000,
    }


def bench_bst(path: str) -> dict:
    if os.path.exists(path):
        os.remove(path)
    keys = list(range(N_KEYS))
    insert_order = keys[:]
    random.Random(7).shuffle(insert_order)  # 顺序插入会退化成链表，这里模拟"随机键"
    t0 = time.perf_counter()
    bst = PagedBST(path)
    for k in insert_order:
        bst.insert(k, k * 2)
    build_s = time.perf_counter() - t0
    build_stats = bst.stats
    height = bst.height
    file_size = os.path.getsize(path)

    rng = random.Random(42)
    probe = [rng.randrange(N_KEYS) for _ in range(N_LOOKUPS)]

    bst.reset_counters()
    t0 = time.perf_counter()
    for k in probe:
        bst.search(k)
    search_s = time.perf_counter() - t0
    st = bst.stats

    # 没有叶子链，做范围扫描只能逐 key 重新从根爬
    bst.reset_counters()
    t0 = time.perf_counter()
    for k in range(N_KEYS // 2, N_KEYS // 2 + RANGE_LEN):
        bst.search(k)
    scan_s = time.perf_counter() - t0
    scan = bst.stats

    bst.close()
    return {
        "name": "朴素页式 BST（每页 1 键）",
        "keys": N_KEYS,
        "height": height,
        "pages": build_stats["pages"],
        "file_mb": file_size / 1024 / 1024,
        "build_s": build_s,
        "build_writes": build_stats["page_writes"],
        "writes_per_insert": build_stats["page_writes"] / N_KEYS,
        "cold_reads_per_lookup": st["page_reads"] / N_LOOKUPS,
        "cold_us_per_lookup": search_s / N_LOOKUPS * 1e6,
        "scan_reads": scan["page_reads"],
        "scan_ms": scan_s * 1000,
    }


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = os.path.join(here, "tmp")
    os.makedirs(tmp, exist_ok=True)
    bpt_path = os.path.join(tmp, "bench_bpt.idx")
    bst_path = os.path.join(tmp, "bench_bst.idx")

    print(f"数据量 {N_KEYS:,} 条 key，查找 {N_LOOKUPS:,} 次，页大小 {PAGE_SIZE} 字节，缓冲池 {POOL_PAGES} 页")
    print("构建页式 B+ 树 ...")
    bpt = bench_bpt(bpt_path)
    print("构建朴素页式 BST ...")
    bst = bench_bst(bst_path)

    ratio_reads = bst["cold_reads_per_lookup"] / bpt["cold_reads_per_lookup"]
    ratio_time = bst["cold_us_per_lookup"] / bpt["cold_us_per_lookup"]
    ratio_scan = bst["scan_reads"] / max(1, bpt["scan_reads"])

    print()
    print("== 结构 ==")
    print(f"{'':22}{'B+ 树':>18}{'朴素 BST':>18}")
    for label, key in [("树高", "height"), ("总页数", "pages"), ("文件大小(MB)", "file_mb")]:
        a, b = bpt[key], bst[key]
        fmt = "{:>18.2f}" if isinstance(a, float) else "{:>18,}"
        print(f"{label:22}" + fmt.format(a) + fmt.format(b))

    print()
    print("== 构建 ==")
    print(f"{'':22}{'B+ 树':>18}{'朴素 BST':>18}")
    print(f"{'耗时':22}{human(bpt['build_s']):>18}{human(bst['build_s']):>18}")
    print(f"{'写页次数':22}{bpt['build_writes']:>18,}{bst['build_writes']:>18,}")
    print(f"{'写页/插入':22}{bpt['writes_per_insert']:>18.2f}{bst['writes_per_insert']:>18.2f}")

    print()
    print("== 点查（冷缓冲池 = 每次查找都真 pread） ==")
    print(f"{'':22}{'B+ 树':>18}{'朴素 BST':>18}")
    print(f"{'页读次数/次':22}{bpt['cold_reads_per_lookup']:>18.2f}{bst['cold_reads_per_lookup']:>18.2f}")
    print(f"{'耗时/次(µs)':22}{bpt['cold_us_per_lookup']:>18.2f}{bst['cold_us_per_lookup']:>18.2f}")
    print(f"→ BST 的页读次数是 B+ 树的 {ratio_reads:.1f} 倍，耗时是 {ratio_time:.1f} 倍")

    print()
    print("== 点查（热缓冲池） ==")
    print(f"{'B+ 树':22}页读/次 {bpt['warm_reads_per_lookup']:.2f}，命中率 {bpt['warm_hit_rate'] * 100:.1f}%，耗时/次 {bpt['warm_us_per_lookup']:.2f} µs")

    print()
    print(f"== 范围扫描 {RANGE_LEN} 个连续 key ==")
    print(f"{'':22}{'B+ 树':>18}{'朴素 BST':>18}")
    print(f"{'页读次数':22}{bpt['scan_reads']:>18,}{bst['scan_reads']:>18,}")
    print(f"{'耗时':22}{human(bpt['scan_ms'] / 1000):>18}{human(bst['scan_ms'] / 1000):>18}")
    print(f"→ 范围扫描 BST 多读 {ratio_scan:.1f} 倍页（它没有叶子链，只能逐 key 回根爬）")

    payload = {
        "config": {"n_keys": N_KEYS, "n_lookups": N_LOOKUPS, "range_len": RANGE_LEN, "page_size": PAGE_SIZE, "pool_pages": POOL_PAGES},
        "bpt": bpt,
        "bst": bst,
        "ratios": {"reads": ratio_reads, "time": ratio_time, "scan_reads": ratio_scan},
    }
    with open(os.path.join(here, "tmp", "bench_disk_io.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("\nJSON 已写入 bench/tmp/bench_disk_io.json")

    for p in (bpt_path, bst_path):
        with contextlib.suppress(OSError):
            os.remove(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
