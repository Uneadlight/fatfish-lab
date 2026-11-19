"""能力快照：把散在各处的「能力数字」一次性从真值采集到 JSON。

为什么要它（2026-11-18 用户 m16919 追问后定的）：
  同一个数字散在多个文档里，改一处忘三处；读到的数字分不清「现查的」还是「抄来的」；
  能力变化没有可对比的历史。快照治这三种病，**不治**「我把清单条目当标题读」。

口径（重要，别混）：
  · lab.commandCount —— 运行时 build_parser() 的 choices 数，不是数源码里的 add_parser
  · plugins[].version —— 读 profile 的 node_modules/<name>/package.json 或 link 源码目录
  · routeLibrary.domains/routes —— 读 tier_domains.PATH_OPTIONS 的真实条数
  · memory.* —— 读 memories.json 的活跃条数与 5/5 条数

用法：
  lab snapshot            # 写 架构文档/能力快照.json + 打印摘要
  lab snapshot --json     # 只输出 JSON（给脚本消费）
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime

ROOT = r'D:\work'
ARCH = os.path.join(ROOT, '架构文档')
OUT = os.path.join(ARCH, '能力快照.json')
PROFILE = r'~/.dsh\profiles\desktop'

# 关键路径：(标签, 路径, 说明)。只收「存在性会变、且判断依赖它」的路径。
KEY_PATHS = [
    ('lab', os.path.join(ROOT, 'tools', 'lab', 'lab.py'), 'lab CLI 主入口'),
    ('tier_domains', os.path.join(ROOT, 'tools', 'lab', 'tier_domains.py'), '候选路线库数据'),
    ('skill_main', os.path.join(ROOT, 'dsh-workflow-skill', 'skills', 'workflow', 'SKILL.md'), '主规则'),
    ('ability_list', os.path.join(ARCH, '我的能力清单.md'), '能力清单'),
    ('memory_json', r'~/.dsh\memory\memories.json', '记忆库'),
    ('comfyui', os.path.join(ROOT, 'ComfyUI', 'main.py'), 'ComfyUI'),
    ('blender_live', os.path.join(ROOT, 'tools', 'blender_live.py'), 'Blender 实时控制'),
    ('ffmpeg', os.path.join(ROOT, 'tools', 'ffmpeg', 'ffmpeg.exe'), 'FFmpeg'),
    ('plugin_index', os.path.join(ROOT, '插件库', 'awesome-index.json'), '插件索引'),
]


def _lab_commands():
    """运行时取 lab 子命令（不是数源码里的 add_parser —— 外部模块 register() 会漏）。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'lab'))
        import lab  # noqa: PLC0415 — 延迟导入，避免循环

        parser = lab.build_parser()
        for action in parser._actions:  # noqa: SLF001 — argparse 没有公开接口
            choices = getattr(action, 'choices', None)
            if choices:
                return sorted(choices)
        return []
    except Exception as e:  # noqa: BLE001 — 采不到要说明，不能静默给空
        return {'error': '%s: %s' % (type(e).__name__, e)}


def _plugins():
    """读 profile 的 package.json + 每个包的真版本（link 的读源码目录）。"""
    out = []
    try:
        pkg = json.loads(io.open(os.path.join(PROFILE, 'package.json'), encoding='utf-8').read())
    except Exception:  # noqa: BLE001
        return out
    deps = dict(pkg.get('dependencies') or {})
    for name in sorted(deps):
        spec = str(deps[name])
        entry = {'name': name, 'spec': spec}
        if spec.startswith('link:'):
            src = spec[5:].replace('\\\\', '\\').replace('/', os.sep)
            pj = os.path.join(src, 'package.json')
        else:
            pj = os.path.join(PROFILE, 'node_modules', name, 'package.json')
        try:
            entry['version'] = json.loads(io.open(pj, encoding='utf-8').read()).get('version')
        except Exception:  # noqa: BLE001
            entry['version'] = None
        out.append(entry)
    return out


def _routes():
    try:
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'lab'))
        import tier_domains  # noqa: PLC0415

        doms = tier_domains.PATH_OPTIONS
        return {
            'domains': len(doms),
            'routes': sum(len(d.get('routes') or []) for d in doms),
        }
    except Exception as e:  # noqa: BLE001
        return {'error': '%s: %s' % (type(e).__name__, e)}


def _memory():
    p = r'~/.dsh\memory\memories.json'
    try:
        data = json.loads(io.open(p, encoding='utf-8').read())
        items = data if isinstance(data, list) else (data.get('memories') or [])
        live = [m for m in items if not m.get('deprecated')]
        fives = [m for m in live if m.get('importance') == 5]
        pinned = [m for m in fives if m.get('pinned') is True]
        return {
            'total': len(items),
            'active': len(live),
            'fiveFive': len(fives),
            'fiveFiveChars': sum(len(str(m.get('content') or '')) for m in fives),
            'pinnedFive': len(pinned),
            'activeChars': sum(len(str(m.get('content') or '')) for m in live),
        }
    except Exception as e:  # noqa: BLE001
        return {'error': '%s: %s' % (type(e).__name__, e)}


def _paths():
    out = {}
    for label, path, note in KEY_PATHS:
        if os.path.exists(path):
            st = os.stat(path)
            out[label] = {'path': path, 'exists': True, 'bytes': st.st_size, 'note': note}
        else:
            out[label] = {'path': path, 'exists': False, 'note': note}
    return out


def build():
    cmds = _lab_commands()
    return {
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'generator': 'lab snapshot',
        'lab': {
            'commandCount': len(cmds) if isinstance(cmds, list) else None,
            'commands': cmds,
        },
        'plugins': _plugins(),
        'routeLibrary': _routes(),
        'memory': _memory(),
        'paths': _paths(),
    }


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    snap = build()
    if '--json' in argv:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    os.makedirs(ARCH, exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(snap, ensure_ascii=False, indent=2))
    rl = snap['routeLibrary']
    mem = snap['memory']
    print('[OK] 写 %s' % OUT)
    print('  lab 子命令 %s 个' % snap['lab']['commandCount'])
    print('  插件 %d 个（读到版本 %d 个）' % (
        len(snap['plugins']),
        sum(1 for p in snap['plugins'] if p.get('version')),
    ))
    print('  路线库 %s 域 / %s 条' % (rl.get('domains'), rl.get('routes')))
    print('  记忆 %s 条活跃（5/5 %s 条 / pinned %s 条 / 正文 %s 字符）' % (
        mem.get('active'), mem.get('fiveFive'), mem.get('pinnedFive'), mem.get('activeChars'),
    ))
    missing = [k for k, v in snap['paths'].items() if not v.get('exists')]
    if missing:
        print('  [注意] 路径不存在：%s' % ', '.join(missing))
    return 0


def cmd_capsnap(a):
    """lab capsnap 的入口（argparse 传进来的 Namespace）。"""
    return main(['--json'] if getattr(a, 'json', False) else [])


def register(sub) -> None:
    p = sub.add_parser(
        'capsnap',
        help='能力快照：从真值采集 lab 子命令数 / 插件版本 / 路线库条数 / 记忆条数 → 架构文档/能力快照.json',
    )
    p.add_argument('--json', action='store_true', help='只输出 JSON，不写文件')
    p.set_defaults(func=cmd_capsnap)


if __name__ == '__main__':
    raise SystemExit(main())
