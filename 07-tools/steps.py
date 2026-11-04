"""lab steps —— 会话的时间轴能不能拼起来。

起因（本质问题 P5「我在同一个坑里反复掉，但不知道当时是怎么走的」）：
想复盘"这一轮做了什么、按什么顺序"，结果发现 agent 级消息里大量没有 turn/step 归属。

判据只一条：**agent 级 assistant/message 有没有 turn/step**。
有 → 能拼出时间轴；没有 → 只能按文件顺序猜。

用法：
    py steps.py                 # 最近 7 天
    py steps.py --days 1
    py steps.py --verify        # 额外列出带数字的验证记录（rc=0/rc=1）
    py steps.py --json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import zstandard as zstd

SESS_ROOT = Path.home() / '.dsh' / 'sessions'


def _unzstd(path: Path):
    with open(path, 'rb') as fh:
        r = zstd.ZstdDecompressor().stream_reader(fh)
        yield from io.TextIOWrapper(r, encoding='utf-8')


def collect(days: float = 7.0, verify: bool = False) -> dict:
    cutoff = time.time() - days * 86400
    agent_msgs = 0
    with_step = 0
    without_step = 0
    examples_missing: list[str] = []
    verify_rows: list[dict] = []
    scanned = 0
    errors: list[str] = []

    for sf in sorted(SESS_ROOT.glob('*/session-*/session.v4.jsonl.zstd')):
        try:
            if sf.stat().st_mtime < cutoff:
                continue
            scanned += 1
            for line in _unzstd(sf):
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

                # 只看 assistant/message 有没有 turn/step。
                # 原来想用「directory 里含 agent」区分 agent 级和 session 级，
                # 实测 2026-11-04：5,833 条 assistant/message 的 data.directory 和
                # rec.directory 全是空字符串——这个判据根本不存在。
                # 换成最朴素的一条：**有 turn/step 就能拼时间轴，没有就只能按文件顺序猜**。
                if typ == 'assistant/message':
                    agent_msgs += 1
                    has = data.get('turn') is not None or data.get('step') is not None
                    if has:
                        with_step += 1
                    else:
                        without_step += 1
                        if len(examples_missing) < 5:
                            msg = data.get('message') or {}
                            txt = ''
                            for part in (msg.get('content') or []):
                                if part.get('type') == 'text':
                                    txt = (part.get('text') or '').strip()
                                    break
                            if txt:
                                examples_missing.append(txt[:70])

                # 验证记录：tool/result 里有 rc=0 / rc=1 这类
                if verify and typ == 'tool/result':
                    msg = data.get('message') or {}
                    for part in (msg.get('content') or []):
                        if part.get('type') != 'text':
                            continue
                        txt = part.get('text') or ''
                        import re as _re
                        m = _re.search(r'\brc=(\d+)', txt)
                        if m:
                            verify_rows.append({
                                'rc': int(m.group(1)),
                                'ok': data.get('isError') is not True,
                                'snippet': txt[:80].replace('\n', ' '),
                            })
        except Exception as e:
            errors.append(f'{sf.parent.name}: {e}')

    return {
        'scanned': scanned,
        'agent_msgs': agent_msgs,
        'with_step': with_step,
        'without_step': without_step,
        'ratio': round(with_step / agent_msgs, 3) if agent_msgs else None,
        'examples_missing': examples_missing,
        'verify': verify_rows,
        'errors': errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=float, default=7.0)
    ap.add_argument('--verify', action='store_true', help='额外统计带 rc= 的验证记录')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    d = collect(a.days, a.verify)

    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    print(f'[STEPS] 最近 {a.days:g} 天 · 扫了 {d["scanned"]} 个会话')
    if d['agent_msgs'] == 0:
        print('  没有 assistant 消息')
        return 0

    print(f'  assistant 消息 {d["agent_msgs"]} 条')
    print(f'    有 turn/step : {d["with_step"]} 条（{d["ratio"]:.1%}）')
    print(f'    缺 turn/step : {d["without_step"]} 条（{1 - d["ratio"]:.1%}）')

    if d['examples_missing']:
        print('\n  缺归属的例子（前 5 条，只能按文件顺序猜位置）：')
        for e in d['examples_missing']:
            print(f'    - {e}')

    if a.verify:
        rows = d['verify']
        ok = sum(1 for r in rows if r['rc'] == 0)
        bad = sum(1 for r in rows if r['rc'] != 0)
        print(f'\n  带 rc= 的验证记录 {len(rows)} 条：PASS {ok} / FAIL {bad}')
        for r in rows[:8]:
            mark = '✅' if r['rc'] == 0 else '❌'
            print(f'    {mark} rc={r["rc"]}  {r["snippet"]}')

    if d['errors']:
        print(f'\n  ⚠️ {len(d["errors"])} 个会话读失败（前 3）：')
        for e in d['errors'][:3]:
            print(f'    {e}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
