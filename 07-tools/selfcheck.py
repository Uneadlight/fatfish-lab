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
import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r'D:\work')
SKILL = ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md'
LAB_PY = ROOT / 'tools' / 'lab' / 'lab.py'
TESTS_DIR = ROOT / 'tools' / 'lab' / 'tests'
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
RE_NSUBCMD = re.compile(r'(\d+)\s*(?:个)?\s*(?:`?lab`?\s*)?子命令')
# 2026-11-07 修：原来只认「N 个子命令」，「40 个 lab 子命令」这种中间夹 lab 的写法
# 全程没被检查过——§11 工具层写着 40 而实际 41，selfcheck 却说 0 漂移。
RE_NBUNDLE = re.compile(r'(\d+)\s*(?:个)?\s*(?:bundle|插件)')
# 2026-11-08 加：规则条数也会过期。那天加第 21 条时，tier.py 有 3 处、SKILL.md 有 1 处
# 还写着「20 条主规则」，selfcheck 全绿——因为第 3 组只查子命令数和 bundle 数。
# 判据：凡是「某个数字被写进文档、而它有唯一真值」的地方，都该有一条断言。
RE_NRULE = re.compile(r'(\d+)\s*条主规则')
# 路径：遇到反引号 / 星号 / 全角或半角冒号 / 引号就停（那些不是路径字符，是 markdown 或句子标点）
RE_PATH = re.compile(r'([A-Za-z]:\\[^\s，。、；：:*`"\'()\[\]<>|]{3,})')


# 2026-11-19 加：读不到的文件要记下来。
# 原来 read() 吞掉一切异常返回 ''，下游检查遇到空文本一律 continue——
# 于是「这份文档不见了」和「这份文档没问题」在输出上完全一样：
# check_lab_refs / check_paths / check_counts / check_cross_docs 全部静默跳过，
# check_counts 的两条断言还依赖计数非零，读成 0 时连它们也一起失效。
# 现在收集起来，main() 末尾统一报「有 N 份文档没读到」。
READ_FAILS: list[str] = []


def read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8')
    except Exception:
        s = str(p)
        if s not in READ_FAILS:
            READ_FAILS.append(s)
        return ''


# 2026-11-11 第 0 步拆 tier.py：域数据搬到 tier_domains.py。
# 所有「按文本找名字」的检查必须把两个文件拼起来看——
# 否则一拆就全变成假缺口（实测：一拆完 look for 插件别名，全部报「已过期」）。
ROUTE_LIB_FILES = ('tier.py', 'tier_domains.py', 'tier_matcher.py', 'tier_judge.py')


def route_lib_text() -> str:
    """候选路线库的源码文本（tier.py + 拆出去的 tier_domains.py）。

    走 `read()` 而不是直接 `Path.read_text()`，是为了让测试能
    `monkeypatch.setattr(sc, 'read', fake)` 注入变异文本（见
    tests/test_selfcheck_assets.py 的三个 mutation 测试）。
    """
    lab = ROOT / 'tools' / 'lab'
    return '\n'.join(read(lab / n) for n in ROUTE_LIB_FILES if (lab / n).exists())


def lab_subcommands() -> set[str]:
    """从 lab.py 的 argparse 定义里抓出**顶层**子命令名。

    为什么不能只写 `sub\\.add_parser`：`snapshot` 那组是两级子命令，
    代码里是 `sn_sub.add_parser('now', ...)`——它含有 `sub.add_parser`
    这个子串，正则会把 now/list/restore/undo 当成顶层（多算 4 个）。
    2026-11-03 实测：正则和 AST 都抓到 25 个，而 `lab --help` 只列 21 个，
    差的正好是 snapshot 的四个动作。加 lookbehind 排掉 `sn_sub` 这种。

    2026-11-17 补：改成**运行时取 parser 的 choices**——`lab img` 是在 `img.py`
    里用 `register(sub)` 注册的，lab.py 源码里根本没有 `sub.add_parser('img')`，
    只扫源码就会把「文档写了 lab img」误判成漂移、把子命令数少数一个。
    运行时失败才回退正则（保守，不因为一次 import 失败就让整个自检崩掉）。
    """
    try:
        import argparse as _ap
        import lab as _lab  # 同目录，同进程时直接命中已加载模块
        for act in _lab.build_parser()._actions:
            if isinstance(act, _ap._SubParsersAction):
                return set(act.choices)
    except Exception:
        pass
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
SOFT_MARKERS = ('→ 不写死', '已改', '曾经', '旧版', '历史', '当时', '如果一周内',
                '（历史）', '写明' ,
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
    nrule = 0
    try:
        # §0.1 表的行就是规则条数：`| 21 | 标题 | 过期条件 |`
        skill = read(ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md')
        nrule = len(re.findall(r'^\|\s*(\d+)\s*\|', skill, re.M))
    except Exception:
        pass
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
            for m3 in RE_NRULE.finditer(line):
                n3 = int(m3.group(1))
                if nrule and n3 != nrule:
                    bad.append({
                        'kind': '规则条数过期',
                        'soft': soft,
                        'claim': f'「{n3} 条主规则」',
                        'actual': f'SKILL.md §0.1 表里实际 {nrule} 条',
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
                        and not (ROOT / '自进化' / name).exists() \
                        and not (ARCH / '路线库配套' / name).exists():
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


def _skill_tool_section() -> str:
    """SKILL.md 里 §5.1 全量工具清单那一段（从 `### 5.1` 到下一个 `## `）。"""
    text = read(SKILL)
    m = re.search(r'^### 5\.1 .*?$(.*?)(?=^## |\Z)', text, re.M | re.S)
    return m.group(1) if m else ''


def check_capability_reverse() -> list[dict]:
    """反向差集：磁盘上**有**、机制图里**没写**。

    为什么必须有这一组：前面 6 组全是「文档说 X，实际有没有」——
    缺的是反方向。2026-11-05 dsh-ops 的 16 个工具就是这样漏的：
    能力已经在了、但 §11 的图里没有它，下一次就不知道它存在。
    判据：**新增任何能力后，这一组的差集必须是空的。**

    两个方向：
      A. lab 每个子命令 → SKILL §5.1 里有没有它的名字
      B. profile 里非 DSH 内置的包 → 我的能力清单.md 里有没有它的名字
    """
    bad = []

    # A. lab 子命令 → §5.1
    sec = _skill_tool_section()
    if sec:
        for name in sorted(lab_subcommands()):
            if f'`{name}`' in sec or f'lab {name}' in sec:
                continue
            bad.append({
                'kind': 'lab 子命令没进 §5.1 工具清单',
                'claim': f'`lab {name}` 存在',
                'actual': 'SKILL.md §5.1 里找不到它 → 下次不知道怎么用',
                'where': 'SKILL.md §5.1',
            })

    # B. profile 包 → 我的能力清单.md
    cap_doc = ARCH / '我的能力清单.md'
    cap_text = read(cap_doc)
    try:
        pkg = json.loads(read(PROFILE_PKG))
    except Exception:
        pkg = {}
    names = set()
    dsh = pkg.get('dsh') or {}
    names.update((dsh.get('profile') or {}).get('bundles') or [])
    names.update((pkg.get('dependencies') or {}).keys())
    for full in sorted(names):
        if full.startswith('@deepseek-ai/'):
            continue  # DSH 内置，不要求进能力清单
        short = full.split('/')[-1]
        if not cap_text:
            break
        if full in cap_text or short in cap_text:
            continue
        bad.append({
            'kind': 'profile 里有这个包，能力清单里没记',
            'claim': f'`{full}` 已装',
            'actual': '架构文档/我的能力清单.md 里找不到它的名字',
            'where': cap_doc.name,
        })
    return bad


def test_covered_commands() -> set[str]:
    """从 tests/*.py 里扫出「碰过哪个 cmd_」。

    宽松判据（出现 `cmd_<name>` 就算），不追求覆盖率百分比——
    目标是回答「有没有人写过关于它的测试」，不是精确度量。
    """
    covered: set[str] = set()
    if not TESTS_DIR.is_dir():
        return covered
    for f in TESTS_DIR.glob('*.py'):
        text = read(f)
        for m in re.finditer(r'cmd_([a-z_]+)', text):
            covered.add(m.group(1))
    return covered


def check_test_coverage() -> list[dict]:
    """反向差集：lab 有子命令、tests 里没有任何测试碰过它。

    为什么加这一组：2026-11-07 之前 42 个命令里 41 个零测试，
    三个 bug（## 分级、selfcheck 正则、lab.cmd 编码）就这样潜伏了一个月。
    **但全部标 soft**——它是真实欠账，不是「文档与能力不一致」，
    混进硬告警会让 selfcheck 永远失败、失去信噪比。
    增量由 `lab commit` 的提醒拦住，存量靠这个数字慢慢消。
    """
    bad = []
    covered = test_covered_commands()
    for name in sorted(lab_subcommands()):
        if name in covered or name == 'test':
            continue  # test 自己测自己会死循环
        bad.append({
            'kind': 'lab 子命令没有测试（技术债，不阻塞）',
            'claim': f'`lab {name}` 存在',
            'actual': 'tools/lab/tests/ 里没有任何测试碰过它',
            'where': 'tools/lab/tests',
            'soft': True,
        })
    return bad


# 明确「不值得进候选路线库」的例外——每条都写清理由，不是「查不到就算了」。
ROUTE_WHITELIST = {
    'reconcile': '账本内部对账，维护类动作，不进任务选路',
    'observe': '零数据文件，从建成起一次没用过（待评估删/留）',
    'asar': '读 DSH 自身 app.asar，只在排查 DSH 时用，不是通用路',
    'correction': '内部工具，配合 asar / review 使用',
    'rework': '无真实场景，等第一个真实需求再进库',
    'review': '无真实场景，等第一个真实需求再进库',
}


def check_route_coverage() -> list[dict]:
    """能力总表里有的 lab 子命令 → 候选路线库（tier.py）里有没有归属。

    为什么必须有这一组：2026-11-07 用户 m11744「候选路线库必须包含你能力层的全部」，
    m11599 追问「有没有包含你所拥有的一切」时实测只有 36%（我只把 lab 子命令当能力）。
    这一组的判据很硬：**总表里每一项都必须能在一个域里找到**——找不到就是
    「我知道有、但永远不会想起用」，比没有更糟（没有时我会去学，有而不想起会反复踩坑）。
    白名单是明示的例外（写清理由），不是「查不到就跳过」。
    """
    tier_text = route_lib_text()
    bad = []
    for name in sorted(lab_subcommands()):
        if name in ROUTE_WHITELIST:
            continue
        if re.search(rf'\blab\s+{re.escape(name)}\b', tier_text):
            continue
        bad.append({
            'kind': 'lab 子命令没进候选路线库',
            'claim': f'`lab {name}` 是能力总表里的一项',
            'actual': 'tier.py 的 PATH_OPTIONS / AUX_MAP / AUX_GLOBAL 里找不到它 → 想不起来用',
            'where': 'tools/lab/tier.py',
        })
    return bad


def check_rule_coverage() -> list[dict]:
    """SKILL.md §0.1 的 20 条主规则 → `lab tier` 的规则触发表里有没有触发信号。

    为什么必须有这一组：用户 m11744「能力层的全部还要含元规则与记忆」、
    m11759「能力层＝我能做到的所有事情，包括规矩、规则、记忆」。
    但「列在能力总表里」不等于「做得到」——20 条规则如果只被列成一张标题表，
    我遇到事时仍然不会翻它（记忆里的原话：「错题本不会自己跳出来，必须由信号触发检索」）。
    所以判据是：**每条规则都得有一个触发信号**，否则它只是文档里的一行字。
    """
    import ast  # noqa: PLC0415

    # 2026-11-11 第 0 步搬家：RULE_* 表搬进 tier_matcher.py 了，所以按 ROUTE_LIB_FILES 逐个解析，
    # 不能再只读 tier.py——否则每条规则都被判成「没有触发信号」（实测 23 处假漂移）。
    lab = ROOT / 'tools' / 'lab'
    trees = []
    for name in ROUTE_LIB_FILES:
        f = lab / name
        if not f.exists():
            continue
        try:
            trees.append(ast.parse(read(f)))
        except SyntaxError as e:
            return [{'kind': f'{name} 语法错误', 'claim': '规则触发表可被解析',
                     'actual': f'{e}', 'where': f'tools/lab/{name}'}]

    have = set()
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in ('RULE_OPENING', 'RULE_CLOSING', 'RULE_SIGNALS'):
                    for el in getattr(node.value, 'elts', []):
                        if isinstance(el, ast.Tuple) and el.elts and isinstance(el.elts[0], ast.Constant):
                            if isinstance(el.elts[0].value, int):
                                have.add(el.elts[0].value)

    # 从 SKILL.md 的 §0.1 表里数出「应该有哪几条」
    # 表头是 `| 条 | 标题 | 过期条件… |`，后面跟分隔行，再跟 `| N | … |` 若干行。
    skill = read(SKILL)
    m = re.search(r'\| 条 \| 标题 \|[^\n]*\n\|[\s\-|]+\n((?:\|\s*\d+\s*\|[^\n]*\n)+)', skill)
    want = set()
    if m:
        for line in m.group(1).splitlines():
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if cells and cells[0].isdigit():
                want.add(int(cells[0]))

    bad = []
    for n in sorted(want - have):
        bad.append({
            'kind': '规则没有触发信号',
            'claim': f'SKILL.md §0.1 第 {n} 条主规则',
            'actual': 'tier.py 的 RULE_OPENING / RULE_CLOSING / RULE_SIGNALS 里没有它 → 遇到事不会翻到',
            'where': 'tools/lab/tier.py',
        })
    for n in sorted(have - want):
        bad.append({
            'kind': '规则编号对不上',
            'claim': f'tier.py 规则触发表里有第 {n} 条',
            'actual': 'SKILL.md §0.1 里没有这个编号 → 编号可能被改过，触发信号指向了不存在的规则',
            'where': 'dsh-workflow-skill/skills/workflow/SKILL.md',
        })
    return bad


# 间接覆盖：能力由别的 lab 子命令代跑，路线库里写的是「那个命令」不是「这个文件」。
# 只写「为什么算间接」，不写「查不到就算间接」——查不到仍要报。
INDIRECT_ASSETS = {
    'route_health': '由 lab health 代跑',
    'tool_stats': '由 lab tools 代跑',
    'session_grep': '由 lab sessions 代跑',
    'session_health': '由 lab selfcheck / 计划任务代跑',
    'recall': '由 lab recall 代跑',
    'deploy': '由 lab deploy 代跑',
    'tier': '由 lab tier 代跑（它自己就是路线库）',
    'selfcheck': '由 lab selfcheck 代跑',
    'lab': 'lab CLI 本体，不是子命令',
    'onboard': '由 lab onboard 代跑',
    # 2026-11-07 第 11 组首次跑出的 16 个，逐个归因（不归因就不许加进来）
    'git_commit': 'lab commit 的实现（cmd_commit 内部调它）',
    'ocr_run': 'lab ocr 的实现（转发给 ocr-venv312）',
    'read_session': 'lab sessions 的实现',
    'read_docx': '一次性读取工具，没有独立场景（ops_read_files 已覆盖常规文本）',
    'config_backup': 'lab config 备份动作的实现',
    'gen_pkg_index': '一次性维护动作（生成包索引），不是可反复选的「路」',
    'clutter_clean': '维护动作（清 _scratch 垃圾），由 lab lint 触发',
    'clutter_inventory': '维护动作（只读盘点碎屑）',
    'skill_stats': 'lab skill 的实现',
    'reconcile': 'lab reconcile 的实现（该子命令在 ROUTE_WHITELIST 里豁免）',
    'review': 'lab review 的实现（该子命令在 ROUTE_WHITELIST 里豁免）',
    'rework': 'lab rework 的实现（该子命令在 ROUTE_WHITELIST 里豁免）',
    'session_age': 'lab session-age 的实现（该子命令在 ROUTE_WHITELIST 里豁免）',
    'test_encoding': '老式自测脚本，不是能力（pytest 覆盖由 lab test 负责）',
    'test_fact': '老式自测脚本，不是能力',
    'test_snapshot': '老式自测脚本，不是能力',
}

# 插件在路线库里的称呼可能是能力词而不是包名（dsh-workflow-skill 的产物是 SKILL.md）
PLUGIN_ALIASES = {
    'dsh-workflow-skill': ('SKILL.md', '规则触发'),
    'dsh-worktree-tool': ('worktree_create', 'worktree_list'),
}

# 纯展示 / 纯装饰类：没有任何「该在什么时候用它」的场景可写进路线库。
# 2026-11-08：**唯一来源是 `tools/lab/tier.py` 的 `NON_ROUTE_ASSETS`**，这里是运行时解析出来的
# 影子副本（短名 -> 类型），不维护自己的名单。
# 起因：两处各写一份 -> 我给 tier.py 加了 NON_ROUTE_ASSETS、这里的 DISPLAY_ONLY 没跟着改，
# 而覆盖率检查按**文本**判「名字在 tier.py 里出现过」→ dsh-chat-background 看起来已覆盖，
# mutation 测试（把它从豁免里删掉）不再报错，等于这条检查变成了假检查。
# 判据：同一个概念只许有一个定义处，别处只能是它的影子。
def _non_route_assets() -> dict[str, tuple[str, str]]:
    """从 tier.py 的 NON_ROUTE_ASSETS 解析出 {短名: (类型, 理由)}。"""
    src = read(ROOT / 'tools' / 'lab' / 'tier.py')
    m = re.search(r"^NON_ROUTE_ASSETS\s*=\s*\[(.*?)^\]", src, re.S | re.M)
    if not m:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for name, kind, why in re.findall(
            r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\)', m.group(1)):
        out[name.split('/')[-1]] = (kind, why)
    return out


def check_asset_route_coverage() -> list[dict]:
    """插件与 tools 脚本 → 候选路线库里有没有位置（第 9 组只扫 lab 子命令，这条补另外两类）。

    2026-11-07 实测口径：bundle 覆盖 3/24 = 12%、tools 脚本 28/99 = 28%——
    我当时判它们是「间接覆盖」（能力由 lab 子命令代跑）就放过了，但那只解释了
    「为什么不用逐条写进路线库」，没回答「怎么保证以后新加的那个也不漏」。
    判据分两档：**点名提到**（出现名字或 `lab <stem>`）= 覆盖；**只在别处出现** = 间接；
    **一次都没出现** = 真缺口，报出来。间接覆盖单独计数，不混进失败。
    """
    tier_text = route_lib_text()
    non_route = _non_route_assets()   # 免检名单的唯一来源（tier.py）
    bad = []

    # 插件：权威清单来自 deploy.py 的 SELF_BUILT（不扫目录、不靠记忆）
    deploy_src = read(ROOT / 'tools' / 'lab' / 'deploy.py')
    m = re.search(r"SELF_BUILT\s*=\s*\[(.*?)\n\]", deploy_src, re.S)
    plugins = re.findall(r"['\"]([@\w./-]+)['\"]", m.group(1)) if m else []
    for full in plugins:
        short = full.split('/')[-1]
        if short in non_route:
            continue
        key = short.replace('dsh-', '').replace('-', '_')
        aliases = PLUGIN_ALIASES.get(short, ())
        if short in tier_text or key in tier_text or any(a in tier_text for a in aliases):
            continue
        bad.append({
            'kind': '自研插件没进候选路线库',
            'claim': f'`{short}` 是 SELF_BUILT 里的一项',
            'actual': 'tier.py 里搜不到它的名字、能力词和别名 → 想不起来用（跑 lab onboard 看还差哪步；'
                      '若它只是装饰或只是某个 lab 子命令的实现，加进 tier.py 的 NON_ROUTE_ASSETS / '
                      '本文件的 INDIRECT_ASSETS 并写清理由）',
            'where': 'tools/lab/tier.py',
        })

    # tools 脚本：按 stem 判，`lab <stem>` 点名优先，其次文件里任何地方出现算间接
    scripts = sorted(p.stem for p in (ROOT / 'tools' / 'lab').glob('*.py')
                     if p.stem not in ('lab',) and not p.stem.startswith('_'))
    for stem in scripts:
        if stem in INDIRECT_ASSETS:
            continue
        if re.search(rf'\blab\s+{re.escape(stem)}\b', tier_text):
            continue
        if stem in tier_text:
            continue
        bad.append({
            'kind': 'tools 脚本没进候选路线库',
            'claim': f'`tools/lab/{stem}.py` 是一个能跑的能力',
            'actual': 'tier.py 里既没有 `lab <stem>` 也没有它的名字 → 它不在任何路线里，我会想不起来',
            'where': 'tools/lab/tier.py',
        })
    return bad


def check_knowledge_paths() -> list[dict]:
    """`tier.py` 的 `_KNOWLEDGE` 里每个知识源路径必须真的存在（第 12 组）。

    2026-11-08 立：`lab tier` 会在「知识源」栏印文档路径，方便我选定路线后知道
    去查什么；但那些路径**从没被检查过**。文档改名/搬家/删掉之后，它会指着一处空气。

    **指向空气比不指向更糟**：不指向，我知道自己没得查；指向空气，我以为「有文档
    可查」，点进去是空的，然后我不会再看第二眼——比一开始就没有还差。

    用 `ast.literal_eval` 而不是正则：`_KNOWLEDGE` 是「域名 → ((描述, 路径), …)」
    的嵌套结构，正则抓不准括号配对；纯字面量正好能直接求值。
    """
    src = read(ROOT / 'tools' / 'lab' / 'tier.py')
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [{
            'kind': 'tier.py 语法错，无法检查知识源',
            'claim': 'tier.py 能被解析', 'actual': f'ast.parse 失败：{e}',
            'where': 'tools/lab/tier.py',
        }]

    kn = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == '_KNOWLEDGE' for t in node.targets):
            try:
                kn = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                kn = None
    if not isinstance(kn, dict):
        return [{
            'kind': '没读到 _KNOWLEDGE',
            'claim': 'tier.py 里有 `_KNOWLEDGE = {…}` 纯字面量',
            'actual': 'ast 找不到，或它引用了变量（结构改了吗？改成字面量才能检查）',
            'where': 'tools/lab/tier.py',
        }]

    bad = []
    for domain, items in kn.items():
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            desc, rel = item[0], item[1]
            if not rel:
                continue
            if not (ROOT / str(rel)).exists():
                bad.append({
                    'kind': '知识源路径不存在',
                    'claim': f'`{domain}` 的知识源：{desc}',
                    'actual': f'`{rel}` 不存在 → lab tier 会指着一处空气',
                    'where': str(rel),
                })
    return bad


FINGERPRINT_FILE = ROOT / '架构文档' / '能力指纹.json'
SKILL_MD = ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md'


def _capability_fingerprint() -> dict:
    """当前能力指纹：四项「能力变了就会变、但文档不一定跟着改」的东西。

    选这四项不是随手挑的——它们是 §0.1 里那条最常被命中的过期条件
    「工具集变化」的**观察量**：装/卸插件 → `plugins`；lab 加子命令 → `lab_cmds`；
    加/删工具脚本 → `tools`；加/删规则 → `rules`。
    """
    fp = {}

    # 1. 插件（profile dependencies，与 onboard 同一基准——不用 bundles，多的 8 个是子组件包）
    try:
        deps = (json.loads(read(PROFILE_PKG)).get('dependencies') or {})
        fp['plugins'] = sorted(n.split('/')[-1] for n in deps)
    except Exception as e:
        fp['plugins'] = [f'<读不到 profile: {type(e).__name__}>']

    # 2. lab 子命令（运行时取 parser choices——2026-11-17 起，因为 `lab img` 这种
    #    在外部模块 register(sub) 注册的子命令，lab.py 里没有对应的 cmd_img 函数；
    #    旧的「扫 cmd_* 函数名」会静默少数一个，导致文档写对反而报漂移）
    try:
        fp['lab_cmds'] = sorted(lab_subcommands())
    except Exception as e:
        fp['lab_cmds'] = [f'<取不到子命令: {type(e).__name__}>']

    # 3. §0.1 规则条数
    try:
        nums = re.findall(r'^\|\s*(\d+)\s*\|', read(SKILL_MD), re.M)
        fp['rules'] = sorted({int(x) for x in nums})
    except Exception as e:
        fp['rules'] = [f'<读不到 SKILL.md: {type(e).__name__}>']

    # 4. tools 脚本
    try:
        fp['tools'] = sorted(p.stem for p in (ROOT / 'tools' / 'lab').glob('*.py')
                             if not p.stem.startswith('_') and p.stem != 'lab')
    except Exception as e:
        fp['tools'] = [f'<列不到 tools: {type(e).__name__}>']

    return fp


def check_capability_fingerprint() -> list[dict]:
    """能力指纹漂移 → 提醒重审 §0.1（第 13 组）。

    2026-11-08 立，用户 m14668：「你的规则要随着你的能力而更改。尺子也不能是一成不变的。」

    §0.1 早就写了 20 条规则的过期条件，`lab tier` 也会在开工时把命中的规则报给我——
    但**能力变化的那一刻没人提醒「去重审那张表」**。今天一天就命中了五次：
    selfcheck 数子命令 25→42、mem-maintain 的 BUDGET 60,000→120,000、
    env-doctor 的 AUTOMATION_MAP 还登记 11-07 就删的任务、onboard 的 PASSIVE_LOGS
    没跟 fail-guard 的新路径、测试里写死 `== 11`。
    **全是「过期条件早就命中，但没人去读表」。**

    指纹只做一件事：**记下上次审表时的能力长相，变了就报**。
    不自动更新——自动更新等于「报一次然后忘掉」，跟没报一样。
    审完表手动跑 `lab selfcheck --update-fingerprint` 记下新基准。
    """
    cur = _capability_fingerprint()

    if not FINGERPRINT_FILE.exists():
        FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        FINGERPRINT_FILE.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return []  # 首次建基准，不算漂移

    try:
        old = json.loads(FINGERPRINT_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        return [{
            'kind': '能力指纹文件读不了',
            'claim': str(FINGERPRINT_FILE),
            'actual': f'{type(e).__name__}: {e} → 无法判断能力有没有变',
            'where': '架构文档/能力指纹.json',
        }]

    bad = []
    for key, label in (('plugins', '插件'), ('lab_cmds', 'lab 子命令'), ('tools', 'tools 脚本')):
        old_set, new_set = set(old.get(key) or []), set(cur.get(key) or [])
        if old_set == new_set:
            continue
        added, removed = sorted(new_set - old_set), sorted(old_set - new_set)
        bits = []
        if added:
            bits.append('新增 ' + '、'.join(added[:6]) + ('…' if len(added) > 6 else ''))
        if removed:
            bits.append('移除 ' + '、'.join(removed[:6]) + ('…' if len(removed) > 6 else ''))
        bad.append({
            'kind': '能力变了，§0.1 该重审',
            'claim': f'{label}：' + '；'.join(bits),
            'actual': '§0.1 里有几条的过期条件可能刚被命中'
                      ' → 审完跑 `lab selfcheck --update-fingerprint` 记下新基准',
            'where': 'dsh-workflow-skill/skills/workflow/SKILL.md',
        })

    if set(old.get('rules') or []) != set(cur.get('rules') or []):
        added = sorted(set(cur.get('rules') or []) - set(old.get('rules') or []))
        removed = sorted(set(old.get('rules') or []) - set(cur.get('rules') or []))
        bad.append({
            'kind': '规则条数变了，§0.1 该重审',
            'claim': f'新增 {added or "—"}；移除 {removed or "—"}',
            'actual': '加/删规则时有没有同时改 tier.py 的 RULE_SIGNALS'
                      '（不改的话新规则永远不触发，等于没加）',
            'where': 'dsh-workflow-skill/skills/workflow/SKILL.md',
        })
    return bad


def _load_tier():
    """把 tier.py 当模块加载（顶层只有常量/函数定义，`if __name__` 才跑 main）。"""
    import importlib.util
    p = ROOT / 'tools' / 'lab' / 'tier.py'
    spec = importlib.util.spec_from_file_location('_tier_for_selfcheck', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_route_hygiene() -> list[dict]:
    """第 14 组：路线清单体检——判「臃肿」，不判「条数」。

    2026-11-08 用户 m16336（原话）：「超过 20 条时不是该拆，而是该休整了。
    如果休整后还是更多的话，那就还是那样就可以了，让它自然而然的往下增长
    就好了。拆不是必须要的。保证它的整体性完整性。不臃肿才是必要的。就算它
    线路再多，只要它运行的够流畅、不臃肿都是可以接受的。」

    → 所以这里**只报 error 级**：重复长处 / 死路径 / 空壳字段 / 代号不合规。
      「>20 条该休整了」是 info，不进这道门禁——否则加几条路线就红，
      反而逼我去砍东西，跟用户定的口径正好反过来。

    首次上线实测抓到 5 处真问题（4 条「代价」只写了「只读」两个字、
    1 条指向还不存在的 `盲区清单.md`），全是靠人眼永远发现不了的那种。
    """
    try:
        tier = _load_tier()
    except Exception as e:  # noqa: BLE001
        return [{'kind': '路线体检跑不起来', 'claim': 'lab tier --audit 加载 tier.py 失败',
                 'actual': f'{type(e).__name__}: {e}', 'where': 'tools/lab/tier.py'}]
    bad: list[dict] = []
    for i in tier.route_hygiene():
        if i.get('level') != 'error':
            continue
        bad.append({
            'kind': f"路线{i['kind']}",
            'claim': f"[{i['domain']}] {i['code']}. {i['detail']}",
            'actual': '修 tier.py 的 PATH_OPTIONS；或跑 `lab tier --audit` 看全表',
            'where': 'tools/lab/tier.py',
        })
    return bad


def _load_deploy():
    """把 deploy.py 当模块加载（顶层只有常量/函数定义）。"""
    import importlib.util
    p = ROOT / 'tools' / 'lab' / 'deploy.py'
    spec = importlib.util.spec_from_file_location('_deploy_for_selfcheck', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_deploy_sync() -> list[dict]:
    """第 15 组：自研插件「源码 vs profile 副本」一致性。

    `file:` 依赖是**实体拷贝**，改源码不会同步到 profile——2026-11-08 栽过
    一次：`dsh-self-guard` 源码是 11-08 11:58 的 19,837 B，profile 副本还停在
    11-02 的 13,108 B，**能加载但跑的是旧代码**。当时能发现是因为用户问
    「还是需要每次去寻找放在哪」，靠人提醒；这组检查让它自己红。

    只查 `deploy.SELF_BUILT`（自研的我们才改源码）；`link:` 软链自动同步、
    跳过。外来的 6 个 `file:` 包（community/context/fail-guard/pocket/
    startup-screen/pet-bridge）不在 SELF_BUILT 里，本来就不该被我们改。
    """
    try:
        dep = _load_deploy()
    except Exception as e:  # noqa: BLE001
        return [{'kind': '部署一致性检查跑不起来', 'claim': 'lab deploy 模块加载失败',
                 'actual': f'{type(e).__name__}: {e}', 'where': 'tools/lab/deploy.py'}]
    bad: list[dict] = []
    for name in dep.SELF_BUILT:
        try:
            r = dep.compare(name)
        except Exception as e:  # noqa: BLE001
            bad.append({'kind': '部署一致性检查异常', 'claim': name,
                        'actual': f'{type(e).__name__}: {e}',
                        'where': f'node_modules/{name}'})
            continue
        if r.get('error'):
            bad.append({'kind': '自研插件部署异常', 'claim': name,
                        'actual': r['error'], 'where': r.get('src', '')})
            continue
        if r.get('kind') == 'link' or r.get('in_sync'):
            continue
        bits = []
        if r.get('diff'):
            bits.append(f'{len(r["diff"])} 个文件内容不同（{"、".join(r["diff"][:3])}）')
        if r.get('only_src'):
            bits.append(f'源码多 {len(r["only_src"])} 个（{"、".join(r["only_src"][:3])}）')
        if r.get('only_dst'):
            bits.append(f'profile 多 {len(r["only_dst"])} 个')
        bad.append({
            'kind': '源码改了但没 deploy',
            'claim': f'{name}：' + '；'.join(bits),
            'actual': f'跑 `lab deploy {name}` 同步（改完还要重启 DSH 才加载新模块）',
            'where': f'node_modules/{name}',
        })
    return bad


def check_pre_freshness() -> list[dict]:
    """第 16 组：`lab pre` 的验收期限有没有到期。

    用户 2026-11-09（m16875）：「一个月太久了，两天吧。这种验证式的期限不要
    定太久。太长了。」→ `lab pre` 的判据是「**两天内没被用过 → 判它没通过，
    砍掉**」。

    为什么要有这一组：期限只写在 docstring 和输出末尾，**没人判它到期没有**。
    两天「没被用」这件事，只有查调用日志才知道——这就是「记忆变流程」：
    光写一句「两天后回看」等于没写。

    数据源 `~/.dsh/lab-calls.log`（JSONL，`{"at": ISO, "cmd": "pre"}`），
    由 `lab.py` 在入口处写，所以**本次 `lab pre` 自己那条也在里面** →
    必须排除最近 60 秒内的记录，否则它永远绿。
    """
    log = Path.home() / '.dsh' / 'lab-calls.log'
    if not log.exists():
        return []
    now = datetime.now()
    latest = None
    saw_pre = False          # 日志里出现过 pre 记录（哪怕全在 60 秒内）
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        if '"pre"' not in line:
            continue
        try:
            rec = json.loads(line)
            if rec.get('cmd') != 'pre':
                continue
            t = datetime.fromisoformat(rec['at'])
        except Exception:  # noqa: BLE001
            continue
        saw_pre = True
        if (now - t).total_seconds() < 60:
            continue        # 本次自己，不算「用过」
        if latest is None or t > latest:
            latest = t
    if latest is None:
        # 2026-11-19 修（盲审第 7 条）：第一次跑 `lab pre` 时，日志里唯一一条 pre 记录
        # 就是本次（上面 60 秒那条把它排除了）→ 走到这里报「从没被用过」**硬漂移**，
        # 而 `lab pre` 自己会因此返回 1。这条检查本来是用来砍掉没人用的工具的，
        # 现在恰好在「第一次被使用」时把使用者判成失败。
        # 区分开：日志里一条 pre 都没有 = 真没用过（该报）；有但全在 60 秒内 = 刚开始用，
        # 期限还没开始计时，不该判失败。
        if saw_pre:
            return []
        return [{'kind': 'lab pre 从没被用过',
                 'claim': '除本次外，调用日志里没有任何 lab pre 记录',
                 'actual': '两天期限从没开始计时——它连一次都没被用',
                 'where': '~/.dsh/lab-calls.log'}]
    hours = (now - latest).total_seconds() / 3600
    if hours > 48:
        return [{'kind': 'lab pre 超期未用',
                 'claim': f'上次用 lab pre 是 {latest:%Y-%m-%d %H:%M}（{hours:.0f} 小时前）',
                 'actual': '超过 48 小时 → 按 2026-11-09 用户定的判据，它没通过，该砍掉',
                 'where': '~/.dsh/lab-calls.log'}]
    return []


def check_plugin_versions() -> list[dict]:
    """自研插件的版本号有没有跟上来（2026-11-18 加，起因见决策日志 ver-drift-20261118）。

    三条判据，按信号强度从强到弱：
      ① CHANGELOG 最新标题的版本 ≠ package.json 的 version → **明确矛盾**（升了没改，或改漏了一处）
      ② lib/ 里最新 mtime 比 package.json 新超过 1 天 → 提示（可能改了代码没升版本，也可能是改注释）
      ③ 自研插件没有 CHANGELOG.md → 提示（新插件要补）

    为什么要有这一组：用户 2026-11-18 指出「以前每次插件更新，多多少少都会版本型号没更新过来，
    不止一回了」。路线库「改插件」域的判据写着「插件页能看到新版本号（不是只有文件改了）」，
    但那句话**只是给人读的，没有任何工具去验**——这一组就是把它变成机器能验的。
    """
    bad = []
    try:
        import deploy as dep
    except Exception:  # noqa: BLE001
        return bad

    for name in dep.SELF_BUILT:
        d = ROOT / name
        pkg_p = d / 'package.json'
        if not pkg_p.exists():
            continue
        try:
            ver = (json.loads(read(pkg_p)) or {}).get('version') or ''
        except Exception:  # noqa: BLE001
            continue
        if not ver:
            continue

        # ① CHANGELOG 最新标题的版本
        cl_p = d / 'CHANGELOG.md'
        if cl_p.exists():
            cl_ver = ''
            for line in (read(cl_p) or '').splitlines():
                if line.startswith('##'):
                    m = re.search(r'v?(\d+\.\d+\.\d+)', line)
                    if m:
                        cl_ver = m.group(1)
                    break
            if cl_ver and cl_ver != ver:
                bad.append({
                    'kind': '版本号与 CHANGELOG 不一致',
                    'claim': f'`{name}` 的 package.json 写 {ver}',
                    'actual': f'CHANGELOG 最新标题是 {cl_ver}',
                    'where': f'{name}/CHANGELOG.md',
                })
        else:
            bad.append({
                'kind': '自研插件缺 CHANGELOG',
                'claim': f'`{name}` 是自研插件（SELF_BUILT 里的一项）',
                'actual': f'没有 {name}/CHANGELOG.md',
                'where': name,
                'soft': True,
            })

        # ④ 我的能力清单.md 里写没写对（2026-11-18 加）
        #    2026-11-18 同一件事第二次：①②③ 全报 OK，但能力清单里 4 处版本号是旧的
        #    （memory 0.6.17 / evolve 0.1.7 / stickers 0.1.3 / workflow 0.3.16），我手工翻出来的。
        #    只查 SELF_BUILT：外部插件（cc-safety-net / dshmarket）的版本我控制不了，
        #    那几行是参考资料不是承诺，跟着 npm 升级去改文档没有收益。
        cap_p = ARCH / '我的能力清单.md'
        if cap_p.exists():
            try:
                cap_text = read(cap_p) or ''
            except Exception:  # noqa: BLE001
                cap_text = ''
            m = re.search(r'\|\s*`' + re.escape(name) + r'`\s*\|\s*\**(\d+\.\d+\.\d+)\**', cap_text)
            if m and m.group(1) != ver:
                bad.append({
                    'kind': '能力清单里的版本号过期',
                    'claim': f'`架构文档/我的能力清单.md` 写 `{name}` 是 {m.group(1)}',
                    'actual': f'package.json 是 {ver}',
                    'where': '架构文档/我的能力清单.md',
                    'soft': True,
                })

        # ② 代码比 package.json 新（弱信号，只提示）
        lib = d / 'lib'
        if lib.is_dir():
            try:
                newest = max((p.stat().st_mtime for p in lib.rglob('*') if p.is_file()), default=0)
                pkg_m = pkg_p.stat().st_mtime
            except OSError:
                newest = pkg_m = 0
            if newest and pkg_m and newest > pkg_m + 86400:
                days = int((newest - pkg_m) / 86400)
                bad.append({
                    'kind': '代码比 version 新（可能忘升版本）',
                    'claim': f'`{name}` 的 package.json 还写着 {ver}',
                    'actual': f'lib/ 里最新改动比 package.json 新 {days} 天',
                    'where': f'{name}/lib/',
                    'soft': True,
                })
    return bad


def check_dir_classification() -> list[dict]:
    """现役/历史目录分类表有没有跟上磁盘（2026-11-18 加，第二版）。

    只查一件事：顶层目录没在分类表里登记 → soft（新目录出现时要归类）。

    2026-11-18 第二版：**删掉了原来那条「现役目录里 mtime > 90 天且零引用 → 可能已退场」**。
    原因是判据反了——用户 m17959 原话：「这种一直没有利用的都算现役，直接留在现役的
    目录当中就可以。保不起哪天要用到。你要是把它归到历史那一档，那就有点麻烦了。」
    「没用过」不等于「该退场」；归历史有成本（要挪、要改路径），所以默认留现役。
    退场的唯一理由是「明确被替代」（06-design 是现役 SKILL.md 的旧副本）或「明确废弃」
    （10-audit lab 里无对应）——这两个机器判不了，要我看 / 要用户拍板。

    所以这一组只负责**目录级**的变化（新目录出现），不负责**文件级**的老化。
    """
    bad = []
    plan_p = ARCH / '目录分类.json'
    if not plan_p.exists():
        return [{
            'kind': '没有目录分类表',
            'claim': '现役/历史目录分类表应该存在',
            'actual': f'{plan_p} 不存在 → 新目录没人归类',
            'where': '架构文档/目录分类.json',
            'soft': True,
        }]
    try:
        plan = json.loads(read(plan_p)) or {}
    except Exception as e:  # noqa: BLE001
        return [{
            'kind': '目录分类表读不了',
            'claim': '目录分类.json 应该是合法 JSON',
            'actual': str(e),
            'where': '架构文档/目录分类.json',
        }]

    known: dict[Path, str] = {}
    for cls, m in plan.items():
        if cls.startswith('_') or not isinstance(m, dict):
            continue
        for p in m:
            known[Path(p)] = cls

    # ① 顶层目录没归类
    try:
        tops = [p for p in ROOT.iterdir() if p.is_dir()]
    except OSError:
        tops = []
    for d in tops:
        if d.name.startswith('.git') or d.name == '.dsh':
            continue
        if d not in known:
            bad.append({
                'kind': '目录没归类',
                'claim': '每个顶层目录都该在 目录分类.json 里标明现役/历史',
                'actual': f'`{d.name}` 不在表里 → 它是现役还是历史？',
                'where': '架构文档/目录分类.json',
                'soft': True,
            })

    # 原第 ② 条「现役目录里 mtime > 90 天且零引用 → 可能已退场」已于 2026-11-18 删除：
    # 用户 m17959「这种一直没有利用的都算现役……你要是把它归到历史那一档，那就有点麻烦了。」
    # 「没用过」不等于「该退场」。文件级的老化由人判断（见 架构文档/文件分类.json），机器只查目录级。
    return bad


def check_requirement_freshness() -> list[dict]:
    """需求清单多久没整理过了（2026-11-18 加，第 19 组）。

    只查「多久没看」，查不了「漏了哪条」——新要求进表仍要靠人。
    判据：文件头的 `最近一次整理 YYYY-MM-DD` 距今超过 30 天 → soft。

    为什么是 30 天：这份表是「大改动前逐条对照」用的。一个月都没整理过，
    说明这段时间用户提的要求（全进了记忆）没进这张表——它就退化成快照了。
    这正是用户 2026-11-18 批评的那个病：「需要长期维护的当一次性的做」。
    """
    p = ARCH / '需求清单.md'
    if not p.exists():
        return [{'kind': '需求清单不在',
                 'claim': str(p),
                 'actual': '文件不存在',
                 'where': '架构文档/',
                 'soft': True}]
    text = read(p)
    m = re.search(r'最近一次整理\s*(\d{4})-(\d{2})-(\d{2})', text)
    if not m:
        return [{'kind': '需求清单没有整理日期',
                 'claim': '文件头要写 `最近一次整理 YYYY-MM-DD`',
                 'actual': '找不到这个格式的日期',
                 'where': '架构文档/需求清单.md',
                 'soft': True}]
    try:
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return [{'kind': '需求清单日期非法',
                 'claim': m.group(0),
                 'actual': '日期解析失败',
                 'where': '架构文档/需求清单.md',
                 'soft': True}]
    days = (datetime.now() - d).days
    if days > 30:
        return [{'kind': '需求清单可能漏了新要求',
                 'claim': '最近一次整理 {0:%Y-%m-%d}'.format(d),
                 'actual': '{0} 天没整理（阈值 30 天）'.format(days),
                 'where': '架构文档/需求清单.md',
                 'soft': True}]
    return []


GROUPS = [
    ('lab 子命令引用', check_lab_refs),    ('绝对路径引用', check_paths),
    ('计数断言', check_counts),
    ('文档互引', check_cross_docs),
    ('@local 插件装机核对', check_local_plugins),
    ('README 覆盖 lab 子命令', check_readme_coverage),
    ('反向差集：能力有、机制图没写', check_capability_reverse),
    ('测试覆盖：命令有、测试没有', check_test_coverage),
    ('候选路线库覆盖：能力有、路线库里没有', check_route_coverage),
    ('规则触发覆盖：规则有、触发信号没有', check_rule_coverage),
    ('插件与脚本覆盖：能力有、路线库里没有', check_asset_route_coverage),
    ('知识源路径：tier 指到的地方还在不在', check_knowledge_paths),
    ('能力指纹：上次审 §0.1 之后能力变没变', check_capability_fingerprint),
    ('路线清单体检：重复/死路径/空壳/代号（判臃肿，不判条数）', check_route_hygiene),
    ('自研插件部署：源码改了但没 lab deploy', check_deploy_sync),
    ('lab pre 时效：两天没被用过就该砍', check_pre_freshness),
    ('自研插件版本号：CHANGELOG 与 package.json 一致', check_plugin_versions),
    ('目录分类：新目录没归类', check_dir_classification),
    ('需求清单时效：多久没整理过', check_requirement_freshness),
]


BLOCK_LOG = ROOT / '架构文档' / 'selfcheck-拦截记录.jsonl'


def _log_block(hard_total: int, report) -> None:
  """2026-11-18 加：selfcheck 跑了 664 次，从没记过「它拦住了什么」。

  拦住只打在屏幕上，关掉窗口就没了 —— 于是「这检查到底有没有用」永远答不出来。
  这里把每次有硬漂移的拦截落一行，事后能统计「哪个 kind 反复出现、哪个从没出现」。
  """
  try:
    BLOCK_LOG.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for g in report:
      for it in g['items']:
        if it.get('soft'):
          continue
        items.append({'group': g['group'], 'kind': it.get('kind'),
                      'claim': it.get('claim'), 'where': it.get('where')})
    rec = {'at': datetime.now().isoformat(timespec='seconds'),
           'hard': hard_total, 'items': items[:20]}
    with BLOCK_LOG.open('a', encoding='utf-8') as f:
      f.write(json.dumps(rec, ensure_ascii=False) + '\n')
  except Exception:
    pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='机制随能力漂移检测')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--only', type=int, help='只跑第 N 组（1 起）')
    ap.add_argument('--update-fingerprint', action='store_true',
                    help='审完 §0.1 后调用：把当前能力状态记为新的基准（第 13 组用）')
    a = ap.parse_args(argv)
    READ_FAILS.clear()  # 每次运行从零开始记，别把上一次的算进来

    if a.update_fingerprint:
        cur = _capability_fingerprint()
        FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        FINGERPRINT_FILE.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'能力指纹已更新 → {FINGERPRINT_FILE}')
        print(f'  插件 {len(cur["plugins"])} 个 / lab 子命令 {len(cur["lab_cmds"])} 个'
              f' / 规则 {len(cur["rules"])} 条 / tools 脚本 {len(cur["tools"])} 个')
        return 0

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
    # 2026-11-19 加：有文档读不到，算漂移。
    # 它们的相关检查本轮全被跳过——「没查到问题」不等于「没问题」。
    if READ_FAILS:
        print()
        print(f'⚠️ 有 {len(READ_FAILS)} 份文档没读到，与它们相关的检查本轮全部跳过：')
        for s in READ_FAILS[:10]:
            print(f'   {s}')
        if len(READ_FAILS) > 10:
            print(f'   …… 还有 {len(READ_FAILS) - 10} 份')
        print('   读不到不等于没问题：先确认这些文件该不该在。')
        hard_total += len(READ_FAILS)
    if hard_total:
        _log_block(hard_total, report)
    return 0 if hard_total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
