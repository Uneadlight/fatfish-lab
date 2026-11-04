"""按工具聚合报错原文——给「错在哪」的证据，不给「该怎么办」的结论。

为什么要它：`lab skill` 只告诉我"edit 错误率 6.5%"，`lab tools` 只告诉我"哪个工具没用过"，
**没有一个工具告诉我"这些错误具体是什么"**。2026-11-04 我是写临时脚本才发现
edit 的 86 条报错里 40+ 条是 `file has not been read`——猜的是「凭印象写 old_string」，
实际差得远。这个子命令就是把那次临时脚本固定下来。

结论仍然要我下：它只列原文和频次，不写"建议动作"。
"""
import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import zstandard as zstd

SESS_ROOT = Path.home() / '.dsh' / 'sessions'
ERR_PREVIEW = 120


def scan(days: int = 7, tool: str | None = None) -> dict:
    files = sorted(SESS_ROOT.glob('*/session-*/session.v4.jsonl.zstd'))
    cutoff = datetime.now().timestamp() - days * 86400

    call_name: dict[str, str] = {}
    errors: list[dict] = []
    scanned, fails = 0, []

    for f in files:
        try:
            if f.stat().st_mtime < cutoff:
                continue
            scanned += 1
            with open(f, 'rb') as fh:
                r = zstd.ZstdDecompressor().stream_reader(fh)
                for line in io.TextIOWrapper(r, encoding='utf-8'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    t = rec.get('time', 0) or 0
                    if t > 1e11:
                        t = t / 1000.0
                    if t and t < cutoff:
                        continue
                    typ = rec.get('type')
                    data = rec.get('data') or {}
                    if typ == 'tool/call':
                        cid = data.get('callId')
                        if cid:
                            call_name[cid] = data.get('name') or '?'
                        continue
                    if typ != 'tool/result':
                        continue
                    msg = data.get('message') or {}
                    if not msg.get('isError'):
                        continue
                    name = call_name.get(msg.get('toolCallId') or '', '?')
                    if tool and name != tool:
                        continue
                    text = ''
                    for part in (msg.get('content') or []):
                        if part.get('type') == 'text':
                            text += part.get('text') or ''
                    text = ' '.join(text.split())
                    try:
                        d = datetime.fromtimestamp(t).strftime('%m-%d %H:%M')
                    except Exception:
                        d = '??-??'
                    errors.append({'tool': name, 'when': d, 'text': text})
        except Exception as e:
            fails.append(f'{f.parent.name[:8]}: {type(e).__name__}: {e}')

    return {'scanned': scanned, 'errors': errors, 'fails': fails}


def main() -> None:
    ap = argparse.ArgumentParser(description='按工具聚合报错原文')
    ap.add_argument('--days', type=int, default=7, help='最近几天，默认 7')
    ap.add_argument('--tool', default=None, help='只看某个工具的错误原文')
    ap.add_argument('--top', type=int, default=20, help='每个工具列前几条原文，默认 20')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    r = scan(a.days, a.tool)
    errs = r['errors']

    if a.json:
        print(json.dumps({'scanned': r['scanned'], 'total': len(errs),
                          'by_tool': dict(Counter(e['tool'] for e in errs)),
                          'errors': errs}, ensure_ascii=False, indent=2))
        return

    if not errs:
        print(f'最近 {a.days} 天没有工具报错（扫了 {r["scanned"]} 个会话）')
        return

    print(f'[ERRORS] 最近 {a.days} 天 · {r["scanned"]} 个会话 · 报错 {len(errs)} 条')
    print()

    if a.tool:
        print(f'  {a.tool} 的报错原文（前 {a.top} 条）:')
        seen = Counter()
        for e in errs[:a.top]:
            seen[e['text'][:ERR_PREVIEW]] += 1
        for text, n in seen.most_common():
            print(f'    ×{n}  {text[:ERR_PREVIEW]}')
        return

    by_tool = Counter(e['tool'] for e in errs)
    print('  按工具:')
    for name, n in by_tool.most_common():
        print(f'    {name:<24} {n:>4} 条')
    print()
    print('  各工具最常见的错误原文（前 2 种）:')
    grouped: dict[str, list[str]] = defaultdict(list)
    for e in errs:
        grouped[e['tool']].append(e['text'])
    for name, _ in by_tool.most_common():
        c = Counter(t[:ERR_PREVIEW] for t in grouped[name])
        print(f'    [{name}]')
        for text, n in c.most_common(2):
            print(f'      ×{n}  {text}')
    print()
    print('  下一步：挑一个工具跑 `lab errors --tool <名字>` 看全部原文，')
    print('  然后自己判断「该改的是用法还是工具」——这个命令不给结论。')

    if r['fails']:
        print()
        print(f'  ⚠️ {len(r["fails"])} 个会话读失败（结果不完整）:')
        for f in r['fails'][:5]:
            print(f'    {f}')

    sys.exit(0)


if __name__ == '__main__':
    main()
