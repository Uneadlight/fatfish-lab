"""文件快照：改文件前存一份，改坏了能退回来。

抄自 `dsh-local-devkit` 的 `CheckpointStore`（`src/checkpoint/store.mjs`），
但那个是插件（挂 `tools/execute` 钩子，`write`/`edit` 前自动快照）；
这里是 CLI —— 我拿不到 hook，只能手动拍。

布局：`<DSH_HOME>/devkit/checkpoints/<projectHash>/<ts>-<seq>-<rand>.{json,bin}`
- `.json` 存元数据（id / tool / path / cwd / reason / createdAt / existed / size / skipped / consumed）
- `.bin`  存拍那一刻的原始字节
- `existed: false` 表示**拍快照时这个文件还不存在** → 恢复时是「删除」而不是「写回」

三个关键设计（都是原文里的，不是我加的理解）：
1. `projectKey(cwd)` = sha1(规范化 cwd) 前 12 位 —— 按工作目录隔离，不同项目不会串
2. `isInsideStore` —— 拍快照时跳过自己的目录，否则会递归
3. `restore` 前先 `capture(reason='pre-restore')` —— **恢复本身也可撤销**

用法：
    py snapshot.py now <path>             # 改文件前手动拍
    py snapshot.py list [--path P]        # 列快照（默认 20 条）
    py snapshot.py restore <id>           # 恢复到某条
    py snapshot.py undo <path>            # 回退到这条路径的上一次（可连续调用 v3→v2→v1）
"""

import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

DSH_HOME = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh'))
ROOT = DSH_HOME / 'devkit' / 'checkpoints'
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 500

_seq = 0


def next_seq():
    global _seq
    _seq = (_seq + 1) % 100000
    return _seq


def normalize(p):
    r = str(Path(p).resolve())
    return r.lower() if os.name == 'nt' else r


def project_key(cwd):
    return hashlib.sha1(normalize(cwd).encode('utf-8')).hexdigest()[:12]


def dir_for(cwd):
    return ROOT / project_key(cwd)


def is_inside_store(target):
    store = normalize(ROOT)
    resolved = normalize(target)
    return resolved == store or resolved.startswith(store + os.sep)


def prune(d):
    metas = sorted(d.glob('*.json'))
    if len(metas) <= MAX_ENTRIES:
        return
    for old in metas[:len(metas) - MAX_ENTRIES]:
        old.unlink(missing_ok=True)
        old.with_suffix('.bin').unlink(missing_ok=True)


def capture(path, tool='manual', cwd=None, reason='pre-edit'):
    target = Path(path).resolve()
    if is_inside_store(target):
        return None
    cwd = cwd or os.getcwd()
    d = dir_for(cwd)
    d.mkdir(parents=True, exist_ok=True)
    cid = '%d-%05d-%s' % (int(time.time() * 1000), next_seq(), random.randbytes(2).hex())
    meta_file = d / ('%s.json' % cid)
    blob_file = d / ('%s.bin' % cid)

    existed = target.is_file()
    meta = {
        'id': cid, 'tool': tool, 'path': str(target),
        'cwd': str(Path(cwd).resolve()), 'reason': reason,
        'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'existed': existed, 'size': 0, 'skipped': None,
    }
    if existed:
        size = target.stat().st_size
        meta['size'] = size
        if size > MAX_FILE_BYTES:
            meta['skipped'] = 'too-large'
        else:
            blob_file.write_bytes(target.read_bytes())
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    prune(d)
    return meta


def list_entries(cwd=None, path=None, limit=20):
    d = dir_for(cwd or os.getcwd())
    if not d.is_dir():
        return []
    wanted = normalize(path) if path else None
    out = []
    for mf in d.glob('*.json'):
        try:
            meta = json.loads(mf.read_text(encoding='utf-8'))
        except Exception:
            continue
        if wanted and normalize(meta.get('path', '')) != wanted:
            continue
        out.append(meta)
    out.sort(key=lambda m: str(m.get('id', '')), reverse=True)
    return out[:limit]


def restore(cid, cwd=None):
    cwd = cwd or os.getcwd()
    d = dir_for(cwd)
    meta_file = d / ('%s.json' % cid)
    if not meta_file.is_file():
        raise SystemExit('找不到快照 %s（项目 %s）' % (cid, Path(cwd).resolve()))
    meta = json.loads(meta_file.read_text(encoding='utf-8'))

    # 恢复前先记录当前状态，使「恢复」本身也可撤销
    capture(meta['path'], tool='snapshot_restore', cwd=cwd, reason='pre-restore')
    meta['consumed'] = True
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')

    target = Path(meta['path'])
    if meta.get('existed') is False:
        target.unlink(missing_ok=True)
        return {'ok': True, 'path': str(target), 'action': 'removed', 'id': cid}

    blob = d / ('%s.bin' % cid)
    if not blob.is_file():
        raise SystemExit('快照 %s 的内容文件已丢失' % cid)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob.read_bytes())
    return {'ok': True, 'path': str(target), 'action': 'restored',
            'bytes': blob.stat().st_size, 'id': cid}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    cmd = args[0]

    if cmd == 'now':
        if len(args) < 2:
            print('用法: snapshot.py now <path>', file=sys.stderr)
            return 2
        meta = capture(args[1], tool='manual', reason='pre-edit')
        if meta is None:
            print('跳过了（这是快照目录自己）')
            return 0
        print('已拍快照 %s' % meta['id'])
        print('  path    %s' % meta['path'])
        print('  existed %s' % meta['existed'])
        if meta.get('skipped'):
            print('  注意    %s' % meta['skipped'])
        return 0

    if cmd == 'list':
        path = None
        limit = 20
        if '--path' in args:
            path = args[args.index('--path') + 1]
        if '--limit' in args:
            limit = int(args[args.index('--limit') + 1])
        entries = list_entries(path=path, limit=limit)
        if not entries:
            print('没有快照')
            return 0
        for e in entries:
            mark = ' [已消费]' if e.get('consumed') else ''
            print('%s  %s%s' % (e['id'], e['path'], mark))
            print('   %s  existed=%s  size=%s' % (e['createdAt'], e['existed'], e['size']))
        return 0

    if cmd == 'restore':
        if len(args) < 2:
            print('用法: snapshot.py restore <id>', file=sys.stderr)
            return 2
        r = restore(args[1])
        print('%s  %s' % (r['action'], r['path']))
        return 0

    if cmd == 'undo':
        if len(args) < 2:
            print('用法: snapshot.py undo <path>', file=sys.stderr)
            return 2
        entries = list_entries(path=args[1], limit=200)
        cand = next((e for e in entries
                     if e.get('reason') != 'pre-restore' and not e.get('consumed')), None)
        if cand is None:
            print('没有可回退的快照：%s' % args[1], file=sys.stderr)
            return 1
        r = restore(cand['id'])
        print('回退到 %s → %s' % (cand['id'], r['action']))
        return 0

    print('未知命令: %s' % cmd, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
