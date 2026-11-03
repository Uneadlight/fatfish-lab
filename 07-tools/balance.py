"""查 DeepSeek 账户余额 + 今日花费估算。

抄自 `dsh-balance-tracker`（`lib/index.js` 的 `createBalanceHandler`），
但那个是插件（注册 webServer 路由 `/budget/balance`），这里是 CLI 子命令
——**纯 HTTP 调用 + 本地文件，不需要插件**。

关键事实（从它的源码里读出来的）：
- 端点   https://api.deepseek.com/user/balance
- 凭证   ~/.dsh/.credentials.yaml 里的 `DEEPSEEK_API_KEY: sk-xxx`
- 响应   { is_available, balance_infos: [{ currency, total_balance,
           granted_balance, topped_up_balance }] }
- 今日花费  有 DEEPSEEK_PLATFORM_TOKEN 时查官方 usage/cost；
           没有时用**余额差值**估算（首日只能记基线，次日才有差值）

用法：
    py balance.py            # 人类可读
    py balance.py --json     # 原始 JSON（给程序消费）
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ENDPOINT = 'https://api.deepseek.com/user/balance'
CRED = Path.home() / '.dsh' / '.credentials.yaml'
DSH_HOME = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh'))
STATE = DSH_HOME / 'storages' / 'lab-balance.json'


def read_key():
    """从 .credentials.yaml 里取 DEEPSEEK_API_KEY。"""
    if not CRED.is_file():
        return None
    text = CRED.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'^\s*DEEPSEEK_API_KEY\s*:\s*(\S+)', text, re.MULTILINE)
    return m.group(1) if m else None


def fetch_balance(key):
    req = urllib.request.Request(
        ENDPOINT,
        headers={'Authorization': f'Bearer {key}'},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def load_state():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_state(obj):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
        tmp.replace(STATE)
    except Exception:
        pass


def estimate_today(balance, today):
    """用余额差值估今日花费。返回 (今日花费 or None, 说明)。"""
    st = load_state()
    if not st or st.get('date') != today:
        save_state({'date': today, 'balance': balance})
        return None, '今日首次查询，只记基线'
    prev = st.get('balance')
    if not isinstance(prev, (int, float)):
        save_state({'date': today, 'balance': balance})
        return None, '上次记录无余额，重记基线'
    spent = round(prev - balance, 2)
    save_state({'date': today, 'balance': balance})
    if spent < 0:
        return 0.0, f'余额涨了 {-spent:.2f}（充值？），按 0 计'
    return spent, f'基线 {prev:.2f} → 现在 {balance:.2f}'


def main():
    as_json = '--json' in sys.argv
    key = read_key()
    if not key:
        print('没找到 DEEPSEEK_API_KEY（~/.dsh/.credentials.yaml）', file=sys.stderr)
        return 1

    try:
        data = fetch_balance(key)
    except urllib.error.HTTPError as e:
        print(f'余额接口 HTTP {e.code}', file=sys.stderr)
        return 1
    except Exception as e:
        print(f'余额查询失败: {e}', file=sys.stderr)
        return 1

    infos = data.get('balance_infos') or []
    primary = infos[0] if infos else {}
    try:
        balance = float(primary.get('total_balance', 0))
    except (TypeError, ValueError):
        balance = 0.0

    today = date.today().isoformat()
    spent, note = estimate_today(balance, today)

    if as_json:
        print(json.dumps({
            'ok': True,
            'isAvailable': data.get('is_available'),
            'currency': primary.get('currency'),
            'totalBalance': balance,
            'grantedBalance': primary.get('granted_balance'),
            'toppedUpBalance': primary.get('topped_up_balance'),
            'todayConsumed': spent,
            'todayNote': note,
            'queriedAt': today,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f'余额   {primary.get("currency", "CNY")} {balance:.2f}')
    print(f'可用   {data.get("is_available")}')
    print(f'今日   ' + (f'{spent:.2f} 元（{note}）' if spent is not None else f'—（{note}）'))
    print(f'查询   {today}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
