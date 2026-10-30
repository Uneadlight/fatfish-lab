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
KEY_LINES: <行号，多个用逗号分隔>
REASON: <一句话中文说明，不超过 30 字>
2. 行号按下面文本从 1 开始数。
3. 不要报 PASSED / INFO / OK / 心跳 这类正常行。
4. 不要解释你的推理过程，不要复述原文。

文本（每行前面是行号）：
{numbered}
"""


def call_ollama(prompt: str, model: str = "qwen2.5:3b", timeout: int = 180) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.0},
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
    m = re.search(r"KEY_LINES?\s*[:：]\s*([0-9,，\s]+)", reply, re.IGNORECASE)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
    reason = ""
    r = re.search(r"REASON\s*[:：]\s*(.+)", reply, re.IGNORECASE)
    if r:
        reason = r.group(1).strip()
    return nums, reason


def score(pred: list[int], truth: list[int]) -> dict:
    if not pred:
        return {"hit": False, "precision": 0.0, "recall": 0.0, "missed": truth}
    hit_lines = [p for p in pred if any(abs(p - t) <= TOLERANCE for t in truth)]
    covered = [t for t in truth if any(abs(p - t) <= TOLERANCE for p in pred)]
    return {
        "hit": bool(hit_lines),
        "precision": round(len(hit_lines) / len(pred), 3),
        "recall": round(len(covered) / len(truth), 3),
        "missed": [t for t in truth if t not in covered],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    truth = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))
    rows = []
    for name, t in truth.items():
        text = (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")
        prompt = PROMPT.format(numbered=number_lines(text))
        t0 = time.perf_counter()
        reply = call_ollama(prompt)
        cost_s = time.perf_counter() - t0
        pred, reason = parse(reply)
        s = score(pred, t["lines"])
        rows.append({"sample": name, "truth": t["lines"], "pred": pred,
                     "reason": reason, "seconds": round(cost_s, 2), **s})
        (OUT / f"{name}.json").write_text(
            json.dumps({"reply": reply, "rows": rows[-1]}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        flag = "HIT " if s["hit"] else "MISS"
        print(f"[{flag}] {name:20s} 真因{t['lines']} 它报{pred} "
              f"P={s['precision']:.2f} R={s['recall']:.2f} {cost_s:.1f}s  {reason[:40]}")

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
