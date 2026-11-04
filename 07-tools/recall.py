#!/usr/bin/env python3
"""lab recall —— 按任务自动提词，把记忆库整个扫一遍。

为什么要有这个命令（2026-11-05，用户说「提词+搜+贴账太笼统，不够有保障」）：
  旧做法靠我「主观挑 1-3 个词」，挑错了就等于没搜；`memory_search` 返回的是
  相关度排序，不告诉我「148 条里到底有没有真命中」；降成 3/5 的记忆不注入
  system prompt，只能靠搜——而「搜不到」和「没搜」从结果上看没有区别。

这个命令把三件事变成可复现的：
  1. 提词是算法算的（中文 2-gram + 英文整词，切掉虚词碎片）
  2. 「零命中」是明确的退出码 1，不是一段模棱两可的输出
  3. 每条命中都标 importance——尤其标出哪些 ≤3/5（它们平时不注入，
     只有这条命令或 memory_search 能把它们带出来）

它保证的是「不漏」，不是「排序完美」：宁可多列几条让我自己判断，
也不要因为算法觉得不相关就漏掉一条真正有用的旧结论。

用法:
  lab recall "给 dsh-env-doctor 加一个记忆阈值检查"
  lab recall "插件不生效" --top 10
  lab recall --terms 插件 软链 重启
  lab recall "xxx" --json
  lab recall --audit          # 最近到底有没有在用

退出码: 0=有命中 / 1=零命中 / 2=记忆库读不了
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

MEM = Path.home() / '.dsh' / 'memory' / 'memories.json'
LOG = Path.home() / '.dsh' / 'memory' / '.recall.log'

# 停用词：只删功能词，不删实词。宁可多留，也不要漏掉「记忆」「插件」这种词。
STOP = set("""
的 了 是 在 我 你 他 她 它 把 被 给 和 跟 与 或 就 都 也 还 又 很 太 更 最
这 那 这个 那个 这些 那些 一个 一种 一下 一点 一些 一边 一样 一直
帮我 我们 你们 他们 咱们 自己 人家
能不能 可不可以 可以 怎么 什么 为什么 哪里 哪个 多少 是否
要 需要 想 应该 必须 先 再 然后 现在 马上 一起 已经 还没 没有 不是 不要
注意 记住 记得 千万 一定 务必 继续 往下 接着 进行 完成 做好 搞定
""".split())

# 中文 2-gram 里这些组合没有检索价值（高频但不指物）
BAD_BIGRAM = {'一个', '这个', '那个', '什么', '怎么', '是不', '不是', '可以', '我们',
              '你们', '他们', '自己', '现在', '已经', '如果', '因为', '所以', '但是',
              '而且', '然后', '还是', '就是', '没有', '一下', '这些', '那些', '需要'}

# 虚词单字：2-gram 里只要沾上一个，基本就是跨词边界切出来的噪音。
# （"了不"来自"装了不生效"、"不生"来自"不生效"——它们很少见，如果用 IDF
#   会因为是稀有词被抬高权重，所以必须在提词阶段就切掉。）
FUNC_CHARS = set('的了是在我你他她它把被给和跟与或就都也还又很太更最这那个些一不没有要会能可上中里到对为以之而但如若因所则且着过嘛呢吧啊')


def load_memories() -> list[dict]:
    if not MEM.exists():
        sys.exit(2)
    try:
        db = json.loads(MEM.read_text('utf-8'))
    except Exception:  # noqa: BLE001 - 读不了就是读不了，退出码 2 已经说明
        sys.exit(2)
    return db.get('memories') or []


def extract_terms(text: str) -> list[str]:
    """中文 2-gram + 英文/数字整词，去停用词与重复。"""
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        t = t.strip().lower()
        if len(t) < 2 or t in STOP or t in BAD_BIGRAM or t in seen:
            return
        if len(t) == 2 and (t[0] in FUNC_CHARS or t[1] in FUNC_CHARS):
            return
        seen.add(t)
        terms.append(t)

    # 英文/数字/下划线/连字符整词（代码标识符也算）
    for w in re.findall(r'[A-Za-z0-9_][A-Za-z0-9_.\-]{1,48}', text):
        add(w)
    # 中文段：只保留汉字，按 2-gram 切
    for seg in re.findall(r'[\u4e00-\u9fff]{2,}', text):
        for i in range(len(seg) - 1):
            add(seg[i:i + 2])
    return terms[:16]


def score(mem: dict, terms: list[str]) -> tuple[float, list[str]]:
    content = (mem.get('content') or '').lower()
    tags = ' '.join(mem.get('tags') or []).lower()
    hit: list[str] = []
    pts = 0.0
    for t in terms:
        c = content.count(t)
        g = tags.count(t)
        if c or g:
            hit.append(t)
            # 标签命中比正文命中更准（标签是人打的）；正文里出现多次也不无限加分
            pts += (2.0 if g else 0.0) + (1.0 + 0.3 * math.log(min(c, 5)) if c else 0.0)
    if not hit:
        return 0.0, []
    # 命中词多比单个词反复出现更有说服力
    pts *= 1.0 + 0.25 * (len(hit) - 1)
    # 太长的条目稍微压一点，避免它靠体量霸榜
    pts /= 1.0 + len(content) / 4000.0
    return pts, hit


def first_line(mem: dict, n: int = 52) -> str:
    body = (mem.get('content') or '').replace('\n', ' ').strip()
    body = re.sub(r'^【', '', body)
    return body[:n] + ('…' if len(body) > n else '')


def log_call(terms: list[str], n_hits: int) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': datetime.now().isoformat(timespec='seconds'),
                                'terms': terms[:8], 'hits': n_hits}, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001 - 记不上不影响检索本身
        pass


def do_audit(days: int = 7) -> int:
    if not LOG.exists():
        print('[AUDIT] 一条调用记录都没有——说明这命令从没用过。')
        return 1
    rows = []
    for line in LOG.read_text('utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001 - 坏行跳过，不影响统计
            continue
    cutoff = datetime.now().timestamp() - days * 86400
    recent = []
    for r in rows:
        try:
            if datetime.fromisoformat(r['at']).timestamp() >= cutoff:
                recent.append(r)
        except Exception:  # noqa: BLE001
            continue
    zero = sum(1 for r in recent if not r.get('hits'))
    avg = (sum(r.get('hits', 0) for r in recent) / len(recent)) if recent else 0
    print(f'[AUDIT] 最近 {days} 天：recall {len(recent)} 次，零命中 {zero} 次，平均命中 {avg:.1f} 条')
    if rows:
        print(f'[AUDIT] 最近一次：{rows[-1].get("at")}  提词 {"/".join(rows[-1].get("terms") or [])}')
    gaps = []
    for a, b in zip(rows, rows[1:]):
        try:
            d = (datetime.fromisoformat(b['at']) - datetime.fromisoformat(a['at'])).total_seconds() / 3600
            gaps.append(d)
        except Exception:  # noqa: BLE001
            continue
    if gaps:
        print(f'[AUDIT] 两次之间最长空档 {max(gaps):.1f} 小时（超过 24 小时说明有段时间没查过）')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='按任务自动提词并检索记忆库')
    ap.add_argument('task', nargs='*', help='任务原话（建议整句贴）')
    ap.add_argument('--terms', nargs='+', help='手动指定检索词，跳过自动提词')
    ap.add_argument('--top', type=int, default=8, help='最多显示几条（默认 8）')
    ap.add_argument('--min', type=float, default=1.0, help='最低分（默认 1.0）')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--audit', action='store_true', help='看最近有没有在用')
    ap.add_argument('--days', type=int, default=7, help='--audit 的时间窗口（默认 7 天）')
    a = ap.parse_args()

    if a.audit:
        return do_audit(a.days)
    if not a.task and not a.terms:
        ap.print_help()
        return 2

    text = ' '.join(a.task)
    terms = [t.lower() for t in (a.terms or extract_terms(text))]
    mems = load_memories()
    hits = []
    for m in mems:
        s, h = score(m, terms)
        if s >= a.min:
            hits.append((s, m, h))
    hits.sort(key=lambda x: (-x[0], -(x[1].get('importance') or 0)))
    log_call(terms, len(hits))

    if a.json:
        print(json.dumps({'terms': terms, 'total': len(mems), 'hits': [
            {'id': m['id'], 'importance': m.get('importance'), 'score': round(s, 2),
             'hit': h, 'title': first_line(m, 80)} for s, m, h in hits[:a.top]]},
            ensure_ascii=False, indent=2))
        return 0 if hits else 1

    print(f'[RECALL] 提词 {len(terms)} 个: ' + ' / '.join(terms))
    print(f'[RECALL] {len(mems)} 条里命中 {len(hits)} 条')
    if not hits:
        print('[RECALL] 零命中——按新任务处理；如果确实做过类似的事，换个更具体的词再试一次。')
        return 1

    for i, (s, m, h) in enumerate(hits[:a.top], 1):
        imp = m.get('importance') or 0
        print(f'  {i}. [{imp}/5] {first_line(m)}')
        print(f'       命中: {" ".join(h)}   分数 {s:.1f}   id {m["id"]}')
    low = sum(1 for _, m, _ in hits if (m.get('importance') or 0) <= 3)
    if low:
        print(f'[RECALL] 其中 {low} 条是 3/5 或更低——它们平时不注入 system prompt，'
              f'只有这条命令（或 memory_search）能把它们带出来。')
    print('要读全文: memory_search "<标题里的词>"；要读一条: memory_search "<id>"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
