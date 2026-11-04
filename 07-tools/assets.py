#!/usr/bin/env python
"""能力痕迹自动盘点：把工作区顶层资产扫一遍，每项给一句**从磁盘证据推出来**的判断。

为什么要有这个：2026-11-04 一天内两次「我有但忘了」——`ops_discover_tools` 排在
零使用清单里、`.edge-debug`（494 MB 浏览器档案）就躺在工作区根目录却没看见。
根因不是记性，是**能力地图靠手写文档，而文档会过期、磁盘不会**。

判据全部可复算：
  大小     递归累加（超时标 >Ns 未算完，不猜）
  最后修改 目录自身 mtime + 其下最深一层文件的 mtime，取大者
  说明     顶层有 README*.md / INDEX.md 之类
  版本     .git 存在
  引用     在 架构文档/ 与 自进化/ 的 *.md 里出现几次（-1 = 文件太多没扫完）

用法：
  py assets.py                # 人读表格
  py assets.py --json         # 给 lab tier 用
  py assets.py --top 10       # 只看最大的 10 个
  py assets.py --name cache   # 只看名字含 cache 的
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(r'D:\work')

# 算大小时跳过这些（它们让体积失真且不影响「这是什么」的判断）
SIZE_SKIP = frozenset({'node_modules', '.git', '.venv', 'venv', '__pycache__', '.pnpm'})

DOC_NAMES = ('readme.md', 'readme.txt', 'index.md', 'readme', '说明.md')
DOC_SUFFIX = ('.md',)

# 引用的扫描范围：只扫这几个目录里的 md，便宜且覆盖「被记录过」这个语义
REF_DIRS = ('架构文档', '自进化', '工具', 'tools')
REF_MAX_FILES = 400


def human(n: int | None) -> str:
  if n is None:
    return '—'
  f = float(n)
  for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
    if f < 1024 or unit == 'TB':
      return f'{f:,.0f} {unit}' if unit == 'B' else f'{f:,.1f} {unit}'
    f /= 1024
  return f'{f:,.1f} TB'


def dir_size(path: Path, deadline: float) -> int | None:
  """递归累加文件大小；超过 deadline 返回 None（不猜、不估）。"""
  total = 0
  stack = [str(path)]
  while stack:
    if time.monotonic() > deadline:
      return None
    d = stack.pop()
    try:
      with os.scandir(d) as it:
        for e in it:
          try:
            if e.is_dir(follow_symlinks=False):
              if e.name in SIZE_SKIP:
                continue
              stack.append(e.path)
            elif e.is_file(follow_symlinks=False):
              total += e.stat(follow_symlinks=False).st_size
          except OSError:
            continue
    except OSError:
      continue
  return total


def newest_mtime(path: Path, deadline: float) -> float:
  """目录自身 mtime 与最深一层文件 mtime 取大者（目录 mtime 只反映直接子项增删）。"""
  best = 0.0
  try:
    best = path.stat().st_mtime
  except OSError:
    pass
  stack = [str(path)]
  while stack:
    if time.monotonic() > deadline:
      break
    d = stack.pop()
    try:
      with os.scandir(d) as it:
        for e in it:
          try:
            if e.is_dir(follow_symlinks=False):
              if e.name in SIZE_SKIP:
                continue
              stack.append(e.path)
            elif e.is_file(follow_symlinks=False):
              m = e.stat(follow_symlinks=False).st_mtime
              if m > best:
                best = m
          except OSError:
            continue
    except OSError:
      continue
  return best


def has_doc(path: Path) -> str:
  """返回说明文件相对路径（顶层优先，再看一层子目录），没有则空串。"""
  try:
    for e in os.scandir(path):
      if e.is_file() and e.name.lower() in DOC_NAMES:
        return e.name
  except OSError:
    return ''
  # 一层子目录：tools/lab/README.md 这种也算「这个目录有说明」
  try:
    for e in os.scandir(path):
      if not e.is_dir(follow_symlinks=False) or e.name in SIZE_SKIP:
        continue
      try:
        for f in os.scandir(e.path):
          if f.is_file() and f.name.lower() in DOC_NAMES:
            return f'{e.name}/{f.name}'
      except OSError:
        continue
  except OSError:
    pass
  # 顶层任意 .md 也算：一个目录里只要有给人看的文字，就不该判「无任何记录」
  try:
    for e in os.scandir(path):
      if e.is_file() and e.name.lower().endswith('.md'):
        return e.name
  except OSError:
    pass
  return ''


def is_git(path: Path) -> bool:
  return (path / '.git').exists()


def collect_refs() -> tuple[dict[str, int], int]:
  """在 REF_DIRS 的 md 里数每个目录名出现几次。返回 (计数表, 扫了多少文件)。"""
  counts: dict[str, int] = {}
  files = 0
  for name in REF_DIRS:
    base = ROOT / name
    if not base.is_dir():
      continue
    for dirpath, dirnames, filenames in os.walk(base):
      dirnames[:] = [d for d in dirnames if d not in SIZE_SKIP]
      for fn in filenames:
        if not fn.lower().endswith(DOC_SUFFIX):
          continue
        if files >= REF_MAX_FILES:
          return counts, files
        files += 1
        try:
          text = (Path(dirpath) / fn).read_text('utf-8', errors='replace')
        except OSError:
          continue
        for hit in re.findall(r'[\w.\-]{2,64}', text):
          counts[hit] = counts.get(hit, 0) + 1
  return counts, files


def judge(name: str, size: int | None, mtime: float, doc: str, git: bool, refs: int, now: float) -> str:
  """一句话判断：只用能复算的事实 + 名字自带语义，不做主观评价。"""
  age_days = (now - mtime) / 86400 if mtime else 9999
  recent = age_days < 30
  low = name.lower()
  # 名字自带语义的先判（备份/缓存/隐藏目录不是「未知资产」）
  if '备份' in name or low.startswith('backup'):
    return f'备份（{human(size)}，不是活跃资产）'
  if low in ('cache', '.cache') or low.endswith('-cache'):
    return f'缓存（{human(size)}，可重建）'
  if low.startswith('.'):
    return f'隐藏目录（{human(size)}，工具/配置数据）'
  if doc and git and recent:
    return f'活跃（说明={doc}，有版本控制，{age_days:.0f} 天前动过）'
  if doc and git:
    return f'停用（说明={doc}，有版本控制，{age_days:.0f} 天没动）'
  if doc and recent:
    return f'在用（说明={doc}，{age_days:.0f} 天前动过）'
  if doc:
    return f'停用（说明={doc}，{age_days:.0f} 天没动）'
  if git:
    return '代码库但顶层无说明文件'
  if size is None:
    return '体积未算完（超时），无说明无版本控制'
  if size >= 100 * 1024 * 1024:
    return f'大块无说明资产（{human(size)}，无文档无版本控制，{age_days:.0f} 天没动）'
  if refs > 0:
    return f'小件但被文档提过 {refs} 次'
  return '小件且无任何记录'


def scan(deadline_per_dir: float) -> tuple[list[dict], int]:
  now = time.time()
  refs, ref_files = collect_refs()
  rows: list[dict] = []
  for entry in sorted(os.scandir(ROOT), key=lambda e: e.name.lower()):
    p = Path(entry.path)
    is_dir = entry.is_dir(follow_symlinks=False)
    dl = time.monotonic() + deadline_per_dir
    size = dir_size(p, dl) if is_dir else entry.stat(follow_symlinks=False).st_size
    dl2 = time.monotonic() + deadline_per_dir
    mtime = newest_mtime(p, dl2) if is_dir else entry.stat(follow_symlinks=False).st_mtime
    doc = has_doc(p) if is_dir else ''
    git = is_git(p) if is_dir else False
    ref = refs.get(entry.name, 0)
    rows.append({
      'name': entry.name,
      'kind': 'dir' if is_dir else 'file',
      'size': size,
      'mtime': mtime,
      'mtime_s': time.strftime('%m-%d %H:%M', time.localtime(mtime)) if mtime else '—',
      'doc': doc,
      'git': git,
      'refs': ref,
      'judge': judge(entry.name, size, mtime, doc, git, ref, now),
    })
  return rows, ref_files


def main() -> int:
  ap = argparse.ArgumentParser(description='能力痕迹自动盘点')
  ap.add_argument('--json', action='store_true', help='输出 JSON')
  ap.add_argument('--top', type=int, default=0, help='只看最大的 N 个')
  ap.add_argument('--name', default=None, help='只看名字含该串的')
  ap.add_argument('--budget', type=float, default=4.0, help='每个目录算大小的秒数上限（默认 4）')
  ap.add_argument('--junk', action='store_true', help='只列「小件且无任何记录」的（清理候选）')
  a = ap.parse_args()

  if not ROOT.is_dir():
    print(f'[ERROR] 工作区不存在: {ROOT}', file=sys.stderr)
    return 2

  t0 = time.monotonic()
  rows, ref_files = scan(a.budget)
  elapsed = time.monotonic() - t0

  if a.name:
    rows = [r for r in rows if a.name.lower() in r['name'].lower()]
  if a.junk:
    rows = [r for r in rows if r['judge'].startswith('小件且无任何记录')]
  if a.top:
    rows.sort(key=lambda r: (r['size'] or 0), reverse=True)
    rows = rows[:a.top]

  if a.json:
    print(json.dumps({
      'root': str(ROOT),
      'scanned_at': time.strftime('%Y-%m-%d %H:%M:%S'),
      'elapsed_s': round(elapsed, 2),
      'ref_files': ref_files,
      'total_items': len(rows),
      'items': rows,
    }, ensure_ascii=False, indent=2))
    return 0

  known = sum(r['size'] for r in rows if r['size'] is not None)
  unknown = sum(1 for r in rows if r['size'] is None)

  print('=' * 108)
  print(f'资产盘点  {ROOT}')
  print(f'{time.strftime("%Y-%m-%d %H:%M:%S")}   {len(rows)} 项   耗时 {elapsed:.2f}s   引用扫描 {ref_files} 个 md')
  print('=' * 108)
  print(f'{"目录":<26} {"大小":>10}  {"最后修改":<12} {"文档":<4} {"版本":<4} {"引用":>4}  判断')
  print('-' * 108)
  for r in rows:
    print(f'{r["name"][:25]:<26} {human(r["size"]):>10}  {r["mtime_s"]:<12} '
          f'{"✅" if r["doc"] else "·":<4} {"✅" if r["git"] else "·":<4} {r["refs"]:>4}  {r["judge"]}')

  print('-' * 108)
  # 分类按语义归并：judge 的具体数字（如「提过 19 次」）不该各成一桶
  buckets: dict[str, int] = {}
  for r in rows:
    j = r['judge']
    if j.startswith('小件但被文档提过'):
      key = '小件·被文档引用'
    elif j.startswith('小件且无任何记录'):
      key = '小件·无任何记录'
    elif j.startswith('小件'):
      key = '小件·其他'
    elif j.startswith('大块无说明资产'):
      key = '大块·无说明'
    else:
      key = j.split('（')[0].split('，')[0]
    buckets[key] = buckets.get(key, 0) + 1
  print(f'已算体积合计 {human(known)}' + (f'，另有 {unknown} 项超时未算完' if unknown else ''))
  print('分类：' + ' / '.join(f'{k} {v}' for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
