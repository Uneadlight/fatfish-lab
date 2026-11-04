"""清 _scratch 的确定垃圾：.idx / .pyc / __pycache__ / .pytest_cache。

默认 dry-run，加 --apply 才真删。
"""

import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(r'D:\work\备份\_scratch')
APPLY = '--apply' in sys.argv

CLEAN_EXTS = {'.idx', '.pyc', '.pyo'}
CLEAN_DIRS = {'__pycache__', '.pytest_cache', '.mypy_cache'}

files_to_delete = []
dirs_to_delete = []

for f in ROOT.rglob('*'):
    if f.is_file() and f.suffix.lower() in CLEAN_EXTS:
        files_to_delete.append(f)
for d in ROOT.rglob('*'):
    if d.is_dir() and d.name in CLEAN_DIRS:
        dirs_to_delete.append(d)

# 去重：被父目录覆盖的就不单独删
dirs_set = set(dirs_to_delete)
pure_files = [f for f in files_to_delete if not any(p in dirs_set for p in f.parents)]

total_bytes = sum(f.stat().st_size for f in pure_files) + sum(
    sum(x.stat().st_size for x in d.rglob('*') if x.is_file()) for d in dirs_set
)

by_ext = defaultdict(lambda: [0, 0])
for f in pure_files:
    by_ext[f.suffix.lower()][0] += 1
    by_ext[f.suffix.lower()][1] += f.stat().st_size

print(f'{"[APPLY]" if APPLY else "[DRY-RUN]"} _scratch 清理')
print(f'\n文件 {len(pure_files)} 个 + 目录 {len(dirs_set)} 个')
print(f'合计释放：{total_bytes / 1024 / 1024:.2f} MB\n')

print('按扩展名：')
for e, (n, size) in sorted(by_ext.items(), key=lambda x: -x[1][1]):
    print(f'  {e:<10} {n:>4} 个  {size / 1024 / 1024:>9.2f} MB')

print(f'\n要删的目录（{len(dirs_set)} 个）：')
for d in sorted(dirs_set)[:10]:
    n = sum(1 for x in d.rglob('*') if x.is_file())
    print(f'  {d.relative_to(ROOT)}  ({n} 个文件)')
if len(dirs_set) > 10:
    print(f'  ...（还有 {len(dirs_set) - 10} 个）')

if APPLY:
    deleted = 0
    errors = []
    for d in sorted(dirs_set, key=lambda p: -len(p.parts)):
        try:
            shutil.rmtree(d)
            deleted += 1
        except OSError as exc:
            errors.append(f'{d}: {exc}')
    for f in pure_files:
        try:
            f.unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f'{f}: {exc}')
    print(f'\n已删除 {deleted} 项')
    if errors:
        print(f'失败 {len(errors)} 项：')
        for e in errors[:5]:
            print(f'  {e}')
else:
    print('\n（dry-run，没动任何文件。加 --apply 执行）')
