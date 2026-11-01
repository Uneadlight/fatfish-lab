# -*- coding: utf-8 -*-
r"""生成 @deepseek-ai 306 个包的逐包索引表。

目的：不留盲区——每个包我都要知道它在哪一层、干什么。
原则：**有官方 description 就原文引用，没有就明确标注是我按包名推断的**，
不把推断冒充成事实。

用法：py D:\work\tools\lab\gen_pkg_index.py [输出路径]
"""
import importlib.util
import json
import sys
from collections import defaultdict

LAB = r'D:\work\tools\lab\lab.py'
spec = importlib.util.spec_from_file_location('lab', LAB)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

OUT = sys.argv[1] if len(sys.argv) > 1 else r'D:\work\架构文档\包索引-306.md'

# 顺序敏感：越靠前越"影响行为"
BUCKETS: list[tuple[str, str, list[str]]] = [
    ('工具', '1', ['tool', 'model-facing', 'callable']),
    ('提示词', '2', ['prompt', 'context', 'compaction', 'system message', 'instruction']),
    ('权限', '3', ['permission', 'sandbox', 'approval', 'policy', 'authorization']),
    ('会话', '4', ['session', 'storage', 'history', 'checkpoint', 'persist']),
    ('模型', '5', ['model', 'llm', 'provider', 'inference', 'completion']),
    ('记忆', '6', ['memory', 'search', 'index', 'embedding', 'recall', 'query']),
    ('插件', '7', ['plugin', 'bundle', 'loader', 'profile', 'cordis', 'extension']),
    ('文件', '8', ['file', 'workspace', 'filesystem', 'worktree', 'path', 'glob']),
    ('网络', '9', ['http', 'fetch', 'network', 'proxy', 'server', 'websocket', 'api']),
    ('界面', '10', ['ui', 'client', 'web', 'desktop', 'theme', 'render', 'component', 'view', 'tab', 'panel']),
    ('MCP', '11', ['mcp']),
]

header, data_start = lab._asar_index()
seen: dict[str, str] = {}
total_pkg = 0
with open(lab.ASAR, 'rb') as fh:
    for path, node in lab._walk(header):
        if not path.endswith('/package.json'):
            continue
        total_pkg += 1
        try:
            meta = json.loads(lab._read_node(fh, data_start, node).decode('utf-8'))
        except Exception:
            continue
        name = str(meta.get('name') or '')
        if not name.startswith('@deepseek-ai/'):
            continue
        desc = ' '.join(str(meta.get('description') or '').split())
        if name not in seen or len(desc) > len(seen[name]):
            seen[name] = desc


# 关键词匹不出来的，逐包显式指定——比硬调关键词可靠，因为不会误伤别的包。
# 这 29 个暴露了一个认知缺口：先前的 11 类分类**漏掉了整个「运行时骨架」层**。
OVERRIDE: dict[str, str] = {
    # 抽象缝 + 实现：ctx.xxx 的接口与本地实现，换实现就是换策略
    'dsh-shell': '运行时骨架',
    'dsh-bash-local': '运行时骨架',
    'dsh-pwsh-local': '运行时骨架',
    'dsh-subprocess': '运行时骨架',
    'dsh-subprocess-local': '运行时骨架',
    'dsh-jobs-local': '运行时骨架',
    'dsh-settings': '运行时骨架',
    'dsh-ptc-runtime': '运行时骨架',
    'dsh-workflow': '运行时骨架',
    'dsh-user-questions': '运行时骨架',
    'dsh-win32-process': '运行时骨架',
    # 零依赖基础件：谁都在用，谁都不直接提供功能
    'cosmokit': '基础库',
    'schemastery': '基础库',
    'dsh-brand': '基础库',
    'dsh-util-values': '基础库',
    'dsh-timeout': '基础库',
    'dsh-output-retention': '基础库',
    'dsh-token-meter': '基础库',
    'dsh-typert-registry': '基础库',
    'dsh-package-manifest': '基础库',
    # 智能体本身
    'dsh-agent': '智能体',
    'dsh-experimental-agent-team': '智能体',
    'dsh-subagent-fork-in-process': '智能体',
    'dsh-subagent-spawn-in-process': '智能体',
    'dsh-persona': '智能体',
    # 账号与身份
    'dsh-anonymous-user-id': '账户身份',
    'dsh-deepseek-account-platform': '账户身份',
    # 外部能力（语音/文档转换）
    'dsh-experimental-speech-to-text-sensevoice': '外部能力',
    'dsh-office-to-pdf': '外部能力',
}


def bucket_of(name: str, desc: str) -> str:
    short_name = name.replace('@deepseek-ai/', '')
    if short_name in OVERRIDE:
        return OVERRIDE[short_name]
    low_desc = desc.lower()
    low_name = name.lower()
    for short, _, kws in BUCKETS:
        if any(kw in low_desc or kw in low_name for kw in kws):
            return short
    return '未归类'


groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
for name in sorted(seen):
    groups[bucket_of(name, seen[name])].append((name, seen[name]))

order = [b[0] for b in BUCKETS] + ['运行时骨架', '基础库', '智能体', '账户身份', '外部能力', '未归类']
with_desc = sum(1 for d in seen.values() if d)
no_desc = len(seen) - with_desc

lines: list[str] = [
    '# @deepseek-ai 包索引',
    '',
    f'> 生成于 2026-11-01 · 数据源 `D:\\DeepSeek Harness\\resources\\app.asar` 内 {total_pkg} 个 `package.json`，'
    f'去重后 **{len(seen)}** 个 `@deepseek-ai/*` 包。',
    f'> 其中 **{with_desc}** 个带官方 description（原文引用），**{no_desc}** 个没有（职责列标 `~` 的是我按包名推断，不是官方说法）。',
    '',
    '## 怎么用这张表',
    '',
    '- 想知道"某个行为是谁负责的" → 按层找',
    '- 想知道"坏了会不会影响我" → 看层：工具层坏了 = 我调不动；权限层坏了 = 全盘被拦；会话层坏了 = 历史丢；界面层坏了 = 看得见但不致命',
    '- **不做的事**：逐包读源码。工具/会话/插件这类数量大的层，知道职责就够，只有我会改的才读到代码级',
    '',
]

for short in order:
    items = groups.get(short, [])
    if not items:
        continue
    lines.append(f'## {short}（{len(items)}）')
    lines.append('')
    lines.append('| # | 包 | 职责 |')
    lines.append('|---|---|---|')
    for i, (name, desc) in enumerate(items, 1):
        pkg = name.replace('@deepseek-ai/', '')
        if desc:
            cell = desc[:110].replace('|', '\\|')
        else:
            cell = f'~（无官方描述，按名推断：{pkg.replace("dsh-", "").replace("-", " ")}）'
        lines.append(f'| {i} | `{pkg}` | {cell} |')
    lines.append('')

lines += [
    '## 统计',
    '',
    '| 层 | 包数 |',
    '|---|---|',
]
for short in order:
    n = len(groups.get(short, []))
    if n:
        lines.append(f'| {short} | {n} |')
lines.append(f'| **合计** | **{len(seen)}** |')
lines.append('')

with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(lines))

print(f'[OK] {len(seen)} 个包 -> {OUT}')
print(f'  有描述 {with_desc}，无描述 {no_desc}')
for short in order:
    n = len(groups.get(short, []))
    if n:
        print(f'  {short}: {n}')
