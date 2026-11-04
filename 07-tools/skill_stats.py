#!/usr/bin/env python3
"""能力熟练度：我哪些本事真熟了，哪些只是用过、哪些还没用上。

分层只有两层（2026-11-04 用户纠正，不许用"每天/每周/每月"这类时间跨度）：
  - 必熟 = 用过的
  - 该熟 = 没用过的（不是"不用管"，是"应该会但还没会"）

三个判据：
  1. 真熟度   —— 用过的里面，错误率 <2% 且从头到尾没重试过
  2. 配对缺失 —— 用 A 的时候，本该配套用的 B 一次没用
  3. 会话长度 —— 一次会话调了多少次工具

数据源：~/.dsh/sessions/*/session-*/session.v4.jsonl.zstd
字段：`tool/call` 的 data 是 {turn, step, callId, name, arguments}；
     `tool/result` 的 data.message 是 {toolCallId, isError, content}。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import zstandard
except ImportError:
    print("[ERROR] 需要 zstandard（pip install zstandard）", file=sys.stderr)
    sys.exit(2)

SESSIONS = Path.home() / ".dsh" / "sessions"

# 本该配套出现的组合：用 key 的时候，value 里至少一个该跟着出现。
# 阈值不设 100% —— 有些场景确实不需要配套（比如新建文件就不用先 read）。
#
# 2026-11-04 删掉两条错假设：
#   compress -> acp_status：压缩大多是 bili 的 nudge 自动触发的，不是我手动调，
#     要求"先查状态再压"不成立（实测 298 次压缩只查了 10 次，那 10 次是我主动压）。
#   workflow -> spawn_teammate：workflow 是批量 fan-out、spawn_teammate 是长期队友，
#     两回事，不是必须配套（实测 workflow 27 次、spawn_teammate 0 次，但这不是缺失）。
PAIRS = {
    "terminal_open": ("terminal_send", "terminal_read", "terminal_close"),
    "terminal_send": ("terminal_read",),
    "memory_save": ("memory_search",),
    "write": ("read",),
    "edit": ("read",),
}

PAIR_FLOOR = 0.20      # 配套率低于这个才报
GOOD_ERR_RATE = 0.02   # 错误率低于这个才算"真熟"
GOOD_RETRY_RATE = 0.05 # 重试率低于这个才算"真熟"
MIN_SAMPLE = 5         # 调用次数少于此的不判真熟/费劲（样本太小，噪声大）


def all_known_tools() -> list[str]:
    """从 tool_stats.KNOWN 拿全部已知工具名（同目录导入）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from tool_stats import KNOWN  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    names: list[str] = []
    for group in KNOWN.values():
        names.extend(group)
    return names


def collect():
    """按会话收集调用序列、错误、真重试。"""
    calls = Counter()      # 工具 -> 调用次数
    errors = Counter()     # 工具 -> 出错次数
    retries = Counter()    # 工具 -> 出错后立刻又调同一个
    sequences = []
    sessions = 0
    bad_files = 0

    for path in SESSIONS.glob("*/session-*/session.v4.jsonl.zstd"):
        sessions += 1
        seq: list[str] = []
        name_of: dict[str, str] = {}
        prev_name, prev_err = None, False
        try:
            with path.open("rb") as handle:
                reader = zstandard.ZstdDecompressor().stream_reader(handle)
                for line in io.TextIOWrapper(reader, encoding="utf-8"):
                    if '"tool/call"' not in line and '"tool/result"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = record.get("type")
                    data = record.get("data") or {}
                    if kind == "tool/call":
                        name = data.get("name") or "?"
                        cid = data.get("callId") or ""
                        name_of[cid] = name
                        calls[name] += 1
                        seq.append(name)
                        # 真重试：上一次调用的结果就是错的，而且是同一个工具
                        if prev_name == name and prev_err:
                            retries[name] += 1
                        prev_name, prev_err = name, False
                    elif kind == "tool/result":
                        msg = data.get("message") or {}
                        cid = msg.get("toolCallId") or ""
                        name = name_of.get(cid)
                        if not name:
                            continue
                        is_err = bool(msg.get("isError"))
                        if is_err:
                            errors[name] += 1
                        prev_name, prev_err = name, is_err
        except Exception as exc:  # noqa: BLE001
            bad_files += 1
            print(f"  [WARN] {path.parent.name[:18]}: {exc}", file=sys.stderr)
        sequences.append(seq)

    if bad_files:
        print(f"  [WARN] {bad_files} 个会话读失败", file=sys.stderr)
    return calls, errors, retries, sequences, sessions


def analyze(calls, errors, retries, sequences, sessions):
    known = all_known_tools()
    known_set = set(known)
    used = [t for t in known if calls.get(t, 0) > 0]
    unused = [t for t in known if calls.get(t, 0) == 0]
    # 不在 KNOWN 清单里的新工具，也算用过的
    for name, n in calls.items():
        if n > 0 and name not in known_set:
            used.append(name)
    total = len(used) + len(unused)

    def err_rate(name):
        n = calls.get(name, 0)
        return errors.get(name, 0) / n if n else 0.0

    def retry_rate(name):
        n = calls.get(name, 0)
        return retries.get(name, 0) / n if n else 0.0

    # 样本太小的不判真熟/费劲（1 次错 1 次就是 100%，是噪声不是结论）
    small = [t for t in used if calls.get(t, 0) < MIN_SAMPLE]
    judged = [t for t in used if calls.get(t, 0) >= MIN_SAMPLE]
    good = [t for t in judged if err_rate(t) < GOOD_ERR_RATE and retry_rate(t) < GOOD_RETRY_RATE]
    good_set = set(good)
    flaky = [t for t in judged if t not in good_set]

    print("=" * 68)
    print(f"能力熟练度（{sessions} 个会话，{sum(calls.values()):,} 次工具调用）")
    print("=" * 68)

    # ---- 0. 分层汇总 + 分数 ----
    print()
    print("【0】分层：只用两层，不用时间跨度")
    print()
    print(f"  必熟（用过的）  {len(used):3d} 个")
    print(f"    ├ 真熟        {len(good):3d} 个（错误率 <{GOOD_ERR_RATE:.0%} 且重试率 <{GOOD_RETRY_RATE:.0%}）")
    print(f"    ├ 用得费劲    {len(flaky):3d} 个")
    print(f"    └ 样本太少    {len(small):3d} 个（<{MIN_SAMPLE} 次，不判）")
    print(f"  该熟（没用过的）{len(unused):3d} 个")
    print(f"  合计            {total:3d} 个")
    print()
    score = len(good) / total if total else 0
    print(f"  **掌控力 = 真熟 {len(good)} / 全部 {total} = {score:.1%}**")
    print()

    if unused:
        print("  该熟清单（还没用上）：")
        for t in sorted(unused):
            print(f"    · {t}")

    if flaky:
        print()
        print("  必熟但用得费劲：")
        for t in sorted(flaky, key=lambda x: -calls.get(x, 0)):
            print(f"    ! {t:22s} 调 {calls.get(t, 0):5,} 错 {errors.get(t, 0):3,} "
                  f"({err_rate(t):.1%}) 重试 {retries.get(t, 0):3,}")

    # ---- 1. 配对缺失 ----
    print()
    print("【1】配对缺失：用了 A，但该配套的 B 一次没用")
    print()
    gaps = []
    for tool, partners in PAIRS.items():
        n = calls.get(tool, 0)
        if n < 3:
            continue
        hit = sum(calls.get(p, 0) for p in partners)
        ratio = hit / n
        if ratio < PAIR_FLOOR:
            gaps.append((tool, n, hit, ratio, partners))
    if gaps:
        for tool, n, hit, ratio, partners in sorted(gaps, key=lambda x: -x[1]):
            print(f"  ⚠️  {tool:18s} {n:5,} 次 → 配套只有 {hit} 次（{ratio:.0%}）")
            print(f"      该配套：{', '.join(partners)}")
    else:
        print("  ✅ 没有明显缺失")

    # ---- 2. 会话长度 ----
    print()
    print("【2】会话长度：一次会话调了多少次工具")
    print()
    lens = sorted((len(s) for s in sequences), reverse=True)
    if lens:
        print(f"  最长 {lens[0]:,} 次 / 中位 {lens[len(lens) // 2]:,} 次 / 共 {len(lens)} 个会话")
        print(f"  >500 次的会话：{sum(1 for n in lens if n > 500)} 个")

    return {
        "score": score,
        "total": total,
        "good": len(good),
        "flaky": len(flaky),
        "unused": len(unused),
        "gaps": gaps,
    }


def main():
    ap = argparse.ArgumentParser(description="能力熟练度：真熟 / 用得费劲 / 还没用上")
    ap.add_argument("--json", action="store_true", help="额外输出 JSON")
    a = ap.parse_args()

    if not SESSIONS.is_dir():
        print(f"[ERROR] 找不到会话目录: {SESSIONS}", file=sys.stderr)
        return 2

    calls, errors, retries, sequences, sessions = collect()
    summary = analyze(calls, errors, retries, sequences, sessions)

    if a.json:
        print()
        print(json.dumps({
            "sessions": sessions,
            "calls": sum(calls.values()),
            "score": round(summary["score"], 4),
            "total": summary["total"],
            "good": summary["good"],
            "flaky": summary["flaky"],
            "unused": summary["unused"],
            "errors": dict(errors),
            "retries": dict(retries),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
