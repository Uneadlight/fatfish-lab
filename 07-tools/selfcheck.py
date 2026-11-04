r"""机制随能力漂移检测器（lab selfcheck）。

为什么要有这个：SKILL.md / 记忆 / 架构文档里写着很多「我现在有什么」——
子命令个数、插件个数、路径、工具名。能力一变，这些字就过期了，
而**过期的机制比没有机制更坏**：它让我按一个不存在的世界行动。

设计原则（跟 lab fact 一致）：**只验「说的和磁盘上的是不是一回事」，不判「该不该这样」**。
每条差异都给「话在哪（文件:行）」+「实际是多少」+「怎么改」。

检查项：
  1. lab 子命令引用   —— 文档里写 `lab xxx`，lab.py 里有没有这个子命令
  2. 绝对路径引用      —— 文档里写的 E:\... / C:\... 还在不在
  3. 计数断言          —— 「N 个子命令 / N 个插件 / N 个 bundle」跟实际对不对
  4. 文档互引          —— 架构文档里提到的文档是否还存在

用法：
  py selfcheck.py             # 全跑，人读
  py selfcheck.py --json      # 机器读
  py selfcheck.py --only 2    # 只跑第 2 组
返回码：全部一致 = 0；有差异 = 1
"""


import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(r'D:\work')
SKILL = ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md'
LAB_PY = ROOT / 'tools' / 'lab' / 'lab.py'
ARCH = ROOT / '架构文档'
PROFILE_PKG = Path(r'~/.dsh\profiles\desktop\package.json')

# 要扫的文档（前两个是"告诉我自己该怎么做"的核心，后面的会引用能力）
DOCS = [
    SKILL,
    ROOT / '自进化' / '迭代章程.md',
    ROOT / '自进化' / '路线图.md',
    ARCH / 'README.md',
    ARCH / '外来插件掌控表.md',
    ARCH / '我的能力清单.md',
    ARCH / '我的能力缺口-v2.md',
]

RE_LAB_CMD = re.compile(r'\blab\s+(?:\.py\s+)?([a-z][a-z0-9-]{2,})\b')
RE_NSUBCMD = re.compile(r'(\d+)\s*(?:个)?\s*子命令')
RE_NBUNDLE = re.compile(r'(\d+)\s*(?:个)?\s*(?:bundle|插件)')
# 路径：遇到反引号 / 星号 / 全角或半角冒号 / 引号就停（那些不是路径字符，是 markdown 或句子标点）
RE_PATH = re.compile(r'([A-Za-z]:\\[^\s，。、；：:*`"\'()\[\]<>|]{3,})')


def read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8')
    except Exception:
        return ''


def lab_subcommands() -> set[str]:
    """从 lab.py 的 argparse 定义里抓出**顶层**子命令名。

    为什么不能只写 `sub\\.add_parser`：`snapshot` 那组是两级子命令，
    代码里是 `sn_sub.add_parser('now', ...)`——它含有 `sub.add_parser`
    这个子串，正则会把 now/list/restore/undo 当成顶层（多算 4 个）。
    2026-11-03 实测：正则和 AST 都抓到 25 个，而 `lab --help` 只列 21 个，
    差的正好是 snapshot 的四个动作。加 lookbehind 排掉 `sn_sub` 这种。
    """
    src = read(LAB_PY)
    return set(re.findall(r"(?<![\w.])sub\.add_parser\('([\w-]+)'", src))


def skill_lab_refs() -> dict[str, list[tuple[str, int, str]]]:
    """文档里引用过的 lab 子命令 -> [(文件名, 行号, 该行原文)]。"""
    out: dict[str, list[tuple[str, int, str]]] = {}
    for doc in DOCS:
        text = read(doc)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in RE_LAB_CMD.finditer(line):
                out.setdefault(m.group(1), []).append((_doc_label(doc), i, line))
    return out


# 这些词说明那句话在讲「历史/提案」，不是在断言现在有什么 → 降级成提示，不算漂移
SOFT_MARKERS = ('→ 不写死', '已改', '曾经', '旧版', '历史', '如果一周内',
                '建议', '将来', '以后做', '还没做', '未做', '做成工具',
                '抄**', '抄：', '装**', '造**')  # 后四个＝「打算这么写」，不是在断言已经有了


def _doc_label(p: Path) -> str:
    """文档标签：优先用相对 ROOT 的路径。

    以前直接报 doc.name，结果 `架构文档/README.md` 和 `tools/lab/README.md`
    都显示成「README.md」，报漂移时根本不知道该改哪个（2026-11-04 实测：
    报「README.md:68 写的 25 个子命令」，我打开 tools/lab/README.md 的 L68
    发现是「8 类凭证扫描」，白查一轮）。
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def check_lab_refs() -> list[dict]:
    actual = lab_subcommands()
    refs = skill_lab_refs()
    bad = []
    for name, hits in sorted(refs.items()):
        if name in actual:
            continue
        fname, lineno, line = hits[0]
        soft = any(k in line for k in SOFT_MARKERS)
        bad.append({
            'kind': '提案/历史引用（不算漂移）' if soft else 'lab子命令不存在',
            'soft': soft,
            'claim': f'写了 `lab {name}`',
            'actual': f'lab.py 没有这个子命令（现有 {len(actual)} 个）',
            'where': f'{fname}:{lineno}（共 {len(hits)} 处）',
        })
    return bad


def check_paths() -> list[dict]:
    bad = []
    seen = set()
    for doc in DOCS:
        text = read(doc)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in RE_PATH.finditer(line):
                p = m.group(1)
                # 去掉行尾标点/反引号残留
                p = p.rstrip('`*）)]，。、；')
                if p in seen or len(p) < 8:
                    continue
                seen.add(p)
                if not Path(p).exists():
                    bad.append({
                        'kind': '路径不存在',
                        'claim': f'`{p}`',
                        'actual': '磁盘上没有',
                        'where': f'{_doc_label(doc)}:{i}',
                    })
    return bad


def check_counts() -> list[dict]:
    bad = []
    nsub = len(lab_subcommands())
    nbundle = 0
    try:
        pkg = json.loads(read(PROFILE_PKG))
        nbundle = len(pkg.get('dsh', {}).get('profile', {}).get('bundles', []))
    except Exception:
        pass

    for doc in DOCS:
        text = read(doc)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            soft = any(k in line for k in SOFT_MARKERS)
            m = RE_NSUBCMD.search(line)
            if m:
                n = int(m.group(1))
                if n != nsub:
                    bad.append({
                        'kind': '子命令计数过期',
                        'soft': soft,
                        'claim': f'「{n} 个子命令」',
                        'actual': f'实际 {nsub} 个',
                        'where': f'{_doc_label(doc)}:{i}',
                    })
            for m2 in RE_NBUNDLE.finditer(line):
                n2 = int(m2.group(1))
                # 只对 25-45 区间的数字做校验，避免误伤「4545 个插件」这类市场数字
                if 25 <= n2 <= 45 and nbundle and n2 != nbundle:
                    bad.append({
                        'kind': 'bundle 计数过期',
                        'soft': soft,
                        'claim': f'「{n2} 个 bundle/插件」',
                        'actual': f'profile 里实际 {nbundle} 个',
                        'where': f'{_doc_label(doc)}:{i}',
                    })
    return bad


def check_cross_docs() -> list[dict]:
    bad = []
    for doc in DOCS:
        text = read(doc)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in re.finditer(r'`?([\u4e00-\u9fa5\w\-]+\.md)`?', line):
                name = m.group(1)
                if name.startswith('http'):
                    continue
                if not (ARCH / name).exists() and not (ROOT / name).exists() \
                        and not (ROOT / '自进化' / name).exists():
                    # 只在「架构文档/xxx.md」这种明确引用时报
                    if '架构文档' in line or '自进化' in line:
                        bad.append({
                            'kind': '文档互引断了',
                            'claim': f'引用了 `{name}`',
                            'actual': '三处目录都找不到',
                            'where': f'{_doc_label(doc)}:{i}',
                        })
    return bad


CAP_DOC = ARCH / '我的能力清单.md'
README_LAB = ROOT / 'tools' / 'lab' / 'README.md'


def check_local_plugins() -> list[dict]:
    """@local/* 的插件：能力清单里提到就必须装着（自己的东西不该漏装）。"""
    bad = []
    try:
        deps = (json.loads(read(PROFILE_PKG)).get('dependencies') or {})
    except Exception:
        return bad
    installed = {n.split('/')[-1] for n in deps}
    text = read(CAP_DOC)
    if not text:
        return bad
    seen = set()
    for m in re.finditer(r'@local/([\w-]+)', text):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        if name not in installed:
            bad.append({
                'kind': '@local 插件没装',
                'claim': f'`@local/{name}`',
                'actual': 'profile dependencies 里没有',
                'where': CAP_DOC.name,
            })
    return bad


def check_readme_coverage() -> list[dict]:
    """lab 的每个子命令，README 里至少提到一次（加了命令没写文档 = 下次又忘）。"""
    bad = []
    text = read(README_LAB)
    if not text:
        return bad
    for name in sorted(lab_subcommands()):
        if f'`{name}`' not in text and f'lab {name}' not in text:
            bad.append({
                'kind': 'README 没写这个子命令',
                'claim': f'`lab {name}`',
                'actual': 'tools/lab/README.md 里没有条目',
                'where': 'tools/lab/README.md',
            })
    return bad


GROUPS = [
    ('lab 子命令引用', check_lab_refs),
    ('绝对路径引用', check_paths),
    ('计数断言', check_counts),
    ('文档互引', check_cross_docs),
    ('@local 插件装机核对', check_local_plugins),
    ('README 覆盖 lab 子命令', check_readme_coverage),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='机制随能力漂移检测')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--only', type=int, help='只跑第 N 组（1 起）')
    a = ap.parse_args(argv)

    report = []
    for idx, (title, fn) in enumerate(GROUPS, 1):
        if a.only and a.only != idx:
            continue
        try:
            items = fn()
        except Exception as e:
            items = [{'kind': '检查自身出错', 'claim': title,
                      'actual': f'{type(e).__name__}: {e}', 'where': '-'}]
        report.append({'group': idx, 'title': title, 'items': items})

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        hard = 0
        soft_n = 0
        for g in report:
            items = g['items']
            h = [it for it in items if not it.get('soft')]
            s = [it for it in items if it.get('soft')]
            hard += len(h)
            soft_n += len(s)
            if not items:
                print(f'✅ [{g["group"]}] {g["title"]}：0 处不一致')
                continue
            flag = '⚠️' if h else '💬'
            print(f'{flag} [{g["group"]}] {g["title"]}：{len(h)} 处漂移'
                  + (f'，{len(s)} 处提案/历史（不算）' if s else ''))
            for it in h[:12]:
                print(f'     · {it["kind"]}')
                print(f'       说的：{it["claim"]}')
                print(f'       实际：{it["actual"]}')
                print(f'       位置：{it["where"]}')
            for it in s:
                print(f'     · (提案/历史，不算) {it["claim"]} @ {it["where"]}')
            if len(h) > 12:
                print(f'     …… 还有 {len(h) - 12} 处')
        print()
        print('=' * 66)
        if hard == 0:
            print('机制与能力一致：文档里说的，磁盘上都有。'
                  + (f'（另有 {soft_n} 处提案/历史引用，按设计不算漂移）' if soft_n else ''))
        else:
            print(f'共 {hard} 处漂移。**这不是错误，是漂移**——能力变了，字没跟着改。')
            print('修法：改文档里的字，或者改能力去匹配文档（通常前者）。')

    hard_total = sum(1 for g in report for it in g['items'] if not it.get('soft'))
    return 0 if hard_total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
