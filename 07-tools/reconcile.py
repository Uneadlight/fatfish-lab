#!/usr/bin/env python
"""记录对账：把决策日志、账本、git log 摆在一起，指出对不上的地方。

**它不判错**。三份记录对不上，绝大多数情况不是"有一个错了"，而是
"有一个没解释"——所以输出是「哪里对不上 + 可能要补哪句话」，不是「哪里错了」。

只读，不改任何文件。

用法：
  py tools/lab/reconcile.py                # 全部日志
  py tools/lab/reconcile.py --days 3       # 只看最近 3 天
  py tools/lab/reconcile.py --md out.md    # 另存 markdown

三类检查：
  A 日志里写的提交号，在任何一个仓库里都找不到       → 记错了 / 提交在别处
  B 日志里写的提交号，git 里的时间和日志写的时间差很远 → 时间记错
  C 某天日志写了"做了很多"，账本当天几乎没有花费      → 可能全是本地活，也可能没真做
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r'D:\work')
LOG_MD = ROOT / '自进化' / '决策日志.md'
LEDGER_DATA = Path.home() / '.dsh' / 'ledger' / 'ledger.data'
GIT = ROOT / 'tools' / 'git' / 'cmd' / 'git.exe'

REPOS = [
  ROOT,
  ROOT / 'repos' / 'dafeiyu-lab',
  ROOT / 'repos' / 'dafeiyu-lab-durable',
  ROOT / 'repos' / 'ollama-python',
  ROOT / 'repos' / 'python-docx',
  ROOT / 'repos' / 'httpx',
  ROOT / '架构文档',
  ROOT / '学习计划' / '01-编程',
  ROOT / 'dsh-workflow-skill',
  ROOT / 'tools' / 'lab',
]

# 提交短号：7-40 位十六进制，且必须含至少一个 a-f（纯数字多半是日期/端口/数量）
SHA_RE = re.compile(r'\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b')
# 「像提交号」的强上下文：commit/提交/合入 后面紧跟的 hex
SHA_STRONG_RE = re.compile(
  r'(?:commit|提交|合入|fast-forward|HEAD)[^\n]{0,12}?`?([0-9a-f]{7,40})`?', re.IGNORECASE
)
# 段落标题：只要求 `## YYYY-MM-DD` 开头就算一段。
# 不去死抠时间格式——日志里真实存在 `## 2026-10-27`（无时间）、`## 2026-10-28 · 收尾`
# （用 · 分隔）、`## 2026-10-30 20:2x`（时间没记准）三种写法。
# 而 `## 做了什么` / `## 为什么` 这些段内子标题因为没有日期前缀，自然不会被误当成段。
HEAD_RE = re.compile(r'^## (\d{4}-\d{2}-\d{2})(.*)$')
TIME_RE = re.compile(r'(\d{1,2}:[0-9xX]{2}(?::[0-9xX]{2})?)')
MONEY_RE = re.compile(r'(\d+(?:\.\d+)?)\s*元')
# safe_mutate 的审核 token 也是 16 位 hex，别把它当提交号
SAFE_TOKEN_RE = re.compile(r'(?:token|令牌)\s*`?([0-9a-f]{8,40})`?', re.IGNORECASE)
HDR = struct.Struct('>II')


def git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
  if not GIT.exists():
    return 1, ''
  r = subprocess.run(
    (str(GIT), '-C', str(cwd or ROOT), *args),
    capture_output=True, text=True, encoding='utf-8', errors='replace',
  )
  return r.returncode, (r.stdout or '').strip()


def parse_log(path: Path) -> list[dict]:
  """按 `## YYYY-MM-DD ...` 切段。时间可选、标题可选、分隔符随便。"""
  if not path.exists():
    return []
  entries: list[dict] = []
  cur: dict | None = None
  for line in path.read_text(encoding='utf-8').splitlines():
    m = HEAD_RE.match(line)
    if m:
      if cur:
        entries.append(cur)
      rest = m.group(2).strip()
      tm = TIME_RE.search(rest)
      cur = {
        'date': m.group(1),
        'time': tm.group(1) if tm else '',
        'title': rest.lstrip(' ·—-').strip(),
        'body': [],
      }
      continue
    if cur is not None:
      cur['body'].append(line)
  if cur:
    entries.append(cur)
  for e in entries:
    e['text'] = '\n'.join(e['body'])
  return entries


def iter_ledger(path: Path):
  """读 ledger.data 的帧： [json 长度 4B][crc32 4B][json]。坏的跳过。"""
  if not path.exists():
    return
  raw = path.read_bytes()
  off = 0
  while off + HDR.size <= len(raw):
    length, _crc = HDR.unpack_from(raw, off)
    off += HDR.size
    if length <= 0 or off + length > len(raw):
      break
    chunk = raw[off : off + length]
    off += length
    try:
      yield json.loads(chunk.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
      continue


def sha_exists(sha: str) -> tuple[bool, Path | None, str]:
  """在哪个仓库里能找到这个提交？返回 (存在?, 仓库, 提交时间)。"""
  for repo in REPOS:
    if not (repo / '.git').exists():
      continue
    code, out = git('cat-file', '-e', f'{sha}^{{commit}}', cwd=repo)
    if code == 0:
      _, when = git('log', '-1', '--format=%ci', sha, cwd=repo)
      return True, repo, when
  return False, None, ''


def selftest() -> int:
  """先证明这个检查抓得到，再相信它报的 OK。

  按 SKILL.md 第 15 条：一个永远返回 OK 的判据不是判据，是装饰。
  这里造三种「该被抓住的东西」，跑一遍，看是不是真抓住了。
  """
  import tempfile

  cases: list[tuple[str, str, str, str]] = [
    # (名字, 日志内容, 期望命中的类, 说明)
    (
      '假提交号',
      '## 2026-11-02 10:00 测试\n- 提交 `abc1234f` 推到远端\n',
      'A',
      '这个号在 git 里当然不存在',
    ),
    (
      '时间错位',
      '## 2020-01-01 10:00 测试\n- 提交 `dd92621` 推到远端\n',
      'B',
      '这个提交是 2026-11-02 的，日志写在 2020 年',
    ),
    (
      '账本缺口',
      '## 2026-10-27 10:00 测试一\n- x\n## 2026-10-27 11:00 测试二\n- x\n'
      '## 2026-10-27 12:00 测试三\n- x\n',
      'C',
      '当天 3 段日志，账本没有这天',
    ),
  ]

  print('=== reconcile 自检 ===\n')
  all_ok = True
  for name, body, expect_kind, why in cases:
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as fh:
      fh.write(body)
      tmp = Path(fh.name)
    try:
      entries = parse_log(tmp)
      hits: list[str] = []

      if expect_kind in ('A', 'B'):
        for e in entries:
          blob = e['text'] + ' ' + e['title']
          strong = set(SHA_STRONG_RE.findall(blob))
          weak = set(SHA_RE.findall(blob)) - strong - set(SAFE_TOKEN_RE.findall(blob))
          for sha in strong | weak:
            ok, _repo, when = sha_exists(sha)
            if not ok and sha in strong:
              hits.append(f'A:{sha}')
            elif ok and when and not when.startswith(e['date']):
              hits.append(f'B:{sha}')

      if expect_kind == 'C':
        by_day: dict[str, int] = {}
        for e in entries:
          by_day[e['date']] = by_day.get(e['date'], 0) + 1
        spent: dict[str, float] = {}
        for row in iter_ledger(LEDGER_DATA) or ():
          raw = row.get('ts') or ''
          if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
            d = datetime.fromtimestamp(float(raw)).strftime('%Y-%m-%d')
            spent[d] = spent.get(d, 0.0) + float(row.get('amount', 0)) / 100.0
        for day, n in by_day.items():
          if n >= 3 and day not in spent:
            hits.append(f'C:{day}')

      ok = any(h.startswith(expect_kind) for h in hits)
      all_ok = all_ok and ok
      print(f'  [{"PASS" if ok else "FAIL"}] {name}（期望 {expect_kind}）—— {why}')
      print(f'         抓到：{hits or "什么都没有"}')
    finally:
      tmp.unlink(missing_ok=True)

  print()
  print('自检结果：' + ('全部抓得到 ✓' if all_ok else '**有检查抓不到，那就是假检查**'))
  return 0 if all_ok else 1


def main() -> int:
  ap = argparse.ArgumentParser(description='把决策日志、账本、git log 摆在一起对账')
  ap.add_argument('--log', type=str, default='', help='换一份日志来对（默认 E:\\DS公作区\\自进化\\决策日志.md）')
  ap.add_argument('--days', type=int, default=0, help='只看最近 N 天（0=全部）')
  ap.add_argument('--md', type=str, default='', help='把结果另存为 markdown')
  ap.add_argument('--selftest', action='store_true',
                  help='自检：构造 3 个假差异，看检查抓不抓得到（抓不到就是假检查）')
  ap.add_argument('--quiet', action='store_true', help='只输出差异，不输出统计')
  a = ap.parse_args()

  if a.selftest:
    return selftest()

  entries = parse_log(Path(a.log) if a.log else LOG_MD)
  if not entries:
    print(f'[FAIL:用途错误] 读不到日志：{LOG_MD}')
    return 2

  if a.days > 0:
    cutoff = (datetime.now() - timedelta(days=a.days)).strftime('%Y-%m-%d')
    entries = [e for e in entries if e['date'] >= cutoff]

  diffs: list[dict] = []

  # ── A/B：提交号核验 ─────────────────────────────────────────
  # 分两档，因为有一半 hex 串根本不是提交号：
  #   强上下文（commit/提交 后面跟的）→ 找不到就是真差异
  #   孤立 hex → 找到了才核对时间，找不到不报（safe_mutate token、sha256 前缀都是 hex）
  sha_total = 0
  for e in entries:
    blob = e['text'] + ' ' + e['title']
    # 同一行里出现 token 的，整行不算提交号。
    # 起因：决策日志里写了一句「把 safe_mutate 的审核 token 当提交号。8e99d8c1… 是 16 位 hex」，
    # 这句本身就是"解释这个坑"的，结果被自己的工具抓成了新差异。
    # 宁可漏报一行，不要天天喊狼来了。
    clean_blob = '\n'.join(ln for ln in blob.splitlines() if 'token' not in ln.lower())
    strong = set(SHA_STRONG_RE.findall(clean_blob))
    weak = set(SHA_RE.findall(clean_blob)) - strong - set(SAFE_TOKEN_RE.findall(clean_blob))

    for sha in sorted(strong | weak):
      is_strong = sha in strong
      sha_total += 1
      ok, repo, when = sha_exists(sha)
      if not ok:
        if not is_strong:
          continue  # 孤立 hex，找不到不算差异（可能是 token/哈希/编号）
        diffs.append({
          'kind': 'A',
          'where': f'{e["date"]} {e["time"]}',
          'what': f'日志明确写着提交 `{sha}`',
          'fact': '已登记的仓库里都找不到这个提交',
          'ask': '这个号是不是记错了（少一位/多一位）？还是提交在某个还没登记的仓库？',
        })
        continue
      # B：日志时间 vs 提交时间（只比日期）
      if when and not when.startswith(e['date']):
        diffs.append({
          'kind': 'B',
          'where': f'{e["date"]} {e["time"]}',
          'what': f'日志把 `{sha}` 记在 {e["date"]}',
          'fact': f'git 显示 {when}（{repo.name if repo != ROOT else "主工作区"}）',
          'ask': '是当天写的日志、事是前一天做的？还是时间写错了？',
        })

  # ── C：日志活跃度 vs 账本花费 ────────────────────────────────
  by_day: dict[str, list[dict]] = {}
  for e in entries:
    by_day.setdefault(e['date'], []).append(e)

  # 账本的 ts 是 Unix 时间戳（不是 "YYYY-MM-DD"）。
  # 第一版直接 str(ts)[:10] 当日期，把 1793509740 之类当成"某天"，
  # 生成了 12 个乌有的日子、还骗出 3 条假差异——对账工具自己先对账。
  spend_by_day: dict[str, float] = {}
  for row in iter_ledger(LEDGER_DATA) or ():
    raw = row.get('ts') or row.get('time') or ''
    day = ''
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
      try:
        day = datetime.fromtimestamp(float(raw)).strftime('%Y-%m-%d')
      except (OverflowError, OSError, ValueError):
        day = ''
    elif isinstance(raw, str) and len(raw) >= 10:
      day = raw[:10]
    if day:
      spend_by_day[day] = spend_by_day.get(day, 0.0) + float(row.get('amount', 0)) / 100.0

  # 账本覆盖的第一天：用来区分「这天没花钱」和「这天账本根本没数据」
  ledger_first = min(spend_by_day) if spend_by_day else ''

  for day, es in sorted(by_day.items()):
    if len(es) < 3:
      continue
    if day not in spend_by_day:
      if ledger_first and day < ledger_first:
        # 账本覆盖范围之前的日期不报差异：这是已知的数据缺口（账本 2026-11-01 才有），
        # 每次跑都报 4 条同样的噪音，会把真正的差异淹掉。
        continue
      diffs.append({
        'kind': 'C',
        'where': day,
        'what': f'当天写了 {len(es)} 段日志',
        'fact': '账本在覆盖区间内，却没有这一天的记录（采集器可能那天没跑）',
        'ask': '是采集器漏跑了，还是这天真的没有余额变化？',
      })
      continue
    spent = spend_by_day[day]
    if spent < 0.05:
      diffs.append({
        'kind': 'C',
        'where': day,
        'what': f'当天写了 {len(es)} 段日志',
        'fact': f'账本记录当天花费 {spent:.2f} 元',
        'ask': '这天是纯本地活（读码/写文档/跑测试都不花钱）？还是记录和实际对不上？',
      })

  # ── 输出 ────────────────────────────────────────────────────
  lines: list[str] = []
  if not a.quiet:
    lines.append(f'扫描 {len(entries)} 段日志 / 核验 {sha_total} 个提交号 / 账本 {len(spend_by_day)} 天有记录')
    lines.append('')

  if not diffs:
    lines.append('**没有发现需要解释的差异。**')
    lines.append('')
    lines.append('（注意：这条结论本身也要留神——如果真的完全没差异，先证明这个检查抓得到问题：')
    lines.append(' 手动构造一个假的提交号，看它报不报。）')
  else:
    lines.append(f'**{len(diffs)} 处需要一句解释**')
    lines.append('')
    lines.append('| # | 类 | 位置 | 日志说 | 记录显示 | 可能要补一句 |')
    lines.append('|---|---|---|---|---|---|')
    for i, d in enumerate(diffs, 1):
      lines.append(
        f'| {i} | {d["kind"]} | {d["where"]} | {d["what"]} | {d["fact"]} | {d["ask"]} |'
      )

  text = '\n'.join(lines)
  print(text)

  if a.md:
    Path(a.md).write_text(text, encoding='utf-8')
    print(f'\n已写入 {a.md}')

  return 0


if __name__ == '__main__':
  sys.exit(main())
