#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""lab - 把反复重写的一次性脚本收成子命令。

起因：2026-10-31 清点发现 `E:\\DS公作区\\tools\\gh-login` 下积压 68 个 `_*.py`/`_*.cjs`，
其中「往决策日志追加一段」写了 6 个、「读 app.asar」写了 4 个，全是同一件事写了多遍。
这不是懒，是没有把"这一次"变成"这一类"。

用法:
  lab log --mark "2026-11-01 09:0x" --title "标题" --body-file body.md
  lab log --mark "..." --title "..." --stdin
  lab log --tail 3
  lab asar list [关键字]
  lab asar desc [关键字]
  lab asar read <包内路径> [--max 1200]

退出码: 0 成功 / 1 用途错误 / 2 目标缺失
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r'D:\work')
DECISION_LOG = ROOT / '自进化' / '决策日志.md'
ASAR = Path(r'D:\DeepSeek Harness\resources\app.asar')
DEFAULT_REPO = ROOT / 'repos' / 'dafeiyu-lab'  # 本地目录名仍是 dafeiyu-lab，远端仓库名是 fatfish-lab
DEFAULT_PLAN = ROOT / 'tools' / 'lab' / 'release-plan.txt'

REQUIRED_SECTIONS = ('**做了什么**', '**为什么**', '**取舍**', '**教训**')

JOURNAL = ROOT / 'tools' / 'lab' / 'journal.jsonl'


def journal(action: str, **fields) -> None:
  """先落盘，再执行 —— 参照 dsh-superagent 的 stored work。

  一个动作「做了什么决定」先记下来，再去做。中途崩了，日志里会有 start 但没有
  done，下次一眼看得出上次没走完，而不是靠回忆「我上次好像拷过」。写不了日志
  不该阻断主流程（否则因为日志挂了就干不了活），但要说出来。
  """
  row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'action': action, **fields}
  try:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open('a', encoding='utf-8', newline='\n') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError as exc:
    print(f'[WARN] journal 写入失败（不影响本次执行）: {exc}')


def _fail(code: int, msg: str) -> int:
  tag = '能力缺失' if code == 2 else '用途错误'
  print(f'[FAIL:{tag}] {msg}')
  return code


# ---------------------------------------------------------------- log


def _split_entries(text: str) -> list[str]:
  chunks = text.split('\n## ')
  if not chunks:
    return []
  head = chunks[0]
  entries = [head] if head.strip() else []
  entries.extend('## ' + c for c in chunks[1:])
  return entries


def cmd_log(a: argparse.Namespace) -> int:
  if not DECISION_LOG.exists():
    return _fail(2, f'决策日志不存在: {DECISION_LOG}')
  text = DECISION_LOG.read_text(encoding='utf-8')

  if a.tail:
    entries = _split_entries(text)
    print(f'共 {len(entries)} 段，最后 {a.tail} 段：')
    for e in entries[-a.tail:]:
      print('  ' + e.strip().split('\n', 1)[0])
    return 0

  if not a.mark:
    return _fail(1, '需要 --mark（时间锚点，也是幂等依据）')
  if not a.title:
    return _fail(1, '需要 --title')
  if a.mark in text:
    print(f'SKIP: {a.mark} 已存在，不重复写')
    return 0

  if a.body_file:
    body_path = Path(a.body_file)
    if not body_path.exists():
      return _fail(2, f'正文文件不存在: {body_path}')
    body = body_path.read_text(encoding='utf-8')
  elif a.stdin:
    body = sys.stdin.read()
  else:
    return _fail(1, '需要 --body-file 或 --stdin')

  body = body.strip()
  missing = [s for s in REQUIRED_SECTIONS if s not in body]
  if missing:
    print(f'[WARN] 缺小标题: {", ".join(missing)}')

  entry = f'\n## {a.mark} {a.title}\n\n{body}\n'
  if a.dry:
    print(entry)
    return 0

  with open(DECISION_LOG, 'a', encoding='utf-8', newline='\n') as f:
    f.write(entry)
  print(f'OK {len(text)} -> {len(text) + len(entry)} chars')
  return 0


# ------------------------------------------------------------- stage

# 顺序敏感：长的先替换，否则 `~/.dsh` 会先被 `~` 吃掉
SCRUB_RULES = [
  (r'C:\\Users\\<user>\\AppData\\Local', '%LOCALAPPDATA%'),
  (r'C:\\Users\\<user>\\.dsh', '~/.dsh'),
  (r'C:\\Users\\<user>', '~'),
  (r'E:\\DS公作区\\进阶-20261029', '.'),
  (r'E:\\DS公作区', 'D:\\work'),
  (r'<user>', '<user>'),
  (r'用户|用户', '用户'),
]

TEXT_SUFFIXES = {'.md', '.py', '.js', '.mjs', '.json', '.yml', '.yaml', '.txt', '.patch'}

BAD_PATTERN = re.compile(r'C:\\Users\\<user>|E:\\DS公作区|<user>|用户|用户')

SECRET_PATTERNS = [
  ('openai-key', re.compile(r'sk-[A-Za-z0-9_\-]{20,}')),
  ('github-token', re.compile(r'\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})')),
  ('bearer', re.compile(r'Bearer\s+[A-Za-z0-9._\-]{20,}')),
  ('private-key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
  ('password', re.compile(r'(?i)\b(password|passwd|secret)\s*[:=]\s*[\'"][^\'"]{6,}[\'"]')),
  ('private-ip', re.compile(r'\b(192\.168|10\.\d{1,3}|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b')),
  ('email', re.compile(r'\b[\w.+-]+@(?!users\.noreply\.github\.com)[\w-]+\.[\w.]{2,}\b')),
]


def _load_plan(plan_path: Path) -> list[tuple[Path, str]]:
  if not plan_path.exists():
    raise FileNotFoundError(plan_path)
  pairs: list[tuple[Path, str]] = []
  for raw in plan_path.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#'):
      continue
    if '=>' not in line:
      raise ValueError(f'行格式应为「源 => 仓库内路径」: {raw}')
    left, right = (s.strip() for s in line.split('=>', 1))
    src = Path(left) if Path(left).is_absolute() else ROOT / left
    pairs.append((src, right))
  return pairs


def _scrub_text(text: str) -> str:
  for pattern, repl in SCRUB_RULES:
    text = re.sub(pattern, lambda _m, r=repl: r, text)
  return text


def cmd_stage(a: argparse.Namespace) -> int:
  repo = Path(a.repo) if a.repo else DEFAULT_REPO
  plan = Path(a.plan) if a.plan else DEFAULT_PLAN
  if not repo.exists():
    return _fail(2, f'仓库目录不存在: {repo}')
  try:
    pairs = _load_plan(plan)
  except Exception as exc:  # noqa: BLE001 - 清单读不了就是读不了，原因直接报
    return _fail(2, f'读发布清单失败: {exc}')
  if not pairs:
    return _fail(1, f'清单里没有条目: {plan}')

  # 展开清单：目录条目递归成文件条目（copy2 不能拷目录）
  targets: list[tuple[Path, Path, str]] = []
  missed: list[tuple[Path, str]] = []
  for src, rel in pairs:
    if not src.exists():
      missed.append((src, rel))
      continue
    if src.is_dir():
      for f in sorted(src.rglob('*')):
        if f.is_file():
          inner = f.relative_to(src).as_posix()
          targets.append((f, repo / rel / inner, f'{rel}/{inner}'))
    else:
      targets.append((src, repo / rel, rel))

  copied: list[tuple[str, int]] = []
  scrubbed: list[str] = []
  if not a.dry:
    # 先落盘：这条记下去之后才开始动发布仓库。中途崩了，日志里会留下一个没有
    # 对应 done 的 start —— 下次知道上次停在哪儿，不用靠回忆。
    journal(
      'stage.start',
      repo=str(repo),
      files=[rel for _, _, rel in targets],
      missed=[rel for _, rel in missed],
    )
  for src, dst, rel in targets:
    if a.dry:
      copied.append((rel, src.stat().st_size))
      continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append((rel, dst.stat().st_size))
    if dst.suffix.lower() in TEXT_SUFFIXES:
      text = dst.read_text(encoding='utf-8', errors='strict')
      cleaned = _scrub_text(text)
      if cleaned != text:
        dst.write_text(cleaned, encoding='utf-8', newline='\n')
        scrubbed.append(rel)

  prefix = '[dry] ' if a.dry else ''
  print(f'{prefix}拷贝 {len(copied)} 个：')
  for rel, size in copied:
    print(f'  {rel}  ({size:,} B)')
  if scrubbed:
    print(f'脱敏 {len(scrubbed)} 个：')
    for rel in scrubbed:
      print('  ' + rel)
  if missed:
    print(f'[MISS] {len(missed)} 个源文件不存在：')
    for src, rel in missed:
      print(f'  {src}  -> {rel}')

  if a.skip_scan:
    print('\n跳过扫描（--skip-scan）')
    return 1 if missed else 0

  print(f'\n=== 安全扫描（{repo.name}）===')
  path_hits = 0
  secret_hits = 0
  for path in repo.rglob('*'):
    if not path.is_file() or '.git' in path.parts:
      continue
    if path.suffix.lower() not in TEXT_SUFFIXES:
      continue
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    # 规则定义行豁免：SCRUB_RULES / BAD_PATTERN / SECRET_PATTERNS 本身就是「要把本机
    # 路径和密钥找出来替换掉」的规则，扫描器抓自己等于杀软特征库报病毒。只豁免本文件
    # 里的这三段定义，文件其余部分照抓。
    rule_lines: set[int] = set()
    if path.name == Path(__file__).name:
      in_block = False
      for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith('SCRUB_RULES = [') or s.startswith('SECRET_PATTERNS = ['):
          in_block = True
        if s.startswith('BAD_PATTERN ='):
          rule_lines.add(i)
          continue
        if in_block:
          rule_lines.add(i)
          if s == ']':
            in_block = False
    for idx, line in enumerate(lines, 1):
      if idx - 1 in rule_lines:
        continue
      if BAD_PATTERN.search(line):
        path_hits += 1
        if path_hits <= 10:
          print(f'  [路径] {path.relative_to(repo)}:{idx}: {line.strip()[:100]}')
      for name, rx in SECRET_PATTERNS:
        if rx.search(line):
          secret_hits += 1
          if secret_hits <= 10:
            print(f'  [凭证:{name}] {path.relative_to(repo)}:{idx}: {line.strip()[:100]}')
  print(f'  路径命中 {path_hits} 行 / 凭证命中 {secret_hits} 行')

  if path_hits or secret_hits:
    print('  [STOP] 不为 0，不许发布')
    if not a.dry:
      journal('stage.aborted', reason='scan', path_hits=path_hits, secret_hits=secret_hits)
    return 1
  print('  [OK] 可以发布')
  if not a.dry:
    journal('stage.done', files=len(copied), scrubbed=len(scrubbed), missed=len(missed))
  return 1 if missed else 0


# --------------------------------------------------------------- asar


def _asar_index():
  """返回 (header, data_start)。asar 头: offset 0/4/8/12 四个 uint32，JSON 从 16 起。"""
  with open(ASAR, 'rb') as f:
    head = f.read(16)
    if len(head) < 16:
      raise ValueError('asar 头不足 16 字节')
    json_size = int.from_bytes(head[12:16], 'little')
    raw = f.read(json_size)
  data_start = 16 + json_size
  data_start += (4 - data_start % 4) % 4
  return json.loads(raw.decode('utf-8')), data_start


def _walk(node, prefix=''):
  for name, child in (node.get('files') or {}).items():
    path = f'{prefix}/{name}' if prefix else name
    if 'files' in child:
      yield from _walk(child, path)
    else:
      yield path, child


def _read_node(fh, data_start: int, node) -> bytes:
  size = int(node.get('size', 0))
  offset = int(node.get('offset', 0))
  fh.seek(data_start + offset)
  return fh.read(size)


def _lookup(header, inner_path: str):
  cur = header
  for part in [p for p in inner_path.split('/') if p]:
    files = cur.get('files') or {}
    if part not in files:
      return None
    cur = files[part]
  return cur


def cmd_asar(a: argparse.Namespace) -> int:
  if not ASAR.exists():
    return _fail(2, f'asar 不存在: {ASAR}')
  try:
    header, data_start = _asar_index()
  except Exception as exc:  # noqa: BLE001 - 解析失败原因不重要，报出来即可
    return _fail(2, f'解析 asar 头失败: {exc}')

  needle = (a.keyword or '').lower()

  if a.action == 'read':
    if not a.keyword:
      return _fail(1, 'read 需要包内路径')
    node = _lookup(header, a.keyword)
    if node is None or 'files' in node:
      return _fail(2, f'不是文件或不存在: {a.keyword}')
    with open(ASAR, 'rb') as fh:
      blob = _read_node(fh, data_start, node)
    text = blob.decode('utf-8', 'replace')
    if a.max and len(text) > a.max:
      print(text[: a.max])
      print(f'\n... (截断，共 {len(text)} 字符，--max 0 看全部)')
    else:
      print(text)
    return 0

  # list / desc：只列 package.json，desc 额外带 description
  rows: list[tuple[str, str, str, str]] = []
  with open(ASAR, 'rb') as fh:
    for path, node in _walk(header):
      if not path.endswith('/package.json'):
        continue
      if needle and needle not in path.lower():
        continue
      try:
        meta = json.loads(_read_node(fh, data_start, node).decode('utf-8'))
      except Exception:  # noqa: BLE001 - 坏掉的 package.json 直接跳过
        continue
      name = str(meta.get('name') or '')
      version = str(meta.get('version') or '')
      desc = ' '.join(str(meta.get('description') or '').split())
      if a.action == 'list':
        rows.append((name, version, '', path))
      else:
        rows.append((name, version, desc[:110], path))

  for name, version, desc, path in sorted(rows):
    if a.action == 'list':
      print(f'  {name} {version}')
    else:
      print(f'  {name} {version}')
      if desc:
        print(f'      {desc}')
  print(f'共 {len(rows)} 个')
  return 0


# ---------------------------------------------------------------- github


def _token() -> str:
  p = Path.home() / '.dsh' / 'github-token.txt'
  if not p.exists():
    raise SystemExit('[FAIL:能力缺失] 没有 GitHub token，先跑 github_device_login.py')
  return p.read_text(encoding='utf-8').strip()


def _gh(method: str, path: str, payload=None) -> tuple[int, dict]:
  data = json.dumps(payload).encode('utf-8') if payload is not None else None
  headers = {
    'Accept': 'application/vnd.github+json',
    'Authorization': f'Bearer {_token()}',
    'User-Agent': 'lab/1.0',
    'X-GitHub-Api-Version': '2022-11-28',
  }
  if data:
    headers['Content-Type'] = 'application/json'
  req = urllib.request.Request(f'https://api.github.com{path}', data=data, method=method, headers=headers)
  try:
    with urllib.request.urlopen(req, timeout=45) as r:
      body = r.read().decode('utf-8')
      return r.status, (json.loads(body) if body.strip() else {})
  except urllib.error.HTTPError as e:
    return e.code, {'error': e.read().decode('utf-8', 'replace')[:300]}


def _slug(a: argparse.Namespace) -> str:
  """把 --repo 归一成 owner/repo。

  2026-11-02 修：原来直接把 --repo 原样塞进 URL，传本地路径（含中文）时
  urllib 抛 `UnicodeEncodeError: 'ascii' codec can't encode characters in
  position 16-18`——报错跟真实原因（参数形态错了）完全对不上。现在两种形态都收：
  ① `owner/repo` 直接用；② 本地仓库路径 → 问 git remote 要。
  """
  raw = (getattr(a, 'repo', None) or '').strip()
  if not raw:
    cfg = ROOT / 'tools' / 'gh-login' / 'ghctl-default.txt'
    if cfg.exists():
      return cfg.read_text(encoding='utf-8').strip()
    return 'Uneadlight/fatfish-lab'

  if re.fullmatch(r'[\w.-]+/[\w.-]+', raw):
    return raw

  path = Path(raw).expanduser()
  if path.is_dir() and (path / '.git').exists():
    import subprocess

    git = ROOT / 'tools' / 'git' / 'cmd' / 'git.exe'
    if git.exists():
      r = subprocess.run((str(git), '-C', str(path), 'remote', 'get-url', 'origin'),
                         capture_output=True, text=True, encoding='utf-8')
      m = re.search(r'github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$', (r.stdout or '').strip())
      if m:
        return m.group(1)

  raise SystemExit(
    '[FAIL:用途错误] --repo 要 owner/repo（如 Uneadlight/fatfish-lab），'
    f'或者一个带 origin remote 的本地仓库路径；收到：{raw}'
  )


def cmd_ci(a: argparse.Namespace) -> int:
  sha = a.sha or 'HEAD'
  if a.wait:
    print(f'等 {a.wait}s 让 CI 起来 …')
    time.sleep(a.wait)

  slug = _slug(a)
  code, data = _gh('GET', f'/repos/{slug}/commits/{sha}/check-runs')
  if code != 200:
    print(f'[FAIL:执行失败] check-runs {code}: {data.get("error", "")}')
    return 1

  runs = data.get('check_runs', [])
  print(f'{slug} @ {sha} → {len(runs)} 个 check run')
  if not runs:
    print('  （还没有 run，可能仍在排队）')
  for r in runs:
    print(f'  {r["name"]:<30} {r["status"]:<12} {r.get("conclusion") or "-"}')

  code2, st = _gh('GET', f'/repos/{slug}/commits/{sha}/status')
  if code2 == 200:
    print(f'合并状态：{st.get("state")}（{st.get("total_count", 0)} 个 status）')

  pending = [r for r in runs if r['status'] != 'completed']
  failed = [r for r in runs if r.get('conclusion') not in (None, 'success', 'skipped')]
  if pending:
    print(f'\n[WAIT] 还有 {len(pending)} 个未完成')
    return 2
  if failed:
    print(f'\n[FAIL] {len(failed)} 个失败')
    return 1
  if runs:
    print('\n[OK] 全部通过')
  return 0


def cmd_plugins(a: argparse.Namespace) -> int:
  base = Path(a.profile) if a.profile else Path.home() / '.dsh' / 'profiles' / 'desktop'
  pkg = base / 'package.json'
  if not pkg.exists():
    return _fail(2, f'找不到 profile: {pkg}')
  deps = json.loads(pkg.read_text(encoding='utf-8')).get('dependencies', {})
  node = base / 'node_modules'

  rows: list[tuple[str, str, str, str]] = []
  for name in sorted(deps):
    meta_path = node / name / 'package.json'
    if not meta_path.exists():
      rows.append((name, 'MISSING', '', ''))
      continue
    try:
      meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except Exception as exc:  # noqa: BLE001 - 坏 JSON 也要列出来
      rows.append((name, 'BADJSON', '', str(exc)[:40]))
      continue
    client = 'Y' if (meta.get('dsh') or {}).get('client') else '-'
    desc = ' '.join(str(meta.get('description') or '').split())[:88]
    rows.append((name, str(meta.get('version') or ''), client, desc))

  for name, ver, client, desc in rows:
    print(f'{name:<34} {ver:<10} {client:<2} {desc}')
  total = len(rows)
  with_client = sum(1 for r in rows if r[2] == 'Y')
  print(f'TOTAL {total}  (client bundle: {with_client})')
  return 0


def cmd_issue(a: argparse.Namespace) -> int:
  slug = _slug(a)
  if a.comment_file:
    text = Path(a.comment_file).read_text(encoding='utf-8')
    code, data = _gh('POST', f'/repos/{slug}/issues/{a.num}/comments', {'body': text})
    if code != 201:
      print(f'[FAIL:执行失败] comment {code}: {data.get("error", "")}')
      return 1
    print(f'[OK] comment {data.get("id")}  {data.get("html_url")}')

  if a.close:
    code, data = _gh('PATCH', f'/repos/{slug}/issues/{a.num}', {'state': 'closed', 'state_reason': 'completed'})
    if code != 200:
      print(f'[FAIL:执行失败] close {code}: {data.get("error", "")}')
      return 1
    print(f'[OK] issue closed  state={data.get("state")}  reason={data.get("state_reason")}')

  if not a.comment_file and not a.close:
    code, data = _gh('GET', f'/repos/{slug}/issues/{a.num}')
    if code != 200:
      print(f'[FAIL:执行失败] issue {code}: {data.get("error", "")}')
      return 1
    print(f'#{data.get("number")} [{data.get("state")}] {data.get("title")}')
    print(f'  {data.get("html_url")}')
  return 0


# ------------------------------------------------------------ journal


def cmd_commit(a: argparse.Namespace) -> int:
  """提交 + 推送：一次绕开四个坑（中文 message 编码、token 落进 .git/config、
  非临时性失败也重试、推完不回读校验）。

  这四条都是 2026-10-30~11-02 真实踩过的，每写一次提交脚本就要重新填一遍坑。
  """
  import base64
  import subprocess
  import tempfile

  git = Path(r'D:\work\tools\git\cmd\git.exe')
  if not git.exists():
    print(f'[FAIL:能力缺失] 找不到便携版 git：{git}')
    return 2

  repo = Path(a.repo).expanduser().resolve() if a.repo else ROOT / 'repos' / 'dafeiyu-lab'
  if not (repo / '.git').exists():
    print(f'[FAIL:用途错误] 不是 git 仓库：{repo}')
    return 2

  if a.msg_file:
    text = Path(a.msg_file).read_text(encoding='utf-8')
  elif a.message:
    text = a.message
  else:
    print('[FAIL:用途错误] 需要 -m/--message 或 --msg-file')
    return 2
  text = text.replace('\r\n', '\n').lstrip('\ufeff').strip()
  if not text:
    print('[FAIL:用途错误] message 是空的')
    return 2

  def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run((str(git), '-C', str(repo), *args),
                       capture_output=True, text=True, encoding='utf-8')
    if check and r.returncode != 0:
      raise RuntimeError((r.stderr or r.stdout).strip()[:600])
    return r

  try:
    # ── 1. 暂存 ──────────────────────────────────────────────
    if a.files:
      run('add', '--', *a.files)
    elif a.all:
      run('add', '-A')
    else:
      # 默认只暂存已跟踪文件的改动：不把没打算提交的新文件顺手带进去
      run('add', '-u')
    staged = [x for x in run('diff', '--cached', '--name-only').stdout.splitlines() if x.strip()]

    # 未跟踪文件也要数出来——**不管暂存区空不空**。
    # 2026-11-02 真事故：`lab stage` 拷了 20 个文件、`lab commit` 只提交了 2 个，
    # 因为默认 `git add -u` 不含新文件，而当时"暂存区不为空"所以跳过了检查，
    # 结果是 lab.py（引用了 ocr_run.py）推上去了、ocr_run.py 没推——远端断。
    # 判据：暂存区有东西不代表没漏东西。
    untracked = [
      ln[3:] for ln in run('status', '--porcelain').stdout.splitlines()
      if ln.startswith('?? ')
    ]

    ahead = run('rev-list', '--count', '@{u}..HEAD', check=False)
    unpushed = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else -1

    # 「暂存区为空就收工」是 ghctl 那次踩过的坑：commit 成功、push 失败后再跑，
    # 什么都不做，用户以为推上去了其实没有。所以这里要再问一句有没有别的活。
    if not staged:
      # 第二个同类坑（2026-11-02 复发）：默认只 `git add -u`（已跟踪文件），
      # 新写的文件会被 git 当成未跟踪，于是"暂存区为空"→ 报"无事可做"，
      # 用户以为提交了、远端其实没有。这里必须把未跟踪文件也数出来并说清楚。
      if untracked:
        print(f'[FAIL:用途错误] 暂存区为空，但有 {len(untracked)} 个未跟踪文件没提交：')
        for u in untracked[:8]:
          print(f'    {u}')
        if len(untracked) > 8:
          print(f'    …还有 {len(untracked) - 8} 个')
        print('  → 默认只提交已跟踪文件的改动；要带上它们用 `--all` 或 `--files <路径…>`')
        return 2
      if unpushed == 0:
        print('[OK] 没有改动、也没有未推送的提交，无事可做')
        return 0
      if unpushed > 0:
        print(f'[INFO] 没有新改动，但有 {unpushed} 个提交没推上去 → 只推送')
      else:
        print('[WARN] 没有改动，也判断不出有没有未推送（当前分支没有上游）；不猜，退出')
        return 1
    elif untracked:
      # 暂存区有东西、但还有未跟踪文件——这是最危险的情形：看着提交成功了，
      # 实际上少了新写的文件。默认模式下直接拦下，要求显式说明。
      print(f'[FAIL:用途错误] 已暂存 {len(staged)} 个文件，但还有 {len(untracked)} 个未跟踪文件会漏掉：')
      for u in untracked[:8]:
        print(f'    {u}')
      if len(untracked) > 8:
        print(f'    …还有 {len(untracked) - 8} 个')
      print('  → 如果它们该进这次提交，用 `--all`；如果只提交其中几个，用 `--files <路径…>`')
      print('  → 如果它们本来就不该进（构建产物等），把它们加进 .gitignore')
      return 2

    if a.dry:
      print(f'[DRY] 仓库：{repo}')
      print(f'[DRY] 待暂存：{len(staged)} 个文件' + (f'，如 {staged[0]}' if staged else ''))
      print(f'[DRY] 首行：{text.splitlines()[0]}')
      return 0

    # ── 2. 提交（message 走文件：Windows 命令行参数按 GBK 传，中文 -m 会落库变乱码）
    if staged:
      with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                       suffix='.txt', delete=False) as fh:
        fh.write(text + '\n')
        mfile = fh.name
      try:
        run('-c', 'i18n.commitEncoding=utf-8', 'commit', '-F', mfile)
      finally:
        Path(mfile).unlink(missing_ok=True)

      got = run('log', '-1', '--pretty=%B').stdout.strip()
      if got.splitlines()[0] != text.splitlines()[0]:
        print('[FAIL:执行失败] 提交说明回读不一致（编码可能出问题）')
        print('  想要：' + text.splitlines()[0])
        print('  实际：' + got.splitlines()[0])
        return 1
      print('[OK] commit ' + run('log', '-1', '--oneline').stdout.strip())

    if a.no_push:
      print('[OK] --no-push，跳过推送')
      return 0

    # ── 3. 推送（只对临时性失败重试）─────────────────────────
    token_file = Path.home() / '.dsh' / 'github-token.txt'
    if not token_file.exists():
      print(f'[FAIL:权限被拒] 没有 token 文件：{token_file}')
      print('  你可能要做什么：跑一次 tools/gh-login/github_device_login.py 授权')
      return 2
    token = token_file.read_text(encoding='utf-8').strip()
    hdr = 'AUTHORIZATION: basic ' + base64.b64encode(f'x-access-token:{token}'.encode()).decode()

    TRANSIENT = ('connection reset', 'connection refused', 'timed out', 'recv failure',
                 'failed to connect', 'could not connect', 'network is unreachable',
                 'remote end hung up', 'early eof', 'http 408', 'http 429',
                 'http 500', 'http 502', 'http 503', 'http 504')
    last = ''
    # 第一次真用就发现 2/4/8 秒不够：网络抖动恢复常要半分钟（实测三次共 14 秒
    # 全挂，隔一分钟再手动推就成功了）。所以退到 2/5/10/20，总共约 37 秒。
    backoff = (2, 5, 10, 20)
    for attempt, wait in enumerate(backoff, 1):
      r = run('-c', f'http.extraheader={hdr}', '-c', 'http.version=HTTP/1.1',
              'push', 'origin', 'HEAD', check=False)
      out = (r.stdout + r.stderr).replace(hdr, '<auth>').strip()
      if r.returncode == 0:
        print('[OK] push 成功')
        if out:
          print('  ' + out.splitlines()[-1])
        return 0
      last = out[:400]
      if not any(p in out.lower() for p in TRANSIENT):
        print('[FAIL:执行失败] 非临时性失败，不重试（认证 / 非快进 / refspec 问题）')
        print('  ' + last)
        return 1
      print(f'[WARN] 第 {attempt} 次推送失败（临时性），退避 {wait}s')
      time.sleep(wait)
    print('[FAIL:执行失败] 连续四次都是临时性失败，放弃')
    print('  ' + last)
    print('  你可能要做什么：过一两分钟再跑一次；如果是长期连不上，检查网络或代理')
    return 1

  except RuntimeError as exc:
    print(f'[FAIL:执行失败] {exc}')
    return 1


def cmd_reconcile(a: argparse.Namespace) -> int:
  """记录对账：把决策日志、账本、git log 摆在一起，只报「需要一句解释」的地方。

  实现在同目录的 reconcile.py——它要单独跑（`py tools/lab/reconcile.py`），
  这里只做转调，好处是 `lab --help` 里能看见它，不用另外记一条路径。
  """
  script = Path(__file__).with_name('reconcile.py')
  if not script.exists():
    print(f'[FAIL:能力缺失] 找不到 {script}')
    return 2

  argv = [sys.executable, str(script)]
  if getattr(a, 'log', ''):
    argv += ['--log', a.log]
  if getattr(a, 'days', 0):
    argv += ['--days', str(a.days)]
  if getattr(a, 'md', ''):
    argv += ['--md', a.md]
  if getattr(a, 'selftest', False):
    argv.append('--selftest')

  import subprocess

  return subprocess.call(argv)


def cmd_journal(a: argparse.Namespace) -> int:
  """看最近的动作记录，并标出「有 start 没 done」的未完成项。"""
  if not JOURNAL.exists():
    print('还没有 journal（等你第一次跑 lab stage 就会生成）')
    return 0
  rows = []
  for line in JOURNAL.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      rows.append(json.loads(line))
    except json.JSONDecodeError:
      continue

  # 判断未完成：一个 start 之后没有同类的 done 或 aborted
  open_actions: dict[str, dict] = {}
  for row in rows:
    action = str(row.get('action', ''))
    if action.endswith('.start'):
      open_actions[action[: -len('.start')]] = row
    elif action.endswith(('.done', '.aborted')):
      open_actions.pop(action[: action.rfind('.')], None)

  show = rows[-a.limit :] if a.limit > 0 else rows
  print(f'journal: {JOURNAL}  共 {len(rows)} 条，显示最近 {len(show)} 条')
  for row in show:
    detail = ''
    for key in ('files', 'reason', 'path_hits', 'scrubbed'):
      if key in row:
        value = row[key]
        detail = f'  {key}={len(value) if isinstance(value, list) else value}'
        break
    print(f'  {row.get("at", "?")}  {row.get("action", "?"):16}{detail}')

  if open_actions:
    print('\n[未完成] 这些动作留下了 start 却没有 done：')
    for name, row in open_actions.items():
      print(f'  {row.get("at", "?")}  {name}  （上次可能中途崩了，核对现场再重跑）')
    return 1
  print('\n[AUDIT] 没有未完成的动作')
  return 0


# ----------------------------------------------------------- observe


OBSERVE_LOG = ROOT / '自进化' / 'observe.jsonl'
OBSERVE_MODE = ROOT / '自进化' / 'observe-mode.json'
SKILL_PATHS = (
  ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md',
  Path.home() / '.dsh' / 'memory' / 'memories.json',
)

# 升级 / 降级门槛。抄 dsh-superagent 的 observe 档，但把「什么时候能升 auto」
# 写成数字而不是感觉——没有这两条，observe 会变成永久只读的摆设。
PROMOTE_AFTER = 3
DEMOTE_ON_MISRUN = 1


def _policy_stamp() -> str:
  """规则版本标记：SKILL.md 和记忆库的哈希前缀。

  为什么记这个：三个月后回头看一条「would accept」，如果不知道它当时依据的是
  哪版规则，这条记录就只是一句话。规则变了而记录不变，等于没记。
  """
  import hashlib

  digest = hashlib.sha256()
  parts = []
  for path in SKILL_PATHS:
    if path.is_file():
      digest.update(path.read_bytes())
      parts.append(path.name)
    else:
      digest.update(b'missing:' + str(path).encode())
      parts.append(f'{path.name}:missing')
  return '+'.join(parts) + '@' + digest.hexdigest()[:8]


def _read_jsonl(path: Path) -> list[dict]:
  rows = []
  if not path.is_file():
    return rows
  for line in path.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line:
      try:
        rows.append(json.loads(line))
      except json.JSONDecodeError:
        continue
  return rows


def _load_modes() -> dict:
  if OBSERVE_MODE.is_file():
    try:
      return json.loads(OBSERVE_MODE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
      pass
  return {}


def _save_modes(modes: dict) -> None:
  OBSERVE_MODE.parent.mkdir(parents=True, exist_ok=True)
  OBSERVE_MODE.write_text(json.dumps(modes, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def cmd_observe(a: argparse.Namespace) -> int:
  action = a.action
  modes = _load_modes()
  rows = _read_jsonl(OBSERVE_LOG)

  if action == 'list':
    pending = [r for r in rows if r.get('status', 'pending') == 'pending']
    if a.kind:
      pending = [r for r in pending if r.get('kind') == a.kind]
    if not pending:
      print('没有待处理的 observe 条目')
    else:
      print(f'待处理 {len(pending)} 条：')
      for r in pending:
        print(f'  {r.get("id")}  [{r.get("kind")}]  {r.get("what")}')
        print(f'    理由: {r.get("why")}')
        if r.get('estimate'):
          print(f'    预估: {r.get("estimate")}')
        print(f'    规则版本: {r.get("policy")}')
    print('\n当前档位：')
    if modes:
      for kind, mode in sorted(modes.items()):
        print(f'  {kind:20} {mode.get("mode")}  (认可 {mode.get("approved", 0)} / 误执行 {mode.get("misruns", 0)})')
    else:
      print('  （全部默认 observe —— 只记录，不执行）')
    return 0

  if action == 'add':
    if not (a.kind and a.what and a.why):
      return _fail(1, 'add 需要 --kind --what --why')
    mode = modes.get(a.kind, {}).get('mode', 'observe')
    if mode == 'auto':
      print(f'[note] {a.kind} 已是 auto，这条记下来也会照做；仍留档以便回溯')
    base = f"{time.strftime('%m%d-%H%M%S')}-{a.kind[:12]}"
    rid = base
    taken = {r.get('id') for r in rows}
    suffix = 2
    while rid in taken:  # 同一秒记两条同类会撞 id，加序号而不是覆盖
      rid = f'{base}-{suffix}'
      suffix += 1
    row = {
      'at': time.strftime('%Y-%m-%d %H:%M:%S'),
      'id': rid,
      'kind': a.kind,
      'what': a.what,
      'why': a.why,
      'estimate': a.estimate or '',
      'policy': _policy_stamp(),
      'status': 'pending',
    }
    OBSERVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with OBSERVE_LOG.open('a', encoding='utf-8', newline='\n') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'[记录] {rid}  [{a.kind}] {a.what}')
    print(f'  规则版本: {row["policy"]}')
    return 0

  if action == 'ack':
    if not a.id:
      return _fail(1, 'ack 需要 --id')
    hit = None
    for r in rows:
      if r.get('id') == a.id and r.get('status', 'pending') == 'pending':
        r['status'] = 'approved'
        r['acked_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        hit = r
        break
    if not hit:
      return _fail(2, f'找不到待处理条目 {a.id}')
    OBSERVE_LOG.write_text(
      '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8', newline='\n'
    )
    kind = hit.get('kind')
    entry = modes.setdefault(kind, {'mode': 'observe', 'approved': 0, 'misruns': 0})
    entry['approved'] = int(entry.get('approved', 0)) + 1
    _save_modes(modes)
    print(f'[认可] {a.id}  {kind} 累计认可 {entry["approved"]}')
    if entry['approved'] >= PROMOTE_AFTER and entry.get('mode') == 'observe':
      print(f'  达到门槛（连续 {PROMOTE_AFTER} 条），可以 lab observe promote --kind {kind}')
    return 0

  if action == 'promote':
    if not a.kind:
      return _fail(1, 'promote 需要 --kind')
    entry = modes.setdefault(a.kind, {'mode': 'observe', 'approved': 0, 'misruns': 0})
    if entry.get('approved', 0) < PROMOTE_AFTER:
      return _fail(1, f'{a.kind} 只被认可 {entry.get("approved", 0)} 次，门槛是 {PROMOTE_AFTER}')
    if entry.get('misruns', 0) >= DEMOTE_ON_MISRUN:
      return _fail(1, f'{a.kind} 有过误执行，先把误执行次数清零再说（先查清那次为什么错）')
    entry['mode'] = 'auto'
    entry['promoted_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    entry['promoted_at_policy'] = _policy_stamp()
    _save_modes(modes)
    print(f'[升级] {a.kind} → auto（依据：连续 {entry["approved"]} 条被认可、零误执行）')
    return 0

  if action == 'demote':
    if not a.kind:
      return _fail(1, 'demote 需要 --kind')
    entry = modes.setdefault(a.kind, {'mode': 'observe', 'approved': 0, 'misruns': 0})
    entry['mode'] = 'observe'
    entry['misruns'] = int(entry.get('misruns', 0)) + 1
    entry['demoted_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    entry['demote_reason'] = a.reason or ''
    _save_modes(modes)
    print(f'[降级] {a.kind} → observe（误执行 {entry["misruns"]} 次）')
    if a.reason:
      print(f'  原因: {a.reason}')
    return 0

  if action == 'stamp':
    print(_policy_stamp())
    return 0

  return _fail(1, f'未知动作: {action}')


# ---------------------------------------------------------------- ocr


OCR_PY = ROOT / 'tools' / 'ocr-venv312' / 'Scripts' / 'python.exe'
OCR_RUN = ROOT / 'tools' / 'lab' / 'ocr_run.py'


def cmd_ocr(a: argparse.Namespace) -> int:
  """图片转文字。转发给 ocr-venv312，因为 rapidocr 只装在那儿。"""
  if not OCR_PY.exists():
    return _fail(2, f'找不到 OCR 解释器：{OCR_PY}（重新建 venv 并装 rapidocr_onnxruntime）')
  if not OCR_RUN.exists():
    return _fail(2, f'找不到 ocr_run.py：{OCR_RUN}')

  from pathlib import Path as _P

  img = _P(a.image)
  if not img.exists():
    return _fail(2, f'图片不存在：{img}')

  cmd = [str(OCR_PY), str(OCR_RUN), str(img), '--min-score', str(a.min_score)]
  try:
    proc = subprocess.run(cmd, capture_output=True, timeout=a.timeout, check=False)  # noqa: S603
  except subprocess.TimeoutExpired:
    return _fail(3, f'OCR 超时（{a.timeout}s）：{img}')

  out = proc.stdout.decode('utf-8', errors='replace').strip()
  if not out:
    err = proc.stderr.decode('utf-8', errors='replace').strip()[-400:]
    return _fail(4, f'OCR 没有输出（exit={proc.returncode}）{chr(10)}{err}')

  try:
    data = json.loads(out)
  except json.JSONDecodeError:
    return _fail(4, f'OCR 输出不是 JSON：{out[:200]}')

  if not data.get('ok'):
    return _fail(4, f'OCR 失败：{data.get("error")}')

  lines = data.get('lines', [])
  if a.json:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

  if not lines:
    print(f'[OK] {img.name}：没有识别到文字（{data.get("elapsed")}s）')
    return 0

  if a.layout:
    for ln in lines:
      x = int(min(p[0] for p in ln['box']))
      y = int(min(p[1] for p in ln['box']))
      print(f'({x:4d},{y:4d}) {ln["score"]:.2f}  {ln["text"]}')
  else:
    for ln in lines:
      print(ln['text'])

  print(f'[OK] {len(lines)} 行，{data.get("elapsed")}s', file=sys.stderr)
  return 0


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog='lab', description='工作区小工具（一次性的收成子命令）')
  sub = parser.add_subparsers(dest='cmd', required=True)

  lg = sub.add_parser('log', help='决策日志追加 / 查看')
  lg.add_argument('--mark', help='时间锚点，同时用于幂等判断')
  lg.add_argument('--title', help='条目标题')
  lg.add_argument('--body-file', dest='body_file', help='正文 markdown 文件')
  lg.add_argument('--stdin', action='store_true', help='从标准输入读正文')
  lg.add_argument('--dry', action='store_true', help='只打印不写入')
  lg.add_argument('--tail', type=int, default=0, help='只列出最后 N 段的首行')
  lg.set_defaults(func=cmd_log)

  st = sub.add_parser('stage', help='按清单把产出拷进发布仓库（脱敏 + 安全扫描）')
  st.add_argument('--plan', help='发布清单，默认 tools/lab/release-plan.txt')
  st.add_argument('--repo', help='目标仓库目录，默认 repos/dafeiyu-lab')
  st.add_argument('--dry', action='store_true', help='只打印不拷贝')
  st.add_argument('--skip-scan', dest='skip_scan', action='store_true', help='跳过安全扫描')
  st.set_defaults(func=cmd_stage)

  cm = sub.add_parser('commit', help='提交 + 推送（中文安全 / token 不进 config / 只重试临时性失败 / 回读校验）')
  cm.add_argument('-m', '--message', help='提交说明；多行用 --msg-file 更稳')
  cm.add_argument('--msg-file', dest='msg_file', help='从 UTF-8 文件读提交说明')
  cm.add_argument('--repo', help='仓库目录，默认 repos/dafeiyu-lab')
  cm.add_argument('--files', nargs='*', help='只暂存这些路径')
  cm.add_argument('--all', action='store_true', help='暂存全部改动（含未跟踪的新文件）')
  cm.add_argument('--no-push', dest='no_push', action='store_true', help='只提交不推送')
  cm.add_argument('--dry', action='store_true', help='只打印要做什么，不动仓库')
  cm.set_defaults(func=cmd_commit)

  jr = sub.add_parser('journal', help='看动作记录，标出「有 start 没 done」的未完成项')
  jr.add_argument('--limit', type=int, default=20, help='显示最近 N 条，默认 20；0 = 全部')
  jr.set_defaults(func=cmd_journal)

  rc = sub.add_parser('reconcile', help='记录对账：日志 / 账本 / git 摆在一起，只报差异不判错')
  rc.add_argument('--log', default='', help='换一份日志来对')
  rc.add_argument('--days', type=int, default=0, help='只看最近 N 天')
  rc.add_argument('--md', default='', help='另存为 markdown')
  rc.add_argument('--selftest', action='store_true', help='先证明检查抓得到，再相信它报的 OK')
  rc.set_defaults(func=cmd_reconcile)

  ob = sub.add_parser('observe', help='观察档：只记录「我会做什么」，不做；攒够认可才升 auto')
  ob.add_argument('action', choices=['list', 'add', 'ack', 'promote', 'demote', 'stamp'])
  ob.add_argument('--kind', help='任务类别，如 cleanup / refactor / doc / optimize')
  ob.add_argument('--what', help='打算做什么（一句话）')
  ob.add_argument('--why', help='为什么该做（判据）')
  ob.add_argument('--estimate', help='预估成本，如「20 分钟」「3 次调用」')
  ob.add_argument('--id', help='条目 id（ack 用）')
  ob.add_argument('--reason', help='降级原因（demote 用）')
  ob.set_defaults(func=cmd_observe)

  ar = sub.add_parser('asar', help='读 app.asar（不解包）')
  ar.add_argument('action', choices=['list', 'desc', 'read'])
  ar.add_argument('keyword', nargs='?', help='list/desc 的关键字过滤；read 的包内路径')
  ar.add_argument('--max', type=int, default=1200, help='read 最多输出多少字符，0 表示全部')
  ar.set_defaults(func=cmd_asar)

  ci = sub.add_parser('ci', help='查某个 commit 的 CI 状态')
  ci.add_argument('sha', nargs='?', default='HEAD', help='commit sha，默认 HEAD')
  ci.add_argument('--wait', type=int, default=0, help='先等 N 秒让 CI 起来')
  ci.add_argument('--repo', help='owner/name，默认读 ghctl 的默认仓库')
  ci.set_defaults(func=cmd_ci)

  pl = sub.add_parser('plugins', help='列出 profile 里已装插件的版本 / 客户端 bundle / 描述')
  pl.add_argument('--profile', help='profile 目录，默认 ~/.dsh/profiles/desktop')
  pl.set_defaults(func=cmd_plugins)

  iss = sub.add_parser('issue', help='看 / 评论 / 关 issue')
  iss.add_argument('num', type=int, help='issue 编号')
  iss.add_argument('--comment-file', dest='comment_file', help='把这个 markdown 文件作为评论发出去')
  iss.add_argument('--close', action='store_true', help='评论之后（或单独）关闭')
  iss.add_argument('--repo', help='owner/name')
  iss.set_defaults(func=cmd_issue)

  oc = sub.add_parser('ocr', help='图片转文字（RapidOCR，本地离线，跑在 ocr-venv312 里）')
  oc.add_argument('image', help='图片路径（png/jpg/webp/bmp/tiff）')
  oc.add_argument('--json', action='store_true', help='输出完整 JSON（含每行坐标与置信度）')
  oc.add_argument('--layout', action='store_true', help='按坐标输出，保留版面位置')
  oc.add_argument('--min-score', dest='min_score', type=float, default=0.3, help='置信度下限，默认 0.3')
  oc.add_argument('--timeout', type=int, default=180, help='超时秒数，默认 180')
  oc.set_defaults(func=cmd_ocr)

  return parser


def main(argv=None) -> int:
  args = build_parser().parse_args(argv)
  return args.func(args)


if __name__ == '__main__':
  sys.exit(main())
