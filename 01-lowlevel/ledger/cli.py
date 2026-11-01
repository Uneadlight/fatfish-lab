"""账本 CLI：记的是**我自己**的 API 花费，不是人类的生活账。

设计取舍：
- 金额一律用**分**（int），不用 float——浮点累加会漂。
- 每条带 `kind`（api / task / manual）和 `tags`，方便按维度汇总。
- 时间默认取当前，`--at` 可补录。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger.store import LedgerError, LedgerStore

# 账本默认落在 `~/.dsh/ledger/`（用 `--file` 或环境变量 `LEDGER_DIR` 可换位置）。
# 不写死机器上的绝对路径：这个仓库是公开的。
DEFAULT_PREFIX = Path(os.environ.get('LEDGER_DIR') or Path.home() / '.dsh' / 'ledger') / 'ledger'


def parse_when(text: str) -> int:
  """`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM` → unix 秒（本地时区）。"""
  text = text.strip()
  for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y/%m/%d'):
    try:
      return int(datetime.strptime(text, fmt).timestamp())
    except ValueError:
      continue
  raise argparse.ArgumentTypeError(f'时间格式看不懂：{text}（要 YYYY-MM-DD 或 YYYY-MM-DD HH:MM）')


def fmt_ts(ts: int) -> str:
  return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def fmt_money(cents: int) -> str:
  sign = '-' if cents < 0 else ''
  value = abs(cents)
  return f'{sign}{value // 100}.{value % 100:02d}'


def cmd_add(store: LedgerStore, args: argparse.Namespace) -> int:
  entry = {
    'ts': args.at if args.at is not None else int(__import__('time').time()),
    'kind': args.kind,
    'amount': args.amount,
    'note': args.note,
    'tags': list(args.tag or []),
  }
  seq = store.append(entry)
  print(f'[OK] seq={seq}  {fmt_ts(entry["ts"])}  {args.kind}  {fmt_money(args.amount)}  {args.note}')
  return 0


def _collect(store: LedgerStore, args: argparse.Namespace) -> list[tuple[int, dict]]:
  rows = list(store.entries())
  if getattr(args, 'since', None) is not None:
    rows = [r for r in rows if r[1]['ts'] >= args.since]
  if getattr(args, 'until', None) is not None:
    rows = [r for r in rows if r[1]['ts'] <= args.until]
  if getattr(args, 'tag', None):
    rows = [r for r in rows if set(args.tag) <= set(r[1].get('tags') or [])]
  if getattr(args, 'kind', None):
    rows = [r for r in rows if r[1].get('kind') == args.kind]
  return rows


def cmd_list(store: LedgerStore, args: argparse.Namespace) -> int:
  rows = _collect(store, args)
  if args.limit:
    rows = rows[-args.limit:]
  if not rows:
    print('（没有符合条件的账目）')
    return 0
  total = 0
  for seq, e in rows:
    total += e['amount']
    tags = (','.join(e.get('tags') or [])) or '-'
    print(f'{seq:>6}  {fmt_ts(e["ts"])}  {e.get("kind", "?"):<7} {fmt_money(e["amount"]):>9}  [{tags}]  {e.get("note", "")}')
  print(f'\n共 {len(rows)} 条，合计 {fmt_money(total)} 元')
  return 0


def cmd_sum(store: LedgerStore, args: argparse.Namespace) -> int:
  rows = _collect(store, args)
  if not rows:
    print('（没有符合条件的账目）')
    return 0
  buckets: dict[str, int] = defaultdict(int)
  for _seq, e in rows:
    ts = e['ts']
    if args.by == 'day':
      key = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    elif args.by == 'month':
      key = datetime.fromtimestamp(ts).strftime('%Y-%m')
    elif args.by == 'kind':
      key = e.get('kind', '?')
    else:  # tag
      tags = e.get('tags') or ['(无标签)']
      for t in tags:
        buckets[t] += e['amount']
      continue
    buckets[key] += e['amount']

  grand = sum(buckets.values())
  width = max(len(k) for k in buckets)
  for key in sorted(buckets):
    print(f'{key:<{width}}  {fmt_money(buckets[key]):>9}')
  print(f'{"合计":<{width}}  {fmt_money(grand):>9}')
  return 0


def cmd_verify(store: LedgerStore, _args: argparse.Namespace) -> int:
  report = store.verify()
  print(f'条目 {report["entries"]} 条，文件 {report["file_bytes"]:,} 字节')
  if report['bad']:
    print(f'[FAIL] {len(report["bad"])} 条读不出来：')
    for item in report['bad']:
      print(f'  seq={item["seq"]} offset={item["offset"]}: {item["error"]}')
    return 1
  if report['orphans']:
    print(f'[WARN] {len(report["orphans"])} 条孤儿帧（有数据没索引），跑 `recover` 收进来')
    return 2
  print('[OK] 全部可读，没有孤儿')
  return 0


def cmd_recover(store: LedgerStore, args: argparse.Namespace) -> int:
  result = store.recover(dry_run=args.dry)
  verb = '可收' if args.dry else '已收'
  print(f'孤儿帧 {result["orphans_found"]} 个，{verb} {result["recovered"]} 条')
  return 0


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(prog='ledger', description='本地账本（防断电丢账）')
  p.add_argument('--file', default=str(DEFAULT_PREFIX), help='账本前缀（默认 %(default)s）')
  sub = p.add_subparsers(dest='cmd', required=True)

  a = sub.add_parser('add', help='记一笔')
  a.add_argument('--amount', type=int, required=True, help='金额（分；支出为正、退款为负）')
  a.add_argument('--note', required=True)
  a.add_argument('--kind', default='manual', choices=['api', 'task', 'manual'])
  a.add_argument('--tag', action='append')
  a.add_argument('--at', type=parse_when)

  ls = sub.add_parser('list', help='列账')
  ls.add_argument('--since', type=parse_when)
  ls.add_argument('--until', type=parse_when)
  ls.add_argument('--tag', action='append')
  ls.add_argument('--kind', choices=['api', 'task', 'manual'])
  ls.add_argument('--limit', type=int, default=0)

  s = sub.add_parser('sum', help='汇总')
  s.add_argument('--by', default='day', choices=['day', 'month', 'kind', 'tag'])
  s.add_argument('--since', type=parse_when)
  s.add_argument('--until', type=parse_when)
  s.add_argument('--tag', action='append')
  s.add_argument('--kind', choices=['api', 'task', 'manual'])

  sub.add_parser('verify', help='校验 CRC 与索引一致性')

  r = sub.add_parser('recover', help='把孤儿帧收进索引')
  r.add_argument('--dry', action='store_true')

  return p


def main(argv: list[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  try:
    store = LedgerStore(args.file)
  except (LedgerError, OSError) as exc:
    print(f'[FAIL:执行失败] 打不开账本：{exc}')
    return 1
  handlers = {
    'add': cmd_add,
    'list': cmd_list,
    'sum': cmd_sum,
    'verify': cmd_verify,
    'recover': cmd_recover,
  }
  try:
    return handlers[args.cmd](store, args)
  finally:
    store.close()


if __name__ == '__main__':
  sys.exit(main())
