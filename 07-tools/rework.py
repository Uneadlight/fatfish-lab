"""返工审计：我在哪儿被否定了，否定得多不多。

为什么要这个：`lab correction` 能记「用户原话 / 我原来的想法 / 改成了什么」，
但它靠我自觉——今天（11-04）被纠正了三次（档位方案、掌控力分层、P9 指标），
一条都没记进去。**记录工具没人用，等于没有记录。**

这个工具换个入口：不去问「你有没有被纠正」，而是**从会话原文里把否定句捞出来**。
它只做一件事——把「用户明确否定我上一句话」的时刻列出来，让我自己看模式。
不判断对错、不给建议（判断是我下）。
"""
import io
import json
import re
import time
import sys
import zstandard as zstd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_grep import message_text  # noqa: E402

SESS_ROOT = Path.home() / '.dsh' / 'sessions'

# 用户明确否定的信号。宁可漏，别误报——误报的代价是我以后不信这个工具。
NEGATIVE = [
    '不是这样', '不是这个', '不是能', '不是让我', '不是我', '不对', '错了', '你说错', '搞错',
    '再想想', '重新想', '再认真', '再思考', '再优化',
    '我不是说', '我说的不是', '理解错', '你误会', '没懂', '没做对',
    '换个', '不要这样', '别再', '你又', '怎么又', '你犯傻', '又犯', '忘记',
    '我做错了吗', '有问题吧', '怎么回事', '为什么还',
]

# 这些是「否定但正常讨论」，容易误报，先从否定词里排除
SOFT = ['没错', '不错', '对不对', '是不是', '要不要', '好不好', '行不行', '不是吗']


def _unzstd(path: Path):
    with open(path, 'rb') as fh:
        r = zstd.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        yield from io.TextIOWrapper(r, encoding='utf-8', errors='replace')


def _text_of(rec) -> str:
    # 复用 session_grep 的取文本逻辑——那边已经处理过 user/message 和
    # assistant/message 两种结构，自己重写一遍就是在造第二个真相。
    try:
        return (message_text(rec) or '').strip()
    except Exception:
        return ''


def scan(days: float = 3.0) -> list[dict]:
    cutoff = time.time() - days * 86400
    hits = []
    for p in sorted(SESS_ROOT.glob('*/session-*/session.v4.jsonl.zstd')):
        try:
            if p.stat().st_mtime < cutoff:
                continue
        except Exception:
            continue
        sid = p.parent.name.replace('session-', '')[:8]
        prev_mine = ''
        for line in _unzstd(p):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get('time') or 0
            if t > 1e11:
                t = t / 1000.0
            if not t or t < cutoff:
                continue
            typ = rec.get('type')
            if typ == 'assistant/message':
                txt = _text_of(rec)
                if txt:
                    prev_mine = txt
            elif typ == 'user/message':
                said = _text_of(rec)
                if not said or len(said) > 800:
                    continue
                if any(s in said for s in SOFT):
                    continue
                marked = [k for k in NEGATIVE if k in said]
                if not marked:
                    continue
                hits.append({
                    't': t,
                    'sid': sid,
                    'said': said[:200].replace('\n', ' '),
                    'was': prev_mine[:160].replace('\n', ' '),
                    'marks': marked,
                })
    hits.sort(key=lambda h: h['t'])
    return hits



# ── 第二个视图：给了方案，但没先复述「你要的是什么」 ──
# 这才是 P15 的硬判据：不靠否定词（误报多），靠结构（能不能对上）。
PLAN_MARK = ['我的方案', '我建议', '我打算', '可以这样做', '我准备', '计划是',
             '我倾向于', '两个选择', '三个方案', '方案 A', '方案一']
RESTATE_MARK = ['你要的是', '你要我做的', '我理解你要', '你真正的意思', '复述一下']


def scan_restate(days: float = 3.0) -> dict:
    cutoff = time.time() - days * 86400
    plans = restated = 0
    misses = []
    for p in sorted(SESS_ROOT.glob('*/session-*/session.v4.jsonl.zstd')):
        try:
            if p.stat().st_mtime < cutoff:
                continue
        except Exception:
            continue
        sid = p.parent.name.replace('session-', '')[:8]
        recent: list[str] = []
        for line in _unzstd(p):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get('time') or 0
            if t > 1e11:
                t = t / 1000.0
            if not t or t < cutoff:
                continue
            typ = rec.get('type')
            if typ == 'user/message':
                recent = []
                continue
            if typ != 'assistant/message':
                continue
            txt = _text_of(rec)
            if not txt:
                continue
            has_plan = any(k in txt for k in PLAN_MARK)
            has_restate = any(k in txt for k in RESTATE_MARK)
            if has_plan:
                plans += 1
                if has_restate or any(any(k in r for k in RESTATE_MARK) for r in recent):
                    restated += 1
                else:
                    head = txt.strip().replace('\n', ' ')[:100]
                    misses.append({'t': t, 'sid': sid, 'head': head})
            recent.append(txt)
            if len(recent) > 2:
                recent.pop(0)
    return {'plans': plans, 'restated': restated, 'misses': misses}


def main() -> int:
    rows = scan()
    if not rows:
        print('最近 3 天没扫到「用户否定」的时刻。')
        return 0

    print('=' * 70)
    print(f'返工审计（最近 3 天，{len(rows)} 次被否定）')
    print('=' * 70)
    print()
    for h in rows:
        when = time.strftime('%m-%d %H:%M', time.localtime(h['t']))
        print(f'── {when}  [{h["sid"]}]  命中：{" / ".join(h["marks"])} ──')
        print(f'  你说的：{h["said"][:150]}')
        if h['was']:
            print(f'  我原来：{h["was"][:120]}')
        print()

    # 按命中词频次看「我常在哪类地方被否」
    freq: dict[str, int] = {}
    for h in rows:
        for m in h['marks']:
            freq[m] = freq.get(m, 0) + 1
    top = sorted(freq.items(), key=lambda x: -x[1])[:6]
    print('【否定词频次】')
    for k, v in top:
        print(f'  {k:<8} {v} 次')
    print()
    print(f'  3 天内 {len(rows)} 次 = 平均每天 {len(rows) / 3:.1f} 次')
    print('  （这只是「我自己能识别的否定」；更隐晦的纠正扫不出来）')
    print()

    # ── 第二个视图 ──
    r = scan_restate()
    print('=' * 70)
    print(f'【给方案前有没有先复述「你要的是什么」】最近 3 天')
    print('=' * 70)
    print(f'  给方案 {r["plans"]} 次 / 其中先复述过 {r["restated"]} 次')
    if r['plans']:
        print(f'  ✅ 复述率 {r["restated"] * 100 // r["plans"]}%')
    for m in r['misses'][:8]:
        when = time.strftime('%m-%d %H:%M', time.localtime(m['t']))
        print(f'    {when} [{m["sid"]}] {m["head"]}')
    if r['misses']:
        print()
        print('  判据：一条回复里出现「我的方案/我建议/我打算/两个选择…」，但同一条或前 2 条里')
        print('        没有「你要的是/你要我做的/我理解你要」——就算「没复述直接给方案」。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
