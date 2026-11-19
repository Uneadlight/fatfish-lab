"""lab memcheck —— 找「记忆和执行版说了同一句话」的地方，**不是**自动判定副本。

## 它测什么、不测什么（2026-11-17 实测后修正）

测：记忆里某个句子，与 SKILL.md 里某句的「最长公共子串 / 较短句长度」>= 阈值（默认 0.65）。

**不测**：「这条记忆是不是比 SKILL.md 弱」。措辞重合不等于副本 —— 同一个判据、同一句用户原话、
同一个命令名，**本来就该在两处都出现**，记忆里没有那句话，我就不知道判据是什么。

2026-11-17 首次跑出 55 条 >= 0.65，抽查其中 12 条（分数最高的 4 条 + 重复句最多的 4 条 + 实质词密度 0 的 4 条），
**全部不是副本**，特征分三类：
  1. **命令名重合**（`lab selfcheck` / `lab assets` / `lab recall --audit`）—— 几乎是噪声
  2. **判据原文重合**（「判据是共用同一段代码」「答不出就先建一条」）—— 正常引用
  3. **事实性记忆**（用户偏好 / 放弃过的方案 / 项目现状）—— 本来就没有「判据/步骤」词，
     用「实质词密度」筛会把它们全部误伤（密度 0 的 4 条全是正常事实记录）

## 真正能识别的副本长什么样（人工判据）

上午我肉眼判定的 3 条真副本（`mem_mw53hf7u_xlia1i` / `mem_mw4tbqks_5q50bj` / `mem_mw53mrcr_cxah8j`），
共同特征是 **记忆正文只有「标题 + 一句用户原话」，SKILL.md 那边有完整步骤和判据** ——
即「记忆真空」：字数少、没有可执行颗粒度、也没有写落点。

2026-11-17 抽到的 12 条**都不符合这个特征** —— 它们都有 SKILL.md 没有的细节（实例、警告、禁令、边界）。

## 所以它的正确用法

**当清单用，不当判据用**：跑它 → 得到「两处都说了同一件事」的候选 → **人工看哪边更完整**：
  - 记忆写了目标版本（`见 SKILL.md §0 第 20 条`）→ **不用改**
  - 记忆只有标题+原话、SKILL.md 有步骤 → 记忆改成指针
  - 记忆有 SKILL.md 没有的细节 → **记忆是全文，SKILL.md 才该补**（反过来）

输出里 `dup_sent_count / total_sent`（重复句占比）比分数更有用：占比 > 30% 才值得细看。

用法：
  python memcheck.py                      # 默认扫 SKILL.md，阈值 0.65
  python memcheck.py --min 0.5            # 放宽（噪声会更多）
  python memcheck.py --id mem_xxx         # 只看一条
  python memcheck.py --json               # 机器可读
  python memcheck.py --corpus <路径>       # 换执行版（可多次，默认 SKILL.md）

实现要点：
  - 3-gram 倒排索引先把「可能的候选句」筛出来，再对候选算 LCS（否则 2600 句 × 2000 句全比太慢）
  - 切句按 。！？；\n 切，过滤 < 12 字的碎片（「对。」这种没信息量）
  - 分数 = LCS 长度 / min(两句话长度)，1.0 表示一句完全包含另一句
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

MEM_FILE = os.path.expandvars(r"%USERPROFILE%\.dsh\memory\memories.json")
DEFAULT_CORPUS = [
    r"D:\work\dsh-workflow-skill\skills\workflow\SKILL.md",
]
MIN_SENT = 12
SENT_SPLIT = re.compile(r"[。！？；\n]+")


def split_sents(text: str) -> list[str]:
    """切成句子，只保留有信息量的（>= MIN_SENT 字，去掉纯标点/空）。"""
    out = []
    for s in SENT_SPLIT.split(text or ""):
        s = s.strip()
        if len(s) >= MIN_SENT:
            out.append(s)
    return out


def grams(s: str, n: int = 3) -> set[str]:
    if len(s) < n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def lcs_len(a: str, b: str) -> int:
    """最长公共子串长度。句子短（几十字），O(n*m) 可接受。"""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


class Corpus:
    """执行版语料：句子 + 3-gram 倒排索引。"""

    def __init__(self, paths: list[str]):
        self.sents: list[tuple[str, str]] = []  # (句子, 来源文件)
        for p in paths:
            if not os.path.exists(p):
                continue
            with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            for s in split_sents(txt):
                self.sents.append((s, os.path.basename(p)))
        self.index: dict[str, list[int]] = {}
        for i, (s, _) in enumerate(self.sents):
            for g in grams(s):
                self.index.setdefault(g, []).append(i)

    def best_match(self, sent: str) -> tuple[float, str, str]:
        """返回 (分数, 命中句, 来源文件)。没有候选返回 0。"""
        gs = grams(sent)
        cnt: dict[int, int] = {}
        for g in gs:
            for i in self.index.get(g, ()):
                cnt[i] = cnt.get(i, 0) + 1
        # 只对「至少命中 2 个 gram」的候选算 LCS，控制成本
        cand = [i for i, c in cnt.items() if c >= 2]
        if not cand:
            return 0.0, "", ""
        best = (0.0, "", "")
        for i in cand:
            osent, src = self.sents[i]
            n = lcs_len(sent, osent)
            if n < MIN_SENT // 2:
                continue
            sc = n / min(len(sent), len(osent))
            if sc > best[0]:
                best = (sc, osent, src)
        return best


def load_memories() -> list[dict]:
    with io.open(MEM_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("memories", [])
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="找记忆与执行版「说了同一句话」的地方（清单，不是判据）")
    ap.add_argument("--min", type=float, default=0.65, help="分数阈值（默认 0.65）")
    ap.add_argument("--id", help="只看某一条记忆")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--corpus", action="append", help="执行版文件（可多次，默认 SKILL.md）")
    ap.add_argument("--min-ratio", type=float, default=0.0, help="只看重复句占比 >= 此值的（如 0.3）")
    a = ap.parse_args(argv)

    corpus_paths = a.corpus or DEFAULT_CORPUS
    corpus = Corpus(corpus_paths)
    if not corpus.sents:
        print("[ERR] 执行版语料为空，检查路径：", file=sys.stderr)
        for p in corpus_paths:
            print("  ", p, file=sys.stderr)
        return 2

    mems = load_memories()
    hits = []
    for m in mems:
        if a.id and m.get("id") != a.id:
            continue
        content = m.get("content") or ""
        sents = split_sents(content)
        if not sents:
            continue
        scored = []
        for s in sents:
            sc, osent, src = corpus.best_match(s)
            if sc > 0:
                scored.append((sc, s, osent, src))
        if not scored:
            continue
        scored.sort(key=lambda x: -x[0])
        top = scored[0]
        dup = sum(1 for x in scored if x[0] >= a.min)
        ratio = dup / len(sents)
        if top[0] < a.min or ratio < a.min_ratio:
            continue
        hits.append(
            {
                "id": m.get("id"),
                "importance": m.get("importance"),
                "tags": m.get("tags") or [],
                "score": round(top[0], 3),
                "ratio": round(ratio, 3),
                "mem_sent": top[1][:120],
                "doc_sent": top[2][:120],
                "doc_file": top[3],
                "dup_sent_count": dup,
                "total_sent": len(sents),
                "mem_chars": len(content),
            }
        )

    hits.sort(key=lambda x: (-x["ratio"], -x["score"]))

    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    print(f"执行版语料 {len(corpus.sents)} 句（{' / '.join(os.path.basename(p) for p in corpus_paths)}）")
    print(f"记忆 {len(mems)} 条，阈值 {a.min}" + (f"，重复占比 >= {a.min_ratio}" if a.min_ratio else ""))
    print()
    if not hits:
        print("✅ 没找到达到阈值的。")
        return 0
    print(f"{len(hits)} 条「两处说了同一句话」——**逐条人工看哪边更完整**，别当副本自动处理：\n")
    for h in hits:
        imp = (h["importance"] or 0) * "\u2605"
        print(f"  [{h['score']:.2f} / 占比 {h['ratio']*100:.0f}%] {h['id']}  {imp}  {h['mem_chars']} 字")
        print(f"         记忆: {h['mem_sent']}")
        print(f"         执行: {h['doc_sent']}   ({h['doc_file']})")
    print()
    print("判读（2026-11-17 抽查 12 条后定）：")
    print("  · 占比 < 30% 多半是命令名/判据原文重合 —— 正常引用，不用改")
    print("  · 记忆只有标题+用户原话、SKILL.md 有步骤 —— 记忆改成指针")
    print("  · 记忆有 SKILL.md 没有的细节（实例/警告/边界）—— 记忆是全文，该补的是 SKILL.md")
    return 1 if hits else 0


def cmd_memcheck(args) -> int:
    """lab 子命令入口：把 argparse 的 Namespace 翻回 argv 交给 main()。"""
    argv: list[str] = []
    argv += ["--min", str(args.min)]
    if args.min_ratio:
        argv += ["--min-ratio", str(args.min_ratio)]
    if args.id:
        argv += ["--id", args.id]
    if args.json:
        argv.append("--json")
    for c in args.corpus or []:
        argv += ["--corpus", c]
    return main(argv)


def register(sub) -> None:
    p = sub.add_parser(
        "memcheck",
        help="找记忆与执行版「说了同一句话」的地方（清单，不是副本判据）",
    )
    p.add_argument("--min", type=float, default=0.65, help="分数阈值（默认 0.65）")
    p.add_argument("--min-ratio", type=float, default=0.0,
                   help="只看重复句占比 >= 此值（如 0.3；比分数更有用）")
    p.add_argument("--id", help="只看一条记忆")
    p.add_argument("--json", action="store_true", help="机器可读输出")
    p.add_argument("--corpus", action="append", help="执行版文件（可多次，默认 SKILL.md）")
    p.set_defaults(func=cmd_memcheck)


if __name__ == "__main__":
    sys.exit(main())
