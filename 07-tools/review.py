"""复盘触发点（治 P5）。

P5 的根因不是「看不到历史」——时间轴是 100% 完整的；缺的是**自动复盘的触发点**：
我只有想起来才会回头看，想不起来就一直往前走。

所以把提醒挂到两件每天一定会发生的事上：
  1. `lab commit` 成功（提交是天然的收尾点）——只读一个 JSON，0 成本；
  2. `lab session-age` 超阈值（长会话该换的时候）。

真正的汇总跑在 `lab review` 里：扫 claims（完成声明有没有证据）+ rework（被否定几次），
写回 `E:\\DS公作区\\自进化\\复盘状态.json`。

设计原则：**提醒必须廉价**。commit 里绝不扫会话（scan(3) 要 3 秒），
只读 state；要数字的时候跑 `lab review`。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '自进化' / '复盘状态.json'
REVIEW_DAYS = 3.0          # 超过这么多天没复盘就该提醒


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    except Exception as e:
        print(f'[WARN] 复盘状态写不进去：{type(e).__name__}: {e}', file=sys.stderr)


def days_since(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(stamp)).total_seconds() / 86400
    except Exception:
        return None


def remind() -> None:
    """一行复盘状态。挂在 commit / session-age 后面，不扫会话。"""
    st = load()
    d = days_since(st.get('last_review'))
    if d is None:
        print('[复盘] 还没有跑过复盘——跑一次 `lab review`（约 5 秒）')
        return
    tail = ''
    if st.get('claims'):
        tail = f" · 证据率 {st.get('backed', 0) / st['claims'] * 100:.0f}%"
    if st.get('negatives') is not None:
        tail += f" · 否定 {st['negatives']} 次"
    if d > REVIEW_DAYS:
        print(f'[复盘] 距上次复盘 {d:.1f} 天（> {REVIEW_DAYS:.0f} 天）——跑 `lab review`{tail}')
    else:
        print(f'[复盘] 上次 {d:.1f} 天前{tail}')


def run() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from claims import chat_claims
    from rework import scan

    print('=' * 70)
    print('复盘（最近 3 天）')
    print('=' * 70)

    c = chat_claims(3)
    rate = c['backed'] / c['claims'] * 100 if c['claims'] else 0.0
    print(f"  完成声明：{c['claims']} 段，{c['backed']} 条有证据（{rate:.0f}%）")
    if c['claims'] - c['backed'] > 0:
        print(f"            光说不带数 {c['claims'] - c['backed']} 条（`lab claims --chat --days 3` 看明细）")

    neg = scan(3.0)
    print(f'  被否定：{len(neg)} 次（`lab rework` 看时刻和被否定前我说了什么）')

    st = load()
    prev = days_since(st.get('last_review'))
    if prev is not None:
        print(f'  上次复盘：{st["last_review"][:16].replace("T", " ")}（{prev:.1f} 天前）')

    if c['errors']:
        print(f"  [WARN] {len(c['errors'])} 个会话读失败：{c['errors'][0]}")

    save({
        'last_review': datetime.now().isoformat(timespec='seconds'),
        'claims': c['claims'],
        'backed': c['backed'],
        'negatives': len(neg),
        'scanned': c['scanned'],
    })
    print(f'  已写 {STATE}')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
