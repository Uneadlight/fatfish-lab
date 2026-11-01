"""余额差值采集器：读 DeepSeek 账户余额，把两次之间的差额记成一条 api 花费。

为什么用余额差而不是 token × 单价：
- 余额是账户侧的权威数字，包含所有 key、所有通道，算错不了；
- token × 单价要同时假设模型、缓存命中率、时段价，三个假设叠起来的
  误差比一次减法大得多。

代价：只知道"总共花了多少"，不知道"花在哪"。归因留给 acp_cache。

用法：
  py -m ledger.collect --baseline   # 首次只记基线，不记账
  py -m ledger.collect --dry        # 看一眼会记多少，不落盘
  py -m ledger.collect              # 正常采集：余额降了就记一条
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger.cli import DEFAULT_PREFIX
from ledger.store import LedgerStore

BALANCE_URL = 'https://api.deepseek.com/user/balance'
CRED = Path.home() / '.dsh' / '.credentials.yaml'
TIMEOUT = 30


def read_api_key() -> str:
  """从 `.credentials.yaml` 的 refs 段里取 DEEPSEEK_API_KEY。"""
  if not CRED.exists():
    raise SystemExit(f'[FAIL:能力缺失] 找不到 {CRED}')
  for line in CRED.read_text(encoding='utf-8').splitlines():
    text = line.strip()
    if text.startswith('DEEPSEEK_API_KEY:'):
      value = text.split(':', 1)[1].strip()
      return value.strip('"\'')
  raise SystemExit('[FAIL:能力缺失] .credentials.yaml 里没有 DEEPSEEK_API_KEY')


def fetch_balance(key: str) -> float:
  request = urllib.request.Request(
    BALANCE_URL,
    headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
  )
  try:
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
      payload = json.loads(response.read().decode('utf-8'))
  except urllib.error.HTTPError as exc:
    raise SystemExit(f'[FAIL:执行失败] 余额接口返回 HTTP {exc.code}') from exc
  except (urllib.error.URLError, TimeoutError) as exc:
    raise SystemExit(f'[FAIL:执行失败] 余额接口连不上：{exc}') from exc
  infos = payload.get('balance_infos') or []
  if not infos:
    raise SystemExit('[FAIL:执行失败] 余额接口没返回 balance_infos')
  return float(infos[0]['total_balance'])


def state_path(prefix: Path) -> Path:
  return prefix.with_suffix('.state.json')


def load_state(path: Path) -> dict:
  if not path.exists():
    return {}
  try:
    return json.loads(path.read_text(encoding='utf-8'))
  except json.JSONDecodeError:
    print(f'[WARN] 状态文件解析失败，按首次处理：{path}')
    return {}


def save_state(path: Path, state: dict) -> None:
  """先写临时文件再 replace，避免半个 JSON。"""
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix('.json.tmp')
  tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  tmp.replace(path)


def main(argv: list[str]) -> int:
  dry = '--dry' in argv
  baseline = '--baseline' in argv
  DEFAULT_PREFIX.parent.mkdir(parents=True, exist_ok=True)
  spath = state_path(DEFAULT_PREFIX)
  state = load_state(spath)

  balance = fetch_balance(read_api_key())
  print(f'余额 {balance:.2f} 元   （状态文件 {spath.name}）')

  last = state.get('last_balance')
  if last is None or baseline:
    state.update({'last_balance': balance, 'updated_at': int(time.time())})
    if dry:
      print('[dry] 会写基线，不记账')
      return 0
    save_state(spath, state)
    print('[OK] 已记基线，本次不产生账目')
    return 0

  spent = round((float(last) - balance) * 100)
  state.update({'last_balance': balance, 'updated_at': int(time.time())})
  if spent <= 0:
    if not dry:
      save_state(spath, state)
    print(f'[OK] 余额没降（{last} → {balance:.2f}），不记账')
    return 0

  if dry:
    print(f'[dry] 会记一条 {spent / 100:.2f} 元的 api 花费（{last} → {balance:.2f}）')
    return 0

  entry = {
    'ts': int(time.time()),
    'kind': 'api',
    'amount': spent,
    'note': f'余额 {last} → {balance:.2f}',
    'tags': ['balance'],
  }
  store = LedgerStore(DEFAULT_PREFIX)
  try:
    seq = store.append(entry)
  finally:
    store.close()
  save_state(spath, state)
  print(f'[OK] seq={seq}  记 {spent / 100:.2f} 元')
  return 0


if __name__ == '__main__':
  raise SystemExit(main(sys.argv[1:]))
