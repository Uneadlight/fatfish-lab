#!/usr/bin/env python3
"""候选路线库体检：用真实调用日志找「假域 / 空命中 / 高频低权」。

**为什么不定时**（2026-11-07 用户 m12153）：
    「每周时间间隔太长了。你每天的变化都是日新月异的。你想想啊，时间应该定为多少？」

所以判据是**事件累积**，不是日历：
    自上次体检后，`tier-calls.jsonl` 新增 ≥ 10 条  或  `lab-calls.log` 新增 ≥ 100 行
10 条 tier ≈ 10 个任务 ≈ 2–4 天；忙的时候天天触发，闲的时候自动拉长。

**判的是「假」和「歪」，不是「漏」**（漏由 selfcheck 第 9 组管）：
    假域      —— 一次都没被任何任务命中过
    空命中    —— 任务描述匹配不到任何域（说明真缺，或词库不够）
    高频低权  —— 日志里高频调用的 subcommand，在路线库的路线里很少被点名

用法：
  py lab.py health            # 看要不要体检 + 需要就跑
  py lab.py health --force    # 强制跑，不看闸门
  py lab.py health --json     # 只出机器可读结果
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 懒加载：build() 里要用当前的 PATH_OPTIONS 重算「现在还是不是空命中」。
# 不在模块顶层 import，是因为它自己会去 import tier_domains（数据），
# 而这个模块的旧版本曾经因为正则解析空源静默空转过两天——保持依赖方向单一。
_tier_matcher = None


def _matcher():
    global _tier_matcher
    if _tier_matcher is None:
        import tier_matcher as _m  # noqa: PLC0415
        _tier_matcher = _m
    return _tier_matcher

ROOT = Path(r'D:\work')
LAB_DIR = ROOT / 'tools' / 'lab'
DSH_HOME = Path.home() / '.dsh'
CALL_LOG = DSH_HOME / 'lab-calls.log'
TIER_CALLS = DSH_HOME / 'tier-calls.jsonl'
STATE = DSH_HOME / 'route-health.json'
REPORT = ROOT / '架构文档' / '路线库体检报告.md'

# 闸门：自上次体检后增量达到任一条件就建议跑
GATE_TIER_CALLS = 10
GATE_CALL_LINES = 100
# 判「假域」的最低样本：少于这个数就只报「样本不足」，不报结论
# —— 2026-11-07 自己踩的：5 条记录报出 19 个假域，它们根本不是假域，是我把样本量不足当成了结论
MIN_SAMPLE_FOR_FAKE = 20


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def save_state(st: dict) -> None:
    try:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass


def count_lines(p: Path) -> int:
    try:
        with p.open('rb') as f:
            return sum(1 for _ in f)
    except Exception:  # noqa: BLE001
        return 0


def gate() -> tuple[bool, str]:
    """要不要现在体检。返回 (是否, 原因)。"""
    st = load_state()
    tier_n = count_lines(TIER_CALLS)
    call_n = count_lines(CALL_LOG)
    d_tier = tier_n - int(st.get('tier_lines', 0))
    d_call = call_n - int(st.get('call_lines', 0))
    if d_tier >= GATE_TIER_CALLS:
        return True, f'自上次体检新增 {d_tier} 次 lab tier（阈值 {GATE_TIER_CALLS}）'
    if d_call >= GATE_CALL_LINES:
        return True, f'自上次体检新增 {d_call} 行 lab 调用（阈值 {GATE_CALL_LINES}）'
    return False, f'自上次体检：tier +{d_tier} / 调用 +{d_call}，都没到闸门'


def parse_domains() -> tuple[list[str], list[dict]]:
    """从 tier_domains.PATH_OPTIONS 里取全部域；从 tier-calls.jsonl 里取真实命中记录。

    2026-11-13 修：原来用正则从 **tier.py 源码**里抓 `"domain": "…"`——11-11 搬家后
    域名在 tier_domains.py，正则对着空源返回 0 个域，「假域」检查静默空转了两天
    （domains_total=0 → 没有任何域会被判假）。抓到就修，别等它自己烂穿（mem_mw0vuamy）。
    """
    if str(LAB_DIR) not in sys.path:
        sys.path.insert(0, str(LAB_DIR))
    from tier_domains import PATH_OPTIONS  # noqa: PLC0415
    all_domains = [o['domain'] for o in PATH_OPTIONS]

    calls = []
    try:
        for line in TIER_CALLS.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return all_domains, calls


def parse_calls() -> list[str]:
    """lab-calls.log 里的 subcommand 序列（只到命令名，日志本身不含参数）。"""
    out = []
    try:
        for line in CALL_LOG.read_text(encoding='utf-8').splitlines():
            try:
                out.append(json.loads(line).get('cmd', ''))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return [c for c in out if c]


MIN_PICKS_FOR_UNUSED = 20


def load_picks() -> list:
    """读 tier-picks.jsonl（lab tier --used 追加的选路记录）。坏行跳过，不抛。"""
    import json
    from pathlib import Path
    fp = Path(r'D:\work\架构文档\路线库配套\选路记录.jsonl')
    if not fp.is_file():
        return []
    out = []
    for line in fp.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def picks_report() -> dict:
    """零选用路线：库里全部 vs 我实际记过 used 的。

    2026-11-15 用户 m04361 定：样本不够就只报样本数、不给结论——
    跟假域的 MIN_SAMPLE_FOR_FAKE 是同一课，小样本上的「没用」多是「还没遇到那类任务」。
    """
    try:
        import tier_domains as T
    except Exception:
        return {'sample': 0, 'unused': None, 'total': 0}
    picks = load_picks()
    used = set()
    for rec in picks:
        u = str(rec.get('used') or '').strip()
        if not u:
            continue
        if '/' in u:
            d, c = u.split('/', 1)
            used.add((d.strip(), c.strip().upper()))
        else:
            used.add(('', u.upper()))
    total = 0
    unused = []
    for d in T.PATH_OPTIONS:
        for r in d['routes']:
            total += 1
            code = str(r[0]).upper()
            if (d['domain'], code) not in used and ('', code) not in used:
                unused.append('%s / %s — %s' % (d['domain'][:16], r[0], str(r[1])[:38]))
    if len(picks) < MIN_PICKS_FOR_UNUSED:
        unused = None
    return {'sample': len(picks), 'unused': unused, 'total': total}

def build() -> dict:
    all_domains, calls = parse_domains()
    used = {}
    empty = 0
    for c in calls:
        ds = c.get('domains') or []
        if not ds:
            empty += 1
        for d in ds:
            used[d] = used.get(d, 0) + 1

    # 假域：有域、但所有 tier 记录里从没出现过
    # **样本不够就不报**——5 条记录能报出 19 个「假域」，那不是假域，是样本不足
    if len(calls) < MIN_SAMPLE_FOR_FAKE:
        fake = None
    else:
        fake = [d for d in all_domains if used.get(d, 0) == 0]

    # 空命中：任务描述一个域都没匹配上
    # 2026-11-19 加第二栏「现在仍然空」：`tier-calls.jsonl` 记的是**当时**的结果，
    # 后来补过词的记录不会自己变好。只看 `empty_tasks` 会得出「有 146 条要补词」的
    # 错结论——2026-11-19 实测 7 条历史空命中，现在重算**全部命中**（除「今天天气不错」
    # 这种本来就不是任务的话）。所以必须用当前的 PATH_OPTIONS 重算一遍。
    empty_tasks = [c.get('task', '') for c in calls if not (c.get('domains') or [])]
    empty_now = []
    for _t in empty_tasks:
        try:
            if not _matcher().path_options(_t):
                empty_now.append(_t)
        except Exception:  # noqa: BLE001 — 重算失败不该让整份报告挂掉
            empty_now.append(_t)

    # 高频低权：日志里出现 ≥8 次的 subcommand，在 tier_domains.py 的 routes 里被点名的次数
    # 2026-11-15 修：路线数据 2026-11-11 已从 tier.py 搬到 tier_domains.py，这里原来还在读
    # tier.py 壳文件（只有 import、不含 routes）→ 整列的「提及次数」几乎全是 0-2，表是失真的。
    tier_src = (LAB_DIR / 'tier_domains.py').read_text(encoding='utf-8')
    freq = {}
    for c in parse_calls():
        freq[c] = freq.get(c, 0) + 1
    hot = [(c, n, len(re.findall(rf'\blab\s+{re.escape(c)}\b', tier_src)))
           for c, n in freq.items() if n >= 8]
    hot.sort(key=lambda x: -x[1])

    # 经验链（2026-11-13 接上）：链库和域表同生共死——域改名/删了，链的 tag 就悬空。
    # 链库不存在 = 正常（还没回写过任何链），不报错。
    try:
        import tier_matcher as _tm
        chains = _tm.load_chains()
        chain_info = {'total': len(chains),
                      'dead': _tm.chain_hygiene(),
                      'deviated': {n: c.get('deviated', 0) for n, c in chains.items()
                                   if c.get('deviated')}}
    except Exception as e:  # noqa: BLE001
        chain_info = {'total': -1, 'dead': [f'链库读取失败：{e}'], 'deviated': {}}

    return {
        'gate': gate()[0],
        'gate_reason': gate()[1],
        'tier_calls': len(calls),
        'domains_total': len(all_domains),
        'domains_used': len(used),
        'fake_domains': fake,
        'empty_hits': empty,
        'empty_tasks': empty_tasks[-10:],
        'empty_now': empty_now[-10:],
        'empty_now_total': len(empty_now),
        'hot_low_weight': hot,
        'chains': chain_info,
        'picks': picks_report(),
    }


def render(r: dict) -> str:
    L = []
    L.append('# 候选路线库体检报告\n')
    L.append('> 动手补库前先看 [路线库维护手册.md](路线库维护手册.md)：域才是触发单位（路线不是）、只加 route 不补 words 等于白加、补词必须确认落进 `words` 字段、空命中率有下限。\n')
    L.append(f'- 生成时间：{__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    L.append(f'- 闸门：{r["gate_reason"]}')
    L.append(f'- 样本：{r["tier_calls"]} 次 lab tier 调用 / {r["domains_total"]} 个域\n')

    L.append('## 一、假域（有域、但从没被任何任务命中过）\n')
    if r['fake_domains'] is None:
        L.append(f'**样本不足，不判**（只有 {r["tier_calls"]} 条记录，判假域至少要 {MIN_SAMPLE_FOR_FAKE} 条）。')
        L.append('')
        L.append('> 为什么设门槛：2026-11-07 第一次跑、只有 5 条记录时报了 19 个「假域」——它们根本不是假域，是样本量不足。')
    elif r['fake_domains']:
        L.append(f'共 **{len(r["fake_domains"])}** 个。它们要么是造出来的需求，要么 words 写得太窄：\n')
        for d in r['fake_domains']:
            L.append(f'- `{d}`')
    else:
        L.append('无。所有域都被命中过。')
    L.append('')

    L.append('## 二、空命中（任务描述匹配不到任何域）\n')
    L.append(f'{r["empty_hits"]} / {r["tier_calls"]} 次任务匹配不到域。')
    L.append(f'其中 **现在重算仍然匹配不到** 的：**{r.get("empty_now_total", "?")}** 条（其余是当时词不够、后来补上了——历史记录不会自己变好，所以必须重算）。')
    if r.get('empty_now'):
        L.append('\n现在仍然空（只列最近 10 条，这才是真要补的）：\n')
        for t in r['empty_now']:
            L.append(f'- {t}')
        L.append('\n> 判据：能出现在这里的，才是「我描述任务用的词不在任何域的 words 里」。')
        L.append('> **处理方式**：挑一条 → 判断是「加 words」还是「加域」→ 改 `tools/lab/tier_domains.py`（数据）→')
        L.append('> 用 `tier_matcher.path_options("<那条原话>")` 确认能命中（**别看 `lab tier` 的「命中：无」，那是规则信号不是域命中**）。')
    if r['empty_tasks']:
        L.append('\n最近 10 条历史空命中（可能已修好）：\n')
        for t in r['empty_tasks']:
            L.append(f'- {t}')
    L.append('')

    L.append('## 三、高频低权（日志里常调，路线库里少提）\n')
    if r['hot_low_weight']:
        L.append('| subcommand | 日志次数 | 路线库提及 | 判断 |')
        L.append('|---|---|---|---|')
        for c, n, refs in r['hot_low_weight']:
            judge = '该加权重' if refs <= 2 else '已覆盖'
            L.append(f'| `lab {c}` | {n} | {refs} | {judge} |')
        L.append('\n> 判据：调用频率高但路线库里只是边缘提及，说明「我实际这么干活，但规划时没想到这条路」。')
    else:
        L.append('无（没有单个 subcommand 超过 8 次）。')
    L.append('')

    L.append('## 四、还不能自动判的（需要我或用户拍板）\n')
    L.append('- **假路线**（域命中过、但某条代号从没被选）：经验链上线后（2026-11-13）')
    L.append('  「组装+战绩」有了，但**单条路线的选择票**还没有——要判「域里哪条路是死的」')
    L.append('  仍需 tier-calls 加选路字段，那是下一步。')
    L.append('- **歪**（选了但结果不好）：链有偏离票可看，单路线的结果仍缺一段数据。')
    L.append('')

    ch = r.get('chains') or {}
    L.append('## 五、经验链（验证过回写的战绩，`lab tier --chain record` 写入）\n')
    if ch.get('total', -1) < 0:
        L.append('链库读取失败（见 error）：' + '；'.join(ch.get('dead', [])))
    elif ch.get('total', 0) == 0:
        L.append('还没有回写过经验链——正常，链只在**任务真验证完**后才写（闸门不收自述）。')
    else:
        L.append(f'- 共 {ch["total"]} 条；死链（tag 悬空）{len(ch.get("dead") or [])} 条；'
                 f'被偏离 {sum((ch.get("deviated") or {}).values())} 票。')
        for msg in ch.get('dead') or []:
            L.append(f'- ❌ {msg}')
        for nm, n in (ch.get('deviated') or {}).items():
            L.append(f'- ⚠️ 链「{nm}」被偏离 {n} 次——连续被越过的该重验或直接删（偏离=探索信号，不是链的错）')
    L.append('')
    L.append('## 五、零选用路线（我记过的 used vs 库里全部）\n')
    pk = r.get('picks') or {}
    if pk.get('unused') is None:
        L.append(f"**样本不足，不判**（只有 {pk.get('sample', 0)} 条 `lab tier --used` 记录，判零选用至少要 {MIN_PICKS_FOR_UNUSED} 条）。")
        L.append('')
        L.append('> 记法：选好路后 `lab tier --used 域/代号` 追一行，不改历史记录。')
    elif pk.get('unused'):
        L.append(f"共 **{len(pk['unused'])}** 条从没被选用过（总 {pk.get('total', 0)} 条）——不是马上删，是下次遇到同类任务时优先试它们：")
        L.append('')
        for it in pk['unused'][:40]:
            L.append(f'- `{it}`')
        if len(pk['unused']) > 40:
            L.append(f"- ……还有 {len(pk['unused']) - 40} 条")
    else:
        L.append('所有路线都至少被选用过一次。')
    L.append('')
    L.append('---\n')
    L.append('**怎么用**：看「假域」和「空命中」两张表，判断哪几处该改 words / 合并域 / 加新域；')
    L.append('看完把结论写回 `tier_domains.py`（数据）或 `tier_matcher.py`（逻辑），然后跑 `lab selfcheck` 确认没引入漂移。')
    return '\n'.join(L)




FIELD_NOTES = Path(r'D:\work\架构文档\路线库配套\路线心得.md')


def render_fieldnotes() -> str:
    """把 tier-picks.jsonl 里带 note 的记录按 域/路线 聚合成可翻看的 md。

    用户 2026-11-15 提的想法：给候选路线库配一份「用它的时候怎么想」的记录。
    这里不做成要我手写的日记——只把 --used 时顺手写的一句心得汇总起来，
    没有 note 的选路记录不进来（顺手用一条是噪声，意外才是信息）。
    """
    picks = load_picks()
    groups = {}
    for rec in picks:
        used = str(rec.get('used') or '').strip()
        note = str(rec.get('note') or '').strip()
        if not used or not note:
            continue
        if '/' in used:
            dom, code = used.split('/', 1)
        else:
            dom, code = '（未写域）', used
        groups.setdefault((dom.strip(), code.strip().upper()), []).append(
            (str(rec.get('at') or '')[:10], note, str(rec.get('task') or '')[:40]))
    L = []
    L.append('# 候选路线库 · 使用心得')
    L.append('')
    L.append('> 自动生成，别手改。来源：`lab tier --used 域/代号 --note "一句"`（`架构文档\路线库配套\选路记录.jsonl`）。')
    L.append('> 只收「这条路线让我意外」的心得；顺手用一条不记，免得里面积满噪声。')
    L.append('> 「当前阶段认知」= 我对「如何使用候选路线库」**目前最新的理解**（用户 2026-11-15 定）：写新的一条即覆盖旧的，旧的自动收到折叠区。')
    L.append('')
    L.append(f'- 生成时间：{__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}')
    L.append(f'- 有心得的路线条数：{len(groups)}')
    reviews = [r for r in picks if str(r.get('event') or '') == 'review' and str(r.get('note') or '').strip()]
    L.append('')
    L.append('## 当前阶段认知（只读最新这一条）')
    L.append('')
    if reviews:
        cur = reviews[-1]
        L.append(f"**{str(cur.get('at') or '')[:10]}** {str(cur.get('note') or '').strip()}")
        older = reviews[:-1]
        if older:
            L.append('')
            L.append('<details><summary>更早的阶段认知（按需翻，平时不用读）</summary>')
            L.append('')
            for rec in older[-8:][::-1]:
                L.append(f"- {str(rec.get('at') or '')[:10]} {str(rec.get('note') or '').strip()}")
            L.append('')
            L.append('</details>')
    else:
        L.append('（还没有阶段性描述。用完一轮路线库后：`lab tier --note "我这阶段怎么用它的"`）')
    L.append('')

    L.append('')
    if not groups:
        L.append('还没有。跑完任务觉得某条路线「比想的快/比想的坑」时，用 `--note` 记一句。')
        return '\n'.join(L)
    for (dom, code) in sorted(groups):
        items = groups[(dom, code)]
        L.append(f'## {dom} / {code}')
        L.append('')
        L.append(f'被记 {len(items)} 次：')
        L.append('')
        for at, note, task in items[-8:]:
            tail = f'（任务：{task}）' if task else ''
            L.append(f'- {at} {note}{tail}')
        L.append('')
    return '\n'.join(L)

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    force = '--force' in argv
    if '--notes' in argv:
        # 只生成心得汇总，不跑体检（两件事，别混）
        text = render_fieldnotes()
        try:
            FIELD_NOTES.write_text(text, encoding='utf-8')
            print(f'[OK] 心得汇总写到 {FIELD_NOTES}')
        except Exception as e:  # noqa: BLE001
            print(text)
            print(f'[WARN] 写文件失败：{e}')
        return 0
    as_json = '--json' in argv

    ok, why = gate()
    if not (ok or force):
        if as_json:
            print(json.dumps({'run': False, 'reason': why}, ensure_ascii=False))
        else:
            print(f'[SKIP] 还没到体检时机：{why}')
            print('       （判据是增量不是日历：tier +{}/{} 或 调用 +{}/{}）'.format(
                GATE_TIER_CALLS, GATE_TIER_CALLS, GATE_CALL_LINES, GATE_CALL_LINES))
        return 0

    r = build()
    if force:
        r['gate_reason'] = '手动强制（--force），不看闸门'
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        text = render(r)
        try:
            REPORT.write_text(text, encoding='utf-8')
            print(f'[OK] 报告写到 {REPORT}')
        except Exception as e:  # noqa: BLE001
            print(f'[WARN] 写报告失败（{e}），只在终端输出：')
            print(text)
        print(f'  样本：{r["tier_calls"]} 次 tier / {r["domains_used"]}/{r["domains_total"]} 个域被命中')
        fake_n = '样本不足' if r["fake_domains"] is None else len(r["fake_domains"])
        print(f'  假域 {fake_n} / 空命中 {r["empty_hits"]} / 高频低权 {len(r["hot_low_weight"])}')

    save_state({'tier_lines': count_lines(TIER_CALLS), 'call_lines': count_lines(CALL_LOG),
                'at': __import__('datetime').datetime.now().strftime('%Y-%m-%dT%H:%M:%S')})
    return 0


if __name__ == '__main__':
    sys.exit(main())
