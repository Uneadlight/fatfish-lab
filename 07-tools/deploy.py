"""改完自研插件，同步到 profile 并验证。

解决两个反复踩的坑（本质问题清单里的 P12 和 P14）：
- P12「一遍遍做手工活」：改完要手动 Copy-Item 到 profile，今天踩两次
- P14「改完没确认生效」：今天两次「以为重启了其实没有」

判定规则（2026-11-04 实测）：
- `SymbolicLink` 的插件改源码就生效，**不用同步**（env-doctor / vision / memory）
- **实体目录**的插件是拷贝，改完必须同步（evolve / workflow-skill / worktree-tool /
  open-design-mcp / stickers / chat-background）

用法：
  py lab.py deploy dsh-evolve          # 同步并验证
  py lab.py deploy dsh-evolve --check  # 只比，不同步
  py lab.py deploy --all               # 所有实体目录的插件（软链的跳过）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(r'D:\work')
PROFILE_NM = Path(r'~/.dsh\profiles\desktop\node_modules')

# 插件名 → 源码目录。`@local/X` 映射到 `D:\work\X`，顶层包名同名。
SELF_BUILT = [
    '@local/dsh-env-doctor',
    '@local/dsh-evolve',
    '@local/dsh-vision',
    '@local/dsh-workflow-skill',
    '@local/dsh-worktree-tool',
    '@local/open-design-mcp',
    'dsh-memory',
    'dsh-stickers',
    'dsh-chat-background',
]

# 不同步的东西：体积大 + 不影响运行
IGNORE = shutil.ignore_patterns(
    'node_modules', '.git', '__pycache__', '*.pyc', '*.log', '.venv', 'venv',
    '.pytest_cache', 'dist', 'build',
)


def src_dir(name: str) -> Path:
    base = name.split('/')[-1]
    # 特例：open-design-mcp 的源码目录叫 open-design-dsh-bundle（2026-11-04 实测，
    # 名字对不上所以之前一直报「源码目录不存在」）
    if base == 'open-design-mcp':
        alt = ROOT / 'open-design-dsh-bundle'
        if alt.is_dir():
            return alt
    return ROOT / base


def dst_dir(name: str) -> Path:
    return PROFILE_NM / name.replace('/', '\\')


def link_type(p: Path) -> str:
    if not p.exists():
        return 'missing'
    item = p.lstat()
    # Windows 上 junction/symlink 都是 reparse point
    if item.st_file_attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        return 'link'
    return 'copy'


def tree_hash(p: Path) -> dict[str, str]:
    """对目录里每个文件算 sha256（跳过 IGNORE）。返回 {相对路径: 哈希}。"""
    out: dict[str, str] = {}
    if not p.is_dir():
        return out
    skip_dirs = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.pytest_cache', 'dist', 'build'}
    for f in p.rglob('*'):
        if not f.is_file():
            continue
        rel = f.relative_to(p)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if f.suffix in ('.pyc', '.log') or '.bak' in f.name:
            continue
        try:
            out[str(rel).replace('\\', '/')] = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        except OSError:
            pass
    return out


def compare(name: str) -> dict:
    """比源码和 profile 的差异。"""
    s, d = src_dir(name), dst_dir(name)
    st = link_type(d)
    result = {'name': name, 'kind': st, 'src': str(s), 'dst': str(d)}

    if not s.is_dir():
        result['error'] = f'源码目录不存在: {s}'
        return result
    if st == 'missing':
        result['error'] = 'profile 里没装'
        return result
    if st == 'link':
        result['note'] = '软链，改源码即生效，不用同步'
        return result

    hs, hd = tree_hash(s), tree_hash(d)
    only_src = sorted(set(hs) - set(hd))
    only_dst = sorted(set(hd) - set(hs))
    diff = sorted(k for k in (set(hs) & set(hd)) if hs[k] != hd[k])
    result.update({
        'only_src': only_src,
        'only_dst': only_dst,
        'diff': diff,
        'same': len(set(hs) & set(hd)) - len(diff),
        'in_sync': not only_src and not only_dst and not diff,
    })
    return result


def sync(name: str) -> dict:
    """单向同步：源码 → profile（只增改，不删 profile 独有的文件）。"""
    s, d = src_dir(name), dst_dir(name)
    if link_type(d) != 'copy':
        return {'name': name, 'skipped': True}
    if not s.is_dir():
        return {'name': name, 'error': f'源码目录不存在: {s}'}

    copied = 0
    for f in s.rglob('*'):
        if not f.is_file():
            continue
        rel = f.relative_to(s)
        skip_dirs = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.pytest_cache', 'dist', 'build'}
        if any(part in skip_dirs for part in rel.parts):
            continue
        if f.suffix in ('.pyc', '.log') or '.bak' in f.name:
            continue
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        copied += 1
    return {'name': name, 'copied': copied}


def restart_hint(name: str) -> str:
    """判断「改完要不要重启」。进程没重启时，改了文件也没生效。"""
    d = dst_dir(name)
    if not d.is_dir():
        return ''
    newest = max((f.stat().st_mtime for f in d.rglob('*') if f.is_file()), default=0)
    # 找当前 DSH 主进程的启动时间（拿个近似：用 python 进程不行，用文件时间对比）
    # 这里只能给「最后修改」和「现在」的差，具体要不要重启由调用者判断
    age_min = (time.time() - newest) / 60 if newest else 0
    if age_min < 5:
        return f'⚠️  文件 {age_min:.0f} 分钟前刚改过——**必须重启 DSH 才生效**'
    return ''


def cmd_deploy(names: list[str], check: bool) -> int:
    print(f'{"=== 只检查 ===" if check else "=== 同步 ==="}')
    print()
    total_bad = 0
    for name in names:
        s = src_dir(name)
        d = dst_dir(name)
        kind = link_type(d)

        if kind == 'link':
            print(f'✅ {name:<30} 软链 → 改源码即生效')
            continue
        if kind == 'missing':
            print(f'❌ {name:<30} profile 里没装')
            total_bad += 1
            continue
        if not s.is_dir():
            print(f'❌ {name:<30} 源码目录不存在：{s}')
            total_bad += 1
            continue

        before = compare(name)
        if before.get('in_sync'):
            print(f'✅ {name:<30} 已同步（{before["same"]} 个文件一致）')
            continue

        total_bad += 1
        if check:
            n = len(before.get('only_src', [])) + len(before.get('diff', [])) + len(before.get('only_dst', []))
            print(f'⚠️  {name:<30} {n} 个文件不一致')
            for k in before.get('only_src', [])[:5]:
                print(f'      仅源码有: {k}')
            for k in before.get('diff', [])[:5]:
                print(f'      内容不同: {k}')
            for k in before.get('only_dst', [])[:5]:
                print(f'      仅 profile 有: {k}')
            continue

        # 同步前先备份 profile 那一份
        bak = d.parent / f'{d.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
        try:
            shutil.copytree(d, bak)
            print(f'   备份 → {bak.name}')
        except OSError as e:
            print(f'   ⚠️ 备份失败（不影响同步）：{e}')
        r = sync(name)
        after = compare(name)
        if after.get('in_sync'):
            print(f'✅ {name:<30} 已同步（复制 {r.get("copied", 0)} 个文件，{after["same"]} 个一致）')
            total_bad -= 1
        else:
            print(f'❌ {name:<30} 同步后仍不一致')
        hint = restart_hint(name)
        if hint:
            print(f'   {hint}')

    print()
    if check:
        print(f'共 {total_bad} 个需要同步' if total_bad else '全部已同步')
    else:
        print('全部就绪' if not total_bad else f'{total_bad} 个仍有问题')
    return 1 if total_bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='改完自研插件，同步到 profile 并验证')
    ap.add_argument('names', nargs='*', help='插件名，如 dsh-evolve 或 @local/dsh-evolve')
    ap.add_argument('--all', action='store_true', help='全部自研插件')
    ap.add_argument('--check', action='store_true', help='只比，不同步')
    a = ap.parse_args(argv)

    if a.all:
        names = SELF_BUILT
    elif a.names:
        names = a.names
    else:
        ap.print_usage()
        return 2
    return cmd_deploy(names, a.check)


if __name__ == '__main__':
    sys.exit(main())
