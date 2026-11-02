"""DSH 配置备份（不含 secrets）。

起因：社区插件 `dsh-config-manager`（65,391 行）干的就是这件事，而我一直在手工 Copy-Item。
不装它（1,686 个文件 / 25 MB / 要重启），只吸收它的三条思路：
  ① 白名单式备份（明确列出要备份什么，不是整个 ~/.dsh 打包）
  ② **secrets 永不进备份**，但要在清单里记下「排除了哪几个」，让人知道少了什么
  ③ 每次备份生成 manifest（sha256），恢复时能验完整性

用法:
  py config_backup.py            # 备份到 <备份根>/config-YYYYMMDD-HHMMSS
  py config_backup.py --dry      # 只看会备份什么
  py config_backup.py --list     # 列出已有备份
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

DSH_HOME = Path(r'~/.dsh')
BACKUP_ROOT = Path(r'D:\work\备份')

# 白名单：明确要备份的东西（配置性质，不含会话/缓存/运行时）
ITEMS: list[tuple[str, str, list[str] | None]] = [
    ('dsh-startup.json', 'file', None),
    ('pet.json', 'file', None),
    ('skin-center-active.json', 'file', None),
    ('dsh-chat-background.json', 'file', None),
    ('ghctl-default.txt', 'file', None),
    ('memory', 'dir', None),            # memories.json —— 最重要的一个
    ('ledger', 'dir', None),            # 账本
    ('task-board', 'dir', None),
    ('dsh-usage', 'dir', None),
    ('storages', 'dir', None),
    ('skills', 'dir', None),
    ('session-index', 'dir', None),     # 可重建，但重建要跑一遍
    # profile 只取配置文件，不取 node_modules
    ('profiles/desktop', 'dir', [
        'cordis.yml', 'cordis.patch.yml', 'manifest.json',
        'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml',
    ]),
]

# 明确排除的 secrets（只记名字，绝不拷内容）
SECRETS = [
    '.credentials.yaml',
    'github-token.txt',
    'dsh-vision-key.txt',
    'dsh-pocket/token',
    'dsh-pocket/token-lan',
]

# 明确排除的大件（说明为什么排除，不是忘了）
EXCLUDED_DIRS = {
    'sessions': '会话记录（48 MB，另有 sessions-deleted 备份）',
    'attachments': '附件（95 MB）',
    'cache': '缓存（可重建）',
    'dsh-ops': 'bash 工具链（411 MB，可重装）',
    'dsh-runtimes': '运行时（539 MB，可重装）',
    'speech-to-text': '语音模型（241 MB，可重下）',
    'dsh-chat-background': '聊天背景图（309 MB）',
    'profiles/*/node_modules': '依赖（用 pnpm-lock.yaml 重装）',
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def collect() -> list[tuple[Path, str]]:
    """返回 [(源绝对路径, 备份内相对路径)]。"""
    out: list[tuple[Path, str]] = []
    for rel, kind, only in ITEMS:
        src = DSH_HOME / rel
        if not src.exists():
            continue
        if kind == 'file':
            out.append((src, rel))
        else:
            if only:
                for name in only:
                    f = src / name
                    if f.exists():
                        out.append((f, f'{rel}/{name}'))
            else:
                for f in src.rglob('*'):
                    if f.is_file():
                        # 统一用正斜杠：Windows 的 relative_to 给的是反斜杠，
                        # 而 only 分支拼的是正斜杠 —— 两种混用会让 manifest 对不上磁盘。
                        out.append((f, str(f.relative_to(DSH_HOME)).replace('\\', '/')))
    # 再兜底过滤一次 secrets（白名单里万一手滑写进去）+ 排掉历史 .bak 文件
    bad = {str(DSH_HOME / s) for s in SECRETS}
    return [
        (s, r) for s, r in out
        if str(s) not in bad and '.bak-' not in s.name and '.bak-' not in r
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description='DSH 配置备份（不含 secrets）')
    ap.add_argument('--dry', action='store_true', help='只列出会备份什么')
    ap.add_argument('--list', action='store_true', help='列出已有备份')
    ap.add_argument('--keep', type=int, default=10, help='保留最近 N 份，默认 10')
    a = ap.parse_args()

    if a.list:
        dirs = sorted(BACKUP_ROOT.glob('config-*'), reverse=True)
        if not dirs:
            print('（还没有备份）')
            return 0
        for d in dirs[:a.keep]:
            mf = d / 'manifest.json'
            n = size = 0
            if mf.exists():
                m = json.loads(mf.read_text(encoding='utf-8'))
                n = len(m.get('files', []))
                size = m.get('total_bytes', 0)
            print(f'  {d.name}   {n:4} 个文件   {size/1048576:7.2f} MB')
        return 0

    files = collect()
    total = sum(s.stat().st_size for s, _ in files)
    print(f'待备份 {len(files)} 个文件，共 {total/1048576:.2f} MB')
    print(f'  来源: {DSH_HOME}')
    print(f'  排除的 secrets: {len(SECRETS)} 个（只记名字，不拷内容）')
    for s in SECRETS:
        print(f'    ✗ {s}')
    print(f'  排除的大件: {len(EXCLUDED_DIRS)} 个')
    for k, why in EXCLUDED_DIRS.items():
        print(f'    ✗ {k:28} {why}')

    if a.dry:
        print('\n--- 文件清单 ---')
        for s, r in files:
            print(f'  {r}  ({s.stat().st_size:,} B)')
        return 0

    stamp = time.strftime('%Y%m%d-%H%M%S')
    dest = BACKUP_ROOT / f'config-{stamp}'
    dest.mkdir(parents=True, exist_ok=False)

    entries = []
    for src, rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        entries.append({
            'path': rel,
            'bytes': src.stat().st_size,
            'sha256': sha256(src),
        })

    manifest = {
        'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': str(DSH_HOME),
        'files': entries,
        'total_bytes': total,
        'excluded_secrets': SECRETS,
        'excluded_dirs': EXCLUDED_DIRS,
    }
    (dest / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8'
    )

    # 回读校验：manifest 能解析 + 文件数对得上（"写了"≠"写对了"）
    check = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
    if len(check['files']) != len(files):
        print(f'[FAIL:执行失败] manifest 文件数 {len(check["files"])} != 实际 {len(files)}', file=sys.stderr)
        return 2

    print(f'\n[OK] 备份完成 -> {dest}')
    print(f'     {len(entries)} 个文件 / {total/1048576:.2f} MB / manifest 已回读校验')

    # 轮转：只留最近 N 份
    dirs = sorted(BACKUP_ROOT.glob('config-*'), reverse=True)
    for old in dirs[a.keep:]:
        print(f'     轮转删除旧备份: {old.name}')
        shutil.rmtree(old, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
