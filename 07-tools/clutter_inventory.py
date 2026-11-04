"""盘点我自己的碎屑：_scratch 和各处临时脚本。只读，不动任何文件。"""

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ZONES = [
    ('_scratch', Path(r'D:\work\备份\_scratch')),
    ('gh-login/_*', Path(r'D:\work\tools\gh-login')),
    ('lab/_*', Path(r'D:\work\tools\lab')),
    ('tools 根下 _*', Path(r'D:\work\tools')),
    ('自进化/_*', Path(r'D:\work\自进化')),
    ('Self-Opt/_*', Path(r'D:\work\Self-Opt')),
]

TODAY = datetime(2026, 11, 2)


def describe(p: Path) -> str:
    """给文件一句人话描述：取首行 docstring 或注释。"""
    if p.suffix.lower() not in {'.py', '.js', '.mjs', '.ps1', '.md', '.txt', '.json', '.cmd', '.bat'}:
        return ''
    try:
        head = p.read_text(encoding='utf-8', errors='ignore')[:400]
    except OSError:
        return ''
    for line in head.splitlines():
        s = line.strip().strip('"\'#/*> ')
        if s and not s.startswith('import') and not s.startswith('from') and not s.startswith('!'):
            return s[:60]
    return ''


total_files = 0
total_bytes = 0

for label, root in ZONES:
    if not root.exists():
        continue
    if label == '_scratch':
        files = [f for f in root.rglob('*') if f.is_file()]
    elif label == 'tools 根下 _*':
        files = [f for f in root.glob('_*') if f.is_file()]
    else:
        files = [f for f in root.glob('_*') if f.is_file()]
        files += [f for f in root.glob('_*.md') if f.is_file()]

    files = sorted(set(files))
    if not files:
        continue

    size = sum(f.stat().st_size for f in files)
    total_files += len(files)
    total_bytes += size

    print(f'\n=== {label}  →  {root} ===')
    print(f'    {len(files)} 个文件 / {size:,} B')

    by_day = defaultdict(int)
    for f in files:
        by_day[datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d')] += 1
    days = sorted(by_day, reverse=True)
    print(f'    按日期：{", ".join(f"{d}({by_day[d]})" for d in days[:6])}')

    today_files = [f for f in files if datetime.fromtimestamp(f.stat().st_mtime) >= TODAY]
    print(f'    今天新建：{len(today_files)} 个')

    for f in files[:14]:
        dt = datetime.fromtimestamp(f.stat().st_mtime)
        desc = describe(f)
        print(f'      {dt:%m-%d %H:%M}  {f.name:<42} {f.stat().st_size:>8,} B  {desc}')
    if len(files) > 14:
        print(f'      ...（还有 {len(files) - 14} 个）')

print(f'\n{"=" * 60}')
print(f'合计：{total_files} 个文件 / {total_bytes:,} B ({total_bytes / 1024 / 1024:.2f} MB)')
