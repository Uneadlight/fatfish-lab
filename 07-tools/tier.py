#!/usr/bin/env python3
"""开工前报数：这活有多少、手里有什么能用。

**不猜档位**——档位是报数的副产品：
  报不出数 → 说明还没看够，先去查
  数出来了 → 数量 × 单件 摆在那儿，档位自己会说话

用法：
  py lab.py tier "把这 4,545 个插件全过一遍"
  py lab.py tier "修 DSH-Ledger-Collect 失败" --no-assets

判据全部来自任务描述里的**字面信息**，不是我脑补的规模。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 数量词：数字 + 量词
QTY = re.compile(r"(\d[\d,]*)\s*(个|条|件|次|行|字|篇|张|KB|MB|GB|TB)")

# 范围词：出现这些说明"不是挑几个，是全都要"
RANGE_WORDS = ("全部", "所有", "每个", "每一个", "全量", "批量", "逐个", "挨个")

# 重活动词：这些词出现说明要动脑，不是机械操作
HEAVY = ("重写", "重新设计", "架构", "分析", "审计", "梳理", "精读", "推演", "对比")

# 轻活动词
LIGHT = ("改", "修", "加", "补", "删", "换", "更新", "重命名")


def extract(text: str):
    qtys = [(int(m.group(1).replace(",", "")), m.group(0)) for m in QTY.finditer(text)]
    ranges = [w for w in RANGE_WORDS if w in text]
    heavy = [w for w in HEAVY if w in text]
    light = [w for w in LIGHT if w in text]
    return qtys, ranges, heavy, light


def judge(qtys, ranges, heavy, light):
    """报规模 + 给档位建议。每条结论都要能指回原文里的哪个词。"""
    max_qty = max((q for q, _ in qtys), default=1)
    reasons: list[str] = []
    tier = "T1"

    if ranges and max_qty >= 100:
        tier = "T4"
        reasons.append(f"范围词「{ranges[0]}」+ 数量 {max_qty:,} → 一个人扛不完，够拆")
    elif max_qty >= 100:
        tier = "T3"
        reasons.append(f"数量 {max_qty:,} → 单次上下文装不下，要么拆要么换工具")
    elif max_qty >= 20:
        tier = "T2"
        reasons.append(f"数量 {max_qty:,} → 要逐条过，不能一眼扫完")
    elif heavy and not light:
        tier = "T2"
        reasons.append(f"动作词「{heavy[0]}」→ 要动脑，不是照做")
    elif max_qty <= 3 and light and not heavy:
        tier = "T1"
        reasons.append(f"数量 {max_qty} + 动作「{light[0]}」→ 小改")
    elif not qtys and not heavy:
        tier = "T1"
        reasons.append("没数出数量、也没重活动词 → 默认低档，先干着看")
    else:
        tier = "T2"
        reasons.append(f"数量 {max_qty}，动作词 {heavy or light} → 中等，边走边看")

    missing = []
    if max_qty >= 20:
        missing.append("单件多大？（没写就算不出总规模）")
    if not qtys:
        missing.append("一共多少？（描述里没有数量，先数一遍再开工）")

    return tier, reasons, missing


def related_assets(text: str, top: int = 5):
    """从 assets 扫描结果里挑名字出现在任务描述里的（或体积最大的几个）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import assets as assets_mod  # noqa: PLC0415
        rows, _total = assets_mod.scan(1.0)
    except Exception:  # noqa: BLE001
        return []
    hits = []
    for row in rows:
        name = row.get("name") or ""
        if name and name in text:
            hits.append(row)
    if hits:
        return hits[:top]
    # 没命中就退回"最大的几个"——至少让用户知道手边有哪些大件
    rows_sorted = sorted(rows, key=lambda r: -(r.get("size") or 0))
    return rows_sorted[:top]


def fmt_bytes(n):
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main() -> int:
    ap = argparse.ArgumentParser(description="开工前报数：这活有多少、手里有什么能用")
    ap.add_argument("task", help="任务描述（一句话）")
    ap.add_argument("--no-assets", action="store_true", help="跳过资产扫描（快 1 秒，但没推荐）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()

    text = a.task
    qtys, ranges, heavy, light = extract(text)
    tier, reasons, missing = judge(qtys, ranges, heavy, light)

    print("=" * 68)
    print(f"任务：{text}")
    print("=" * 68)
    print()

    print("【1】从字面数出来的")
    print()
    if qtys:
        for q, raw in qtys:
            print(f"  · 数量 {q:>6,}  ← 「{raw}」")
    else:
        print("  · 没数到任何数量")
    if ranges:
        print(f"  · 范围词：{'、'.join(ranges)}")
    if heavy:
        print(f"  · 重活动词：{'、'.join(heavy)}")
    if light:
        print(f"  · 轻活动词：{'、'.join(light)}")
    print()

    print("【2】规模判断")
    print()
    for r in reasons:
        print(f"  → {r}")
    if missing:
        print()
        print("  ⚠️ 还缺的：")
        for m in missing:
            print(f"    · {m}")
    print()

    print(f"【3】档位建议：{tier}")
    print()
    print(f"  （档位是上面报数的副产品，不是先说「我该几档」再去凑数）")
    print()

    if not a.no_assets:
        print("【4】手边可能用得上的")
        print()
        rows = related_assets(text)
        if rows:
            for row in rows:
                print(f"  · {row.get('name', '?'):32s} {fmt_bytes(row.get('size')):>10s}  {row.get('judge', '')}")
        else:
            print("  （资产扫描没结果）")
        print()

    if a.json:
        import json  # noqa: PLC0415
        print(json.dumps({
            "task": text,
            "quantities": [{"n": q, "raw": raw} for q, raw in qtys],
            "ranges": ranges,
            "heavy": heavy,
            "light": light,
            "tier": tier,
            "reasons": reasons,
            "missing": missing,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
