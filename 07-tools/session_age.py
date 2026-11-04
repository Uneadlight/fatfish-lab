"""会话年龄：这个对话还能撑多久，每轮比新对话贵几倍。

为什么要这个：上下文窗口是「桌子面积」，累计 token 是「搬上搬下多少东西」。
桌子面积固定，所以对话越长，**每一轮都要把前面全部内容重发一遍**——
第 N 轮的输入大约是前面 N-1 轮总和。成本跟轮数是**平方关系**，不是线性的。

所以「什么时候该开新对话」不该靠感觉，该有个数字。
"""
import io
import json
import time
import zstandard as zstd
from pathlib import Path

SESS_ROOT = Path.home() / '.dsh' / 'sessions'

# 新开一个对话时，每轮固定要发的量（系统提示 + 记忆注入 + 工具定义）
# 实测约 30K token，用 4 字符/token 粗估成 120K 字符。
FRESH_BYTES = 120_000

# 超过这个倍数就建议开新对话（用数据定：8 倍时每轮多花 7 个「新对话的钱」）
ADVISE_RATIO = 8.0


def _unzstd(path: Path):
    with open(path, 'rb') as fh:
        r = zstd.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        yield from io.TextIOWrapper(r, encoding='utf-8', errors='replace')


def scan(days: float = 30.0) -> list[dict]:
    cutoff = time.time() - days * 86400
    files = sorted(SESS_ROOT.glob('*/session-*/session.v4.jsonl.zstd'))
    out = []
    for p in files:
        try:
            st = p.stat()
            if st.st_mtime < cutoff:
                continue
            sid = p.parent.name.replace('session-', '')[:8]
            total = 0
            msgs = 0
            first_t = last_t = None
            for line in _unzstd(p):
                total += len(line)
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                t = rec.get('time') or 0
                if t > 1e11:
                    t = t / 1000.0
                if t:
                    first_t = first_t or t
                    last_t = t
                if rec.get('type') in ('user/message', 'assistant/message'):
                    msgs += 1
            if total == 0:
                continue
            out.append({
                'id': sid,
                'bytes': total,
                'file_mb': st.st_size / 1024 / 1024,
                'msgs': msgs,
                'mtime': st.st_mtime,
                'span_h': ((last_t - first_t) / 3600) if (first_t and last_t) else 0,
                # 每轮要重发的量 ≈ 全文；新对话只有固定开销
                'ratio': total / FRESH_BYTES if FRESH_BYTES else 0,
            })
        except Exception:
            continue
    out.sort(key=lambda r: r['mtime'], reverse=True)
    return out


def human(n: int) -> str:
    if n >= 1024 * 1024:
        return f'{n / 1024 / 1024:.1f} MB'
    if n >= 1024:
        return f'{n / 1024:.1f} KB'
    return f'{n} B'


def main() -> int:
    rows = scan()
    if not rows:
        print('没有扫到会话。')
        return 1

    cur = rows[0]
    print('=' * 70)
    print(f'会话年龄（{len(rows)} 个会话，按最近活动排序）')
    print('=' * 70)
    print()
    print(f'【当前最活跃】{cur["id"]}  {human(cur["bytes"])}  {cur["msgs"]} 条消息  {cur["span_h"]:.1f} 小时')
    print(f'  累计内容量 ≈ 新对话的 {cur["ratio"]:.0f} 倍')
    print('  ⚠️  这是「这个会话一共承载了多少内容」，**不是当前每轮要发多少**。')
    print('     当前每轮的真实成本看 acp_status 的 billed input（会小很多，因为有压缩和缓存）。')
    print('     它的用处是：说明这个会话已经重发了多少遍历史。')
    if cur['ratio'] >= ADVISE_RATIO:
        print(f'  ⚠️  超过 {ADVISE_RATIO:.0f} 倍值得开新对话')
    else:
        print(f'  ✅ 还在 {ADVISE_RATIO:.0f} 倍以内')
    print()

    print('【分布】')
    sizes = sorted(r['bytes'] for r in rows)
    mid = sizes[len(sizes) // 2]
    print(f'  中位 {human(mid)}（{mid / FRESH_BYTES:.1f} 倍）  最大 {human(sizes[-1])}（{sizes[-1] / FRESH_BYTES:.1f} 倍）')
    over = [r for r in rows if r['ratio'] >= ADVISE_RATIO]
    print(f'  超过 {ADVISE_RATIO:.0f} 倍的有 {len(over)} 个')
    print()

    if over:
        print(f'【建议换新对话的（≥{ADVISE_RATIO:.0f} 倍）】')
        for r in over[:8]:
            print(f'  {r["id"]}  {human(r["bytes"]):>10}  {r["msgs"]:>5} 条  {r["ratio"]:.1f} 倍  {time.strftime("%m-%d %H:%M", time.localtime(r["mtime"]))}')
        print()
        print('  换新对话的做法：把「做到哪了 / 下一步」写进文件，再开新窗口读那个文件。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
