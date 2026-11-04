"""从 bili.log 读每次请求的 token 用量，按时间窗口算成本。

为什么从日志读而不是调 acp_cache：acp_cache 一次输出 37K 字符，只为看"这一小时花了多少"不值。
bili.log 里每轮都有一行现成的 [acp-usage] input=... cached=...，4.9 MB / 2.8 万行，一次扫 0.2 秒。

单价用官方口径（元/百万 token，北京时间）：
  高峰 = 周一至周五 9:00–12:00、14:00–18:00（不含法定节假日）
  空闲 = 其余全部
  flash 命中 0.02/0.04 · 未命中 1.00/2.00 · 输出 4.00/8.00

局限（写在输出里）：bili.log 只记 input 和 cached，不记 output。
output 约占总 token 的 0.3%（今天实测 1513.93M input / 4.99M output），所以只算 input 的误差在 1% 量级。
"""
import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

LOG = Path.home() / '.local' / 'state' / 'billion-context' / 'bili.log'

LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+\s+\[\w+\].*?\[acp-usage\]\s+input=(\d+)\s+cached=(\d+)'
)
# bili 的每行 usage 带会话标记，格式 [sess=session-<uuid>]。
# 有这个就能回答「当前这轮/这个会话花了多少」，而不是只能看一个时间窗口。
SESS_RE = re.compile(r'\[sess=([^\]]+)\]')

# (空闲, 高峰) 元/百万 token
PRICE_HIT = (0.02, 0.04)
PRICE_MISS = (1.00, 2.00)
PRICE_OUT = (4.00, 8.00)


def is_peak(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    h = dt.hour
    return (9 <= h < 12) or (14 <= h < 18)


def cost_of(inp: int, cached: int, peak: bool) -> float:
    i = 1 if peak else 0
    hit = cached
    miss = max(0, inp - cached)
    return hit / 1e6 * PRICE_HIT[i] + miss / 1e6 * PRICE_MISS[i]


def load(since: datetime | None = None) -> list[dict]:
    """读 bili.log 和 bili.log.old（滚动日志）里所有 [acp-usage] 行。

    必须读 .old：bili.log 只保留最近一段时间，昨天的请求在 .old 里。
    """
    rows = []
    logdir = LOG.parent
    for name in ('bili.log.old', 'bili.log'):        # 先旧后新，时间顺序自然
        p = logdir / name
        if not p.exists():
            continue
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                m = LINE_RE.match(line)
                if not m:
                    continue
                try:
                    t = datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    continue
                if since and t < since:
                    continue
                inp = int(m.group(2))
                cached = int(m.group(3))
                sm = SESS_RE.search(line)
                rows.append({'t': t, 'in': inp, 'cached': cached, 'peak': is_peak(t),
                             'sess': sm.group(1) if sm else ''})
    rows.sort(key=lambda r: r['t'])
    return rows


def report_session(rows: list[dict], sess: str) -> None:
    """一个会话内部的成本视图——回答「这一轮花了多少、比上一轮贵几倍」。

    为什么单独一个视图：`--hours` 的汇总回答不了「刚才这一轮多少钱」，
    而会话内相邻请求的比值可以直接暴露「上下文炸了」——同一次对话里
    第 1 次和第 50 次请求的成本可能差 10 倍以上。
    """
    total_in = sum(r['in'] for r in rows)
    total_cached = sum(r['cached'] for r in rows)
    total_cost = sum(cost_of(r['in'], r['cached'], r['peak']) for r in rows)
    hit_pct = (total_cached / total_in * 100) if total_in else 0
    print(f'[COST] 会话 {sess}')
    print(f'  {len(rows)} 次请求 · input {total_in:,} tok / cached {total_cached:,} tok（命中 {hit_pct:.1f}%）')
    print(f'  估算合计 ¥{total_cost:.4f}（只算 input；绝对值偏低约 2.4 倍，看相对）')
    print()
    show = rows[-8:]
    print(f'  最近 {len(show)} 次请求（×N = 相对上一次的 input 倍数，input 决定成本）:')
    prev = None
    for r in show:
        c = cost_of(r['in'], r['cached'], r['peak'])
        h = (r['cached'] / r['in'] * 100) if r['in'] else 0
        ratio = '' if prev is None else f'  ×{r["in"] / prev:.2f}'
        print(f'    {r["t"].strftime("%H:%M:%S")}  {r["in"]:>9,} tok  命中 {h:>5.1f}%  ¥{c:.6f}{ratio}')
        prev = r['in']
    last = rows[-1]
    last_cost = cost_of(last['in'], last['cached'], last['peak'])
    print()
    print(f'  这一轮（最后一次请求）input {last["in"]:,} tok ≈ ¥{last_cost:.6f}')
    if len(rows) > 1:
        avg = sum(r['in'] for r in rows[:-1]) / (len(rows) - 1)
        if avg:
            word = '贵' if last['in'] > avg else '便宜'
            print(f'  比这个会话之前的平均请求（{avg:,.0f} tok）{word} {last["in"] / avg:.2f} 倍')


def main() -> None:
    ap = argparse.ArgumentParser(description='按时间窗口算 token 成本（数据源 bili.log）')
    ap.add_argument('--hours', type=float, default=24, help='看最近几小时，默认 24')
    ap.add_argument('--recent', type=int, default=0, help='只看最近 N 次请求')
    ap.add_argument('--session', nargs='?', const='', default=None,
                    help='只看某个会话（不带值 = 日志里最新的会话）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    # 会话模式不限时间窗口：一个长会话可能横跨好几个小时，按 --hours 切会把前半段吃掉。
    if a.session is not None:
        all_rows = load(None)
        sess = a.session or (all_rows[-1]['sess'] if all_rows else '')
        if not sess:
            print(f'[FAIL] 判断不出当前会话：日志里没有 [sess=...] 标记（bili.log: {LOG}）')
            sys.exit(1)
        rows = [r for r in all_rows if r['sess'] == sess]
        if not rows:
            print(f'[FAIL] 会话 {sess} 没有 [acp-usage] 记录（bili.log: {LOG}）')
            sys.exit(1)
        if a.json:
            import json
            tin = sum(r['in'] for r in rows)
            tc = sum(r['cached'] for r in rows)
            print(json.dumps({'session': sess, 'requests': len(rows), 'input': tin,
                              'cached': tc,
                              'cost': round(sum(cost_of(r['in'], r['cached'], r['peak']) for r in rows), 6)},
                             ensure_ascii=False, indent=2))
        else:
            report_session(rows, sess)
        return

    since = datetime.now() - timedelta(hours=a.hours)
    rows = load(since)
    if a.recent and len(rows) > a.recent:
        rows = rows[-a.recent:]

    if not rows:
        print(f'最近 {a.hours:g} 小时没有 [acp-usage] 记录（bili.log: {LOG}）')
        sys.exit(1)

    total_in = sum(r['in'] for r in rows)
    total_cached = sum(r['cached'] for r in rows)
    total_cost = sum(cost_of(r['in'], r['cached'], r['peak']) for r in rows)
    hit_pct = (total_cached / total_in * 100) if total_in else 0

    by_hour: dict[str, dict] = defaultdict(lambda: {'n': 0, 'in': 0, 'cached': 0, 'cost': 0.0})
    for r in rows:
        k = r['t'].strftime('%m-%d %H')
        b = by_hour[k]
        b['n'] += 1
        b['in'] += r['in']
        b['cached'] += r['cached']
        b['cost'] += cost_of(r['in'], r['cached'], r['peak'])

    if a.json:
        import json
        print(json.dumps({'hours': a.hours, 'requests': len(rows), 'input': total_in,
                          'cached': total_cached, 'cost': round(total_cost, 4),
                          'by_hour': {k: {**v, 'cost': round(v['cost'], 4)} for k, v in by_hour.items()}},
                         ensure_ascii=False, indent=2))
        return

    print(f'[COST] 最近 {a.hours:g} 小时 · {len(rows)} 次请求')
    print(f'  input {total_in:,} tok / cached {total_cached:,} tok（命中 {hit_pct:.1f}%）')
    print(f'  **估算花费 ¥{total_cost:.4f}**（只算 input，output 约占 0.3%）')
    print()
    print('  ⚠️ 这个数**低于官方账单约 2.4 倍**（实测：48 小时估 ¥43.7，官方报 ¥63.45/天）。')
    print('     原因：bili 记录的 cached 命中率是 98.1%，而反推官方账单得到的有效命中率约 91%——')
    print('     两者的 cached 口径不同（bili 算的是"前缀字节命中"，官方算的是"计费 token 命中"）。')
    print('     所以：**看相对分布（哪个小时贵、高峰 vs 空闲）可信，看绝对值不可信。**')
    print()
    print('  按小时（只列花了钱的）:')
    for k in sorted(by_hour):
        b = by_hour[k]
        if b['cost'] < 0.0001:
            continue
        peak_tag = '⏰高峰' if is_peak(datetime.strptime(k + ':00:00', '%m-%d %H:%M:%S').replace(year=datetime.now().year)) else '空闲'
        print(f'    {k}:00  {b["n"]:>3} 次  {b["in"]:>10,} tok  命中 {b["cached"]/b["in"]*100 if b["in"] else 0:>5.1f}%  ¥{b["cost"]:>7.4f}  {peak_tag}')


if __name__ == '__main__':
    main()
