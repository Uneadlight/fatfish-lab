"""让本地 3b 在长输出里挑「最可能出错的那几行」，用来自动评分。

设计要点（对应 SKILL.md §0 第 13 条「任务机械拆解」）：
    - 签名写死：只要 KEY_LINES / REASON 两行，别的不要
    - 边界写死：只报 1-3 行；行号从 1 开始；不许报 PASSED/INFO 行
    - 验收写死：我们按行号对不对来算命中率
    - 反例写明：不要解释过程、不要复述日志、不要给建议

输出：out/<样本名>.json —— 原始回复 + 解析出的行号 + 是否命中
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
OUT = ROOT / "out"
TOLERANCE = 2  # 真因前后 2 行内算命中（错误行常和细节行分开）

PROMPT = """下面是一段程序输出。请找出**最可能导致失败的那 1-3 行**（不要找正常的行）。

规则：
1. 只输出两行，格式严格如下，不要有任何其它文字：
KEY_LINES: <行号，多个用逗号分隔；如果整段输出里没有任何真错误，就写 NONE>
REASON: <一句话中文说明，不超过 30 字>
2. 行号按下面文本从 1 开始数。
3. 不要报 PASSED / INFO / OK / 心跳 这类正常行，也不要报表头、进程列表、"Processes:" 这种结构性行。
4. 不要解释你的推理过程，不要复述原文。
5. 什么算"可能导致失败"——按优先级找这四类，找到就停：
   a) 明确的错误：ERROR / FAILED / Error / Exception / Traceback / AssertionError / SyntaxError / 中止 / 失败
   b) **数值异常**：把同一行或相邻两行的数字**互相比较**——用到容量接近上限（如 7912MiB / 8188MiB）、指标超过阈值（如 812ms > 500ms）、剩余量变成 0 或负数、百分比 > 90%
   c) **WARN / 警告**里带"超时""丢弃""不一致""过期"字样的那行
   d) 断言不成立的那行（`assert 5 == 6` 这种）
6. 若同时有 a 和 b，报 b 可能更重要（a 只是后果）。
7. **最多报 2 行**，宁可漏一个也不要凑数：报错行多了等于没筛。
8. 如果所有行都是正常的（只有 PASSED / INFO / ok / 心跳），必须输出 KEY_LINES: NONE，不许硬找。

文本（每行前面是行号）：
{numbered}
"""


def call_ollama(prompt: str, model: str = "qwen2.5:3b", timeout: int = 180) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.0},
        "keep_alive": "120s",
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def number_lines(text: str, limit: int = 200) -> str:
    lines = text.splitlines()
    return "\n".join(f"{i + 1:4d}| {ln}" for i, ln in enumerate(lines[:limit]))


def parse(reply: str) -> tuple[list[int], str]:
    nums: list[int] = []
    if re.search(r"KEY_LINES?\s*[:：]\s*NONE", reply, re.IGNORECASE):
        return [], "(模型判断：无错误)"
    m = re.search(r"KEY_LINES?\s*[:：]\s*([0-9,，\s]+)", reply, re.IGNORECASE)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
    reason = ""
    r = re.search(r"REASON\s*[:：]\s*(.+)", reply, re.IGNORECASE)
    if r:
        reason = r.group(1).strip()
    return nums, reason


def score(pred: list[int], truth: list[int]) -> dict:
    # 空真因 = 这份输出本来就没错。此时"不报"才算对，"报任何一行"都是误报。
    if not truth:
        return {"hit": not pred, "precision": 1.0 if not pred else 0.0,
                "recall": 1.0 if not pred else 0.0, "missed": [], "false_alarm": bool(pred)}
    if not pred:
        return {"hit": False, "precision": 0.0, "recall": 0.0, "missed": truth, "false_alarm": False}
    hit_lines = [p for p in pred if any(abs(p - t) <= TOLERANCE for t in truth)]
    covered = [t for t in truth if any(abs(p - t) <= TOLERANCE for p in pred)]
    return {
        "hit": bool(hit_lines),
        "precision": round(len(hit_lines) / len(pred), 3),
        "recall": round(len(covered) / len(truth), 3),
        "missed": [t for t in truth if t not in covered],
        "false_alarm": False,
    }


# ---- 长输入分块 -------------------------------------------------------------
CHUNK_LINES = 80      # 每块行数（200 行会拆成 3 块，带重叠）
CHUNK_OVERLAP = 15    # 重叠行数：防止真因正好被切在边界上

# ---- 证据校验：模型只负责"提名"，规则负责"要有证据" -------------------------
# 为什么需要：实测它在全绿输出上也会硬报一行（"PASSED 重复执行导致超时"）。
# 所以对模型提名的每一行做一次机械检查——行文本里必须真的含下面这些硬证据之一，
# 否则当幻觉丢弃。规则比模型可靠，这一层不许省。
EVIDENCE = re.compile(
    r"ERROR|FATAL|FAILED|FAIL\b|WARN|Exception|Traceback|AssertionError|SyntaxError|"
    r"invalid syntax|WinError|拒绝访问|不足|超时|丢弃|不一致|过期|漏填|失败|"
    r"MiB|assert",
    re.IGNORECASE,
)


def evidence_ok(line_text: str) -> bool:
    return bool(EVIDENCE.search(line_text))


def filter_evidence(pred: list[int], lines: list[str], tol: int = 3) -> tuple[list[int], list[int]]:
    """模型提名的行必须"有证据"，否则当幻觉丢弃。

    但多行结构（nvidia-smi 一个 GPU 占两行、pytest 的错误栈跨多行）里，
    它常指到"相邻的那一行"，所以做一次**邻近复活**：被丢弃的行若在 ±tol 行内
    存在含证据的行，就认为它指的是同一处，保留。

    返回 (保留, 丢弃)。
    """
    kept: list[int] = []
    dropped: list[int] = []
    for n in pred:
        if not (1 <= n <= len(lines)):
            dropped.append(n)
            continue
        if evidence_ok(lines[n - 1]):
            kept.append(n)
            continue
        lo, hi = max(0, n - 1 - tol), min(len(lines), n + tol)
        if any(evidence_ok(lines[i]) for i in range(lo, hi)):
            kept.append(n)  # 邻近有证据 → 认为它指向同一处
        else:
            dropped.append(n)
    return kept, dropped


def triage_chunked(text: str) -> tuple[list[int], str, str]:
    """把长文本切块分别问，合并全局行号。返回 (行号, 理由, 原始回复拼接)。"""
    lines = text.splitlines()
    total = len(lines)
    picked: set[int] = set()
    reasons: list[str] = []
    raw: list[str] = []
    dropped: list[int] = []
    start = 0
    while start < total:
        end = min(start + CHUNK_LINES, total)
        chunk = "\n".join(f"{i + 1:4d}| {lines[i]}" for i in range(start, end))
        reply = call_ollama(PROMPT.format(numbered=chunk))
        raw.append(f"--- chunk {start + 1}-{end} ---\n{reply}")
        nums, reason = parse(reply)
        globals_ = [n for n in nums if 1 <= n <= total]
        chunks_ = [n for n in globals_ if start < n <= end]
        if chunks_:
            reasons.append(reason or "（无理由）")
        keep, drop = filter_evidence(chunks_, lines)
        picked.update(keep)
        dropped.extend(drop)
        if end >= total:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    note = ""
    if dropped:
        note = f"（规则丢弃无证据行 {dropped}）"
    return sorted(picked), " | ".join(reasons) + note, "\n".join(raw)


def run_file(path: str, context_lines: int = 1) -> int:
    """真实用法：把一份输出文件丢进来，打印它挑出的行 + 上下文。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    t0 = time.perf_counter()
    if len(lines) > CHUNK_LINES:
        pred, reason, _raw = triage_chunked(text)
    else:
        reply = call_ollama(PROMPT.format(numbered=number_lines(text)))
        pred, reason = parse(reply)
        kept, dropped = filter_evidence(pred, lines)
        pred = sorted(set(kept))
        if dropped:
            reason += f"（丢弃无证据行 {sorted(dropped)}）"
    dt = time.perf_counter() - t0
    print(f"文件 {path} 共 {len(lines)} 行，耗时 {dt:.1f}s")
    print(f"模型理由：{reason}")
    if not pred:
        print("→ 没发现错误行（KEY_LINES: NONE）")
        return 0
    for n in pred:
        lo, hi = max(1, n - context_lines), min(len(lines), n + context_lines)
        print(f"\n--- 第 {n} 行（上下文 {lo}-{hi}）---")
        for i in range(lo, hi + 1):
            mark = ">>" if i == n else "  "
            print(f"{mark} {i:5d}| {lines[i - 1]}")
    return 0


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        sys.exit(run_file(sys.argv[2]))
    OUT.mkdir(parents=True, exist_ok=True)
    truth = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))
    rows = []
    for name, t in truth.items():
        text = (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")
        lines = text.splitlines()
        t0 = time.perf_counter()
        if len(lines) > CHUNK_LINES:
            pred, reason, reply = triage_chunked(text)
        else:
            reply = call_ollama(PROMPT.format(numbered=number_lines(text)))
            pred, reason = parse(reply)
            kept, dropped_one = filter_evidence(pred, lines)
            if dropped_one:
                reason += f"（规则丢弃无证据行 {sorted(dropped_one)}）"
            kept = sorted(set(kept))
            if len(set(kept)) != len(set(pred)) or dropped_one:
                reason += f" [保留 {kept}]"
            pred = kept
        cost_s = time.perf_counter() - t0
        s = score(pred, t["lines"])
        rows.append({"sample": name, "truth": t["lines"], "pred": pred,
                     "reason": reason, "seconds": round(cost_s, 2), **s})
        (OUT / f"{name}.json").write_text(
            json.dumps({"reply": reply, "rows": rows[-1]}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        flag = "HIT " if s["hit"] else "MISS"
        print(f"[{flag}] {name:20s} 真因{t['lines']} 它报{pred} "
              f"P={s['precision']:.2f} R={s['recall']:.2f} {cost_s:.1f}s  {reason[:50]}")

    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    mean_p = sum(r["precision"] for r in rows) / n
    mean_r = sum(r["recall"] for r in rows) / n
    print(f"\n命中率 {hits}/{n} = {hits / n:.0%}   平均精确率 {mean_p:.2f}   平均召回 {mean_r:.2f}")
    (OUT / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if hits / n < 0.6:
        print("→ 低于 60% 阈值：按预定规则，这个方向对 3b 不成立。")
        sys.exit(2)


if __name__ == "__main__":
    main()
