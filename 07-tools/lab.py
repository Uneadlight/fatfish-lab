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

REQUIRED_SECTIONS = ('做了什么', '为什么', '取舍', '教训')


def _has_section(body: str, name: str) -> bool:
  """这一节算不算写了：`**做了什么**`（行内加粗）或 `## 做了什么`（markdown 标题）都算。

  2026-11-03 修：原来只认 `**X**`，我自己用 `## X` 写就被误报。
  判据应该是「有没有这个分段」，不是「用哪种标记语法」。
  """
  import re as _re
  pat = r'(\*\*\s*' + _re.escape(name) + r'\s*\*\*)|(^#{2,4}\s*' + _re.escape(name) + r')'
  return _re.search(pat, body, _re.MULTILINE) is not None

JOURNAL = ROOT / 'tools' / 'lab' / 'journal.jsonl'
# 纠正日志：用户纠正我时，记下「原话 / 我原来的想法 / 改成了什么」。
# 记忆库存结论（对的是什么），这里存过程（我原来错在哪）——后者才是能复盘的东西。
CORRECTIONS = ROOT / '自进化' / 'corrections.jsonl'


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
  missing = [s for s in REQUIRED_SECTIONS if not _has_section(body, s)]
  if missing:
    print(f'[WARN] 缺小标题: {", ".join(missing)}（写 **做了什么** 或 ## 做了什么 都算）')

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


def _auto_lab_entries(pairs: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
  """tools/lab 下的脚本和数据文件自动进发布清单（P12：加工具不必再手写一行）。

  跳过 `_` 开头（一次性/内部修 BOM 之类）和 `test_` 开头（测试）。
  清单里已写过的按 resolve() 去重，先手写也不会重复发布。
  """
  base = Path(__file__).resolve().parent
  covered = {p.resolve() for p, _ in pairs}
  extra: list[tuple[Path, str]] = []
  for p in sorted(base.iterdir()):
    if not p.is_file() or p.suffix not in {'.py', '.json'}:
      continue
    if p.name.startswith('_') or p.name.startswith('test_'):
      continue
    if p.resolve() in covered:
      continue
    extra.append((p, f'07-tools/{p.name}'))
  return extra


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
  auto = [] if getattr(a, 'no_auto', False) else _auto_lab_entries(pairs)
  if auto:
    print(f'[AUTO] lab 里新增的 {len(auto)} 个（清单没写，自动补）：')
    for src, rel in auto:
      print(f'  {src.name} -> {rel}')
    pairs = pairs + auto
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

    # ── 1.5 提交说明的排版自检（只提示，绝不阻断）────────────────
    # 为什么只提示不拦：lint 想解决的是「人读不下去」，如果拦下来，
    # 就会变成「为了过检查而改文档」，那就反了。2026-11-03 用户给的排版五律
    # （短句成行 / 小标题要短 / 每条一个事实 / 留白 / 能列表就不写段落）
    # 在这里只挑两种最硬的毛病：首行过长、段落过密。
    if not getattr(a, 'no_lint', False):
      lines = text.splitlines()
      warns: list[str] = []
      if lines and len(lines[0]) > 72:
        warns.append(f'首行 {len(lines[0])} 字，超过 72（git log 会被截断）')
      run_len = 0
      for ln in lines[1:]:
        if ln.strip():
          run_len += 1
          if run_len == 6:
            warns.append('有一段连续 6 行以上没留白，读起来会挤')
            break
        else:
          run_len = 0
      for i, ln in enumerate(lines, 1):
        if len(ln) > 120:
          warns.append(f'第 {i} 行 {len(ln)} 字，超过 120')
      if warns:
        print('[lint] 提交说明有几处读起来费劲（只提示，不阻断）：')
        for w in warns:
          print(f'   · {w}')
        print('   → 觉得无所谓就继续；下次不想看到加 --no-lint')

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
      _review_remind()
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
        _review_remind()
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


# ---------------------------------------------------------------- correction

# 起因：吸收社区插件 `dsh-run2skill` 的核心思路——「把对话里的纠正变成可复用的东西」。
# 我的记忆库存的是结论（对的是什么），缺的正是「我原来错在哪」。
# 没有"原来的想法"，纠正就退化成一条新规矩，看不出自己犯的是哪一类毛病。


def cmd_correction(a: argparse.Namespace) -> int:
  """纠正日志：用户纠正我时，记下原话 / 我原来的想法 / 改成了什么。"""
  if a.action == 'add':
    if not a.said:
      return _fail(1, '--said 必填（用户当时说了什么）')
    rec = {
      'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
      'date': time.strftime('%Y-%m-%d'),
      'said': a.said.strip(),
      'was': (a.was or '').strip(),
      'now': (a.now or '').strip(),
      'tags': a.tags or [],
    }
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    with CORRECTIONS.open('a', encoding='utf-8', newline='\n') as fh:
      fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
      fh.flush()
      import os as _os

      _os.fsync(fh.fileno())
    # 写后回读，确认真的能解析（"写了"≠"写对了"）
    try:
      last = CORRECTIONS.read_text(encoding='utf-8').strip().splitlines()[-1]
      json.loads(last)
    except Exception as exc:  # noqa: BLE001
      return _fail(2, f'追加后回读失败：{exc}')
    print(f'[OK] 已记一条纠正 -> {CORRECTIONS}')
    print(f'     原话：{rec["said"][:60]}')
    if rec['was']:
      print(f'     原来：{rec["was"][:60]}')
    if rec['now']:
      print(f'     改成：{rec["now"][:60]}')
    return 0

  if not CORRECTIONS.exists():
    print('（还没有纠正记录）')
    return 0
  rows = [json.loads(x) for x in CORRECTIONS.read_text(encoding='utf-8').splitlines() if x.strip()]

  if a.action == 'list':
    tail = rows[-a.limit:]
    print(f'共 {len(rows)} 条，最近 {len(tail)} 条：\n')
    for r in tail:
      tags = ' '.join(f'#{t}' for t in r.get('tags') or [])
      print(f'{r["ts"]}  {tags}')
      print(f'  原话：{r["said"][:80]}')
      if r.get('was'):
        print(f'  原来：{r["was"][:70]}')
      if r.get('now'):
        print(f'  改成：{r["now"][:70]}')
      print()
    return 0

  if a.action == 'stats':
    from collections import Counter

    c = Counter(t for r in rows for t in (r.get('tags') or ['(无标签)']))
    print(f'共 {len(rows)} 条纠正，按标签：\n')
    for k, n in c.most_common():
      print(f'  {k:16} {n:3}')
    return 0

  return _fail(1, f'未知动作：{a.action}')


# ---------------------------------------------------------------- config

# 起因：社区插件 dsh-config-manager（65,391 行）专门做「备份/恢复/迁移 DSH 配置」，
# 而我一直在手工 Copy-Item。不装它（1,686 文件 / 25 MB / 要重启），吸收三条思路自己做：
#   ① 白名单式备份  ② secrets 永不进备份但记下排除了哪几个  ③ 每次生成 manifest（sha256）

CONFIG_BACKUP = Path(__file__).with_name('config_backup.py')


def cmd_config(a: argparse.Namespace) -> int:
  """转调 config_backup.py（DSH 配置备份，不含 secrets）。"""
  if not CONFIG_BACKUP.exists():
    return _fail(2, f'找不到 config_backup.py：{CONFIG_BACKUP}')
  argv = [sys.executable, str(CONFIG_BACKUP)]
  if a.action == 'list':
    argv.append('--list')
  elif a.action == 'dry' or a.dry:
    argv.append('--dry')
  elif a.action == 'verify':
    # 验证最近一份
    root = ROOT / '备份'
    dirs = sorted(root.glob('config-*'), reverse=True)
    if not dirs:
      return _fail(2, '还没有任何 config 备份')
    return subprocess.call([
      sys.executable, str(Path(__file__).with_name('_verify_backup.py')), str(dirs[0])
    ])
  return subprocess.call(argv)


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
  st.add_argument('--no-auto', dest='no_auto', action='store_true',
                  help='不自动补 tools/lab 下新增的脚本（默认会自动补）')
  st.set_defaults(func=cmd_stage)

  cm = sub.add_parser('commit', help='提交 + 推送（中文安全 / token 不进 config / 只重试临时性失败 / 回读校验）')
  cm.add_argument('-m', '--message', help='提交说明；多行用 --msg-file 更稳')
  cm.add_argument('--msg-file', dest='msg_file', help='从 UTF-8 文件读提交说明')
  cm.add_argument('--repo', help='仓库目录，默认 repos/dafeiyu-lab')
  cm.add_argument('--files', nargs='*', help='只暂存这些路径')
  cm.add_argument('--all', action='store_true', help='暂存全部改动（含未跟踪的新文件）')
  cm.add_argument('--no-push', dest='no_push', action='store_true', help='只提交不推送')
  cm.add_argument('--no-lint', dest='no_lint', action='store_true', help='跳过 message 排版检查（默认只提示不阻断）')
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

  cr = sub.add_parser('correction', help='纠正日志：记下用户原话 / 我原来的想法 / 改成了什么')
  cr.add_argument('action', choices=['add', 'list', 'stats'], help='add 记一条 / list 看最近 / stats 按标签统计')
  cr.add_argument('--said', help='用户当时的原话（add 用）')
  cr.add_argument('--was', help='我原来的想法（add 用）')
  cr.add_argument('--now', help='改成什么了（add 用）')
  cr.add_argument('--tags', nargs='*', help='标签，如 编码 乱码 并发')
  cr.add_argument('--limit', type=int, default=5, help='list 显示最近几条，默认 5')
  cr.set_defaults(func=cmd_correction)

  cf = sub.add_parser('config', help='DSH 配置备份（白名单 / 不含 secrets / 带 manifest）')
  cf.add_argument('action', nargs='?', default='backup', choices=['backup', 'list', 'dry', 'verify'],
                  help='backup 备份（默认）/ list 看已有 / dry 只看会备份什么 / verify 验最近一份')
  cf.add_argument('--dry', action='store_true', help='等价于 action=dry')
  cf.set_defaults(func=cmd_config)

  cl = sub.add_parser('claims', help='完成声明的证据对账：我说的「做完了」，日志/提交/文件能不能接住')
  cl.add_argument('--date', help='YYYY-MM-DD（默认今天）')
  cl.add_argument('--file', help='直接查某个 md 文件')
  cl.add_argument('--all', action='store_true', help='全部日期汇总')
  cl.add_argument('--chat', action='store_true',
                  help='扫会话记录里我的回复（形式完成真正发生的地方）')
  cl.add_argument('--days', type=int, default=7, help='--chat 时看最近几天，默认 7')
  cl.add_argument('--json', action='store_true', help='JSON 输出')
  cl.add_argument('--selftest', action='store_true',
                  help='用人工标注回归判据本身（改 claims.py 后必跑）')
  cl.set_defaults(func=cmd_claims)

  fa = sub.add_parser('fact', help='事实核对：把我话里的数字/路径/版本号/行号逐个验证')
  fa.add_argument('text', nargs='*', help='要检查的文本（不给就走 stdin）')
  fa.add_argument('--file', help='从文件读文本')
  fa.set_defaults(func=cmd_fact)

  bal = sub.add_parser('balance', help='DeepSeek 余额 + 今日花费估算（抄自 dsh-balance-tracker）')
  bal.add_argument('--json', action='store_true', help='输出 JSON')
  bal.set_defaults(func=cmd_balance)

  sn = sub.add_parser('snapshot', help='文件快照：改文件前存一份，改坏了能退（抄自 dsh-local-devkit）')
  sn_sub = sn.add_subparsers(dest='snap_cmd', required=True)
  sn_now = sn_sub.add_parser('now', help='给某个文件拍快照')
  sn_now.add_argument('path')
  sn_list = sn_sub.add_parser('list', help='列出快照（按时间倒序）')
  sn_list.add_argument('--path', help='只看这个路径')
  sn_list.add_argument('--limit', type=int, default=20)
  sn_restore = sn_sub.add_parser('restore', help='恢复到某条快照（恢复前会再拍一次，可逆）')
  sn_restore.add_argument('id')
  sn_undo = sn_sub.add_parser('undo', help='回退这条路径的上一次（可连续调用 v3→v2→v1）')
  sn_undo.add_argument('path')
  sn.set_defaults(func=cmd_snapshot)

  ec = sub.add_parser('encoding', help='判编码 / 解码 / 修乱码（抄自 dsh-encoding）')
  ec.add_argument('rest', nargs=argparse.REMAINDER, help='detect/read/fix 及其参数，原样透传')
  ec.set_defaults(func=cmd_encoding)

  ss = sub.add_parser('sessions', help='会话管理：列清单 / 读原文 / 搜索（治「找不到以前的对话」）')
  ss.add_argument('keywords', nargs='*', help='搜索关键词（不给且无 --list/--show 时默认列清单）')
  ss.add_argument('--list', action='store_true', help='列出所有会话')
  ss.add_argument('--show', metavar='ID', help='打印某个会话的原文')
  ss.add_argument('--context', type=int, metavar='TURN',
                  help='配合 --show：重建 turn=N 那一刻的完整上下文（消息 + 工具调用与结果）')
  ss.add_argument('--before', type=int, default=1, help='配合 --context：往前多带几轮用户消息，默认 1')
  ss.add_argument('--head', action='store_true', help='配合 --show，从头而不是从尾')
  ss.add_argument('--all', action='store_true', help='搜索时也匹配我的回复')
  ss.add_argument('--days', type=float, default=0, help='只看最近 N 天')
  ss.add_argument('--limit', type=int, default=20)
  ss.add_argument('--stats', action='store_true', help='索引状态')
  ss.set_defaults(func=cmd_sessions)

  sc = sub.add_parser('selfcheck', help='机制随能力漂移：文档里的子命令/路径/计数跟磁盘对不对得上')
  sc.add_argument('--json', action='store_true')
  sc.add_argument('--only', type=int, help='只跑第 N 组（1 起）')
  sc.set_defaults(func=cmd_selfcheck)

  tl = sub.add_parser('tools', help='工具使用率：我有的工具里哪些一次都没调用过（治「装了不用」）')
  tl.add_argument('--top', type=int, default=0, help='只显示前 N 个（0=全部）')
  tl.add_argument('--never', action='store_true', help='只显示零使用清单')
  tl.set_defaults(func=cmd_tools)

  li = sub.add_parser('lint', help='文档排版检查：小标题过长 / 一行多事实 / 长段落 / 超长行（只提示不阻断）')
  li.add_argument('path', nargs='*', help='要检查的 md 文件（可多个；不给则查 SKILL.md 和决策日志）')
  li.add_argument('--max-title', type=int, default=8, help='小标题最多几个字，默认 8')
  li.add_argument('--max-line', type=int, default=120, help='单行最多几个字，默认 120')
  li.add_argument('--max-para', type=int, default=10, help='连续几行非空算一段，默认 10')
  li.add_argument('--max-facts', type=int, default=3, help='一行几个「；/、」算多事实，默认 3')
  li.add_argument('--strict', action='store_true', help='有问题就返回 1（默认只提示，返回 0）')
  li.set_defaults(func=cmd_lint)

  assets_p = sub.add_parser('assets', help='能力痕迹盘点：工作区每个目录/文件是什么、有没有说明、被谁引用')
  assets_p.add_argument('--json', action='store_true', help='输出 JSON')
  assets_p.add_argument('--top', type=int, default=0, help='只看最大的 N 个')
  assets_p.add_argument('--name', default=None, help='只看名字含该串的')
  assets_p.add_argument('--budget', type=float, default=4.0, help='每个目录算大小的秒数上限（默认 4）')
  assets_p.add_argument('--junk', action='store_true', help='只列「小件且无任何记录」的（清理候选）')
  assets_p.set_defaults(func=cmd_assets)

  sk = sub.add_parser('skill', help='能力熟练度：真熟 / 用得费劲 / 还没用上（只分两层，不分时间跨度）')
  sk.add_argument('--json', action='store_true', help='输出 JSON')
  sk.set_defaults(func=cmd_skill)

  tr = sub.add_parser('tier', help='开工前报数：这活有多少、配什么档、手边有什么能用的')
  tr.add_argument('task', help='任务描述（一句话）')
  tr.add_argument('--no-assets', action='store_true', help='跳过资产扫描（快 1 秒，但没推荐）')
  tr.add_argument('--json', action='store_true', help='输出 JSON')
  tr.set_defaults(func=cmd_tier)

  co = sub.add_parser('cost', help='这一步花了多少钱：从 bili.log 读 acp-usage，按小时聚合（只算 input）')
  co.add_argument('--hours', type=float, default=24, help='看最近几小时，默认 24')
  co.add_argument('--recent', type=int, default=0, help='只看最近 N 次请求')
  co.add_argument('--session', nargs='?', const='', default=None,
                  help='只看某个会话（不带值 = 日志里最新的会话），回答「这一轮花了多少」')
  co.add_argument('--json', action='store_true', help='输出 JSON')
  co.set_defaults(func=cmd_cost)

  er = sub.add_parser('errors', help='报错原文按工具聚合：只列原文和频次，不给建议动作')
  er.add_argument('--days', type=int, default=7, help='最近几天，默认 7')
  er.add_argument('--tool', default=None, help='只看某个工具的报错原文')
  er.add_argument('--top', type=int, default=20, help='每个工具列前几条，默认 20')
  er.add_argument('--json', action='store_true', help='输出 JSON')
  er.set_defaults(func=cmd_errors)

  st = sub.add_parser('steps', help='时间轴能不能拼起来：assistant 消息有多少带 turn/step')
  st.add_argument('--days', type=float, default=7.0, help='最近几天，默认 7')
  st.add_argument('--verify', action='store_true', help='额外统计带 rc= 的验证记录')
  st.add_argument('--json', action='store_true', help='输出 JSON')
  st.set_defaults(func=cmd_steps)

  sa = sub.add_parser('session-age', help='会话年龄：这个对话一共承载了多少内容、相当于多少个新对话')
  sa.add_argument('--days', type=float, default=30.0, help='最近几天，默认 30')
  sa.set_defaults(func=cmd_session_age)

  rw = sub.add_parser('rework', help='返工审计：从会话原文捞「用户否定我上一句」的时刻，看我在哪儿被纠正')
  rw.set_defaults(func=cmd_rework)

  rv = sub.add_parser('review', help='复盘：完成声明证据率 + 被否定次数，写回复盘状态（P5 的触发点）')
  rv.set_defaults(func=cmd_review)

  cd = sub.add_parser('cdp', help='通过 CDP 操作已经开着的浏览器（点元素/执行 JS/导航/截图）')
  cd.add_argument('action', choices=['tabs', 'eval', 'click', 'goto', 'shot'])
  cd.add_argument('arg', nargs='?', help='eval 的 JS / click 的选择器 / goto 的 URL / shot 的路径')
  cd.add_argument('--tab', type=int, default=0, help='第几个 page 标签，默认 0')
  cd.add_argument('--port', type=int, default=9222, help='CDP 端口，默认 9222')
  cd.add_argument('--file', help='eval 从文件读 JS')
  cd.add_argument('--json', action='store_true', help='输出 JSON')
  cd.add_argument('--wait-ms', type=int, default=0, help='click 之后等多久（毫秒）')
  cd.add_argument('--wait', type=float, default=15.0, help='goto 等 readyState 的上限秒数')
  cd.add_argument('--await-promise', action='store_true', help='eval 时等 Promise 解析')
  cd.set_defaults(func=cmd_cdp)

  vt = sub.add_parser('vet', help='装插件前扫一遍代码：它要联网/读写什么/执不执行命令')
  vt.add_argument('path', help='插件目录')
  vt.add_argument('--json', action='store_true', help='输出 JSON')
  vt.add_argument('--max', type=int, default=4, help='每条规则最多展示几处（默认 4）')
  vt.add_argument('--all', action='store_true', help='连开发目录（test/iterate/scripts）一起扫')
  vt.set_defaults(func=cmd_vet)

  lp = sub.add_parser('lsp', help='用语言服务器查定义/引用/符号（治「只能靠 grep 摸黑」）')
  lp.add_argument('action', choices=['def', 'refs', 'hover', 'symbols'], help='def=跳定义 refs=找引用 hover=类型 symbols=文件符号')
  lp.add_argument('file', help='源码文件')
  lp.add_argument('line', nargs='?', type=int, help='行号（1 开始）')
  lp.add_argument('col', nargs='?', type=int, help='列号（1 开始）')
  lp.add_argument('--root', help='项目根（默认文件所在目录）')
  lp.add_argument('--server', help='自定义语言服务器启动命令')
  lp.add_argument('--timeout', type=float, default=30.0, help='单次请求超时秒数（默认 30）')
  lp.set_defaults(func=cmd_lsp)

  dp = sub.add_parser('deploy', help='改完自研插件，同步到 profile 并验证（软链的自动跳过）')
  dp.add_argument('names', nargs='*', help='插件名，如 dsh-evolve 或 @local/dsh-evolve')
  dp.add_argument('--all', action='store_true', help='全部自研插件')
  dp.add_argument('--check', action='store_true', help='只比，不同步')
  dp.set_defaults(func=cmd_deploy)

  tk = sub.add_parser('tasks', help='计划任务体检：状态 / 上次结果 / 下次时间 / 电池空闲网络条件')
  tk.add_argument('--json', action='store_true', help='输出 JSON')
  tk.set_defaults(func=cmd_tasks)

  un = sub.add_parser('unattended', help='无人值守跑 headless 任务（只关审批，沙箱仍是 workspace-write）')
  un.add_argument('task', nargs='?', help='任务文本（与 --task-file 二选一）')
  un.add_argument('--task-file', help='从文件读任务文本')
  un.add_argument('--timeout', type=int, default=600, help='硬超时秒数（默认 600）')
  un.add_argument('--name', help='运行名（决定目录名）')
  un.add_argument('--out', default=str(ROOT / '自进化' / 'unattended'), help='输出根目录')
  un.add_argument('--cwd', default=str(ROOT), help='headless 的工作目录（决定沙箱可写范围）')
  un.add_argument('--dry', action='store_true', help='只打印将执行的命令')
  un.add_argument('--list', action='store_true', help='列出历史运行')
  un.add_argument('--show', metavar='RUN_ID', help='看某一次运行')
  un.add_argument('--last', action='store_true', help='看最近一次运行')
  un.set_defaults(func=cmd_unattended)

  return parser


def _review_remind() -> None:
  """打一行复盘状态。只读 state 文件，不扫会话——挂在 commit 后面必须是 0 成本的。"""
  try:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
      sys.path.insert(0, str(here))
    import review
    review.remind()
  except Exception as e:
    print(f'[WARN] 复盘提醒失败（不影响主流程）：{type(e).__name__}: {e}')


def cmd_review(a: argparse.Namespace) -> int:
  """复盘：转调同目录的 review.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('review.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  return _sp.run([sys.executable, str(script)]).returncode


def cmd_rework(a: argparse.Namespace) -> int:
  """返工审计：转调同目录的 rework.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('rework.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  return _sp.run([sys.executable, str(script)]).returncode


def cmd_session_age(a: argparse.Namespace) -> int:
  """会话年龄：转调同目录的 session_age.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('session_age.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), '--days', str(a.days)]
  return _sp.run(cmd).returncode


def cmd_steps(a: argparse.Namespace) -> int:
  """时间轴盘点：转调同目录的 steps.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('steps.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), '--days', str(a.days)]
  if a.verify:
    cmd.append('--verify')
  if a.json:
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_tasks(a: argparse.Namespace) -> int:
  """计划任务体检：转调同目录的 tasks.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('tasks.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script)]
  if getattr(a, 'json', False):
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_unattended(a: argparse.Namespace) -> int:
  """无人值守跑 headless：转调同目录的 unattended.py（治 P8）。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('unattended.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script)]
  if a.list:
    cmd.append('--list')
  elif a.show:
    cmd += ['--show', a.show]
  elif a.last:
    cmd.append('--last')
  else:
    if a.task:
      cmd.append(a.task)
    if a.task_file:
      cmd += ['--task-file', a.task_file]
    if a.timeout != 600:
      cmd += ['--timeout', str(a.timeout)]
    if a.name:
      cmd += ['--name', a.name]
    if a.out != str(ROOT / '自进化' / 'unattended'):
      cmd += ['--out', a.out]
    if a.cwd != str(ROOT):
      cmd += ['--cwd', a.cwd]
    if a.dry:
      cmd.append('--dry')
  return _sp.run(cmd).returncode


def cmd_vet(a: argparse.Namespace) -> int:
  """装插件前扫一遍代码：联网/写文件/执行进程/读记忆凭据（P13 信任边界）。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('vet.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), a.path]
  if a.json:
    cmd.append('--json')
  if a.max != 4:
    cmd += ['--max', str(a.max)]
  if a.all:
    cmd.append('--all')
  return _sp.run(cmd).returncode


def cmd_lsp(a: argparse.Namespace) -> int:
  """用语言服务器查定义/引用/符号（P11：别再靠 grep 摸黑）。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('lsp.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  if a.action in ('def', 'refs', 'hover') and (a.line is None or a.col is None):
    print(f'[ERROR] lsp {a.action} 需要 <line> <col>（都从 1 开始）', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), a.action, a.file]
  if a.line is not None and a.col is not None:
    cmd += [str(a.line), str(a.col)]
  if a.root:
    cmd += ['--root', a.root]
  if a.server:
    cmd += ['--server', a.server]
  if a.timeout != 30.0:
    cmd += ['--timeout', str(a.timeout)]
  return _sp.run(cmd).returncode


def cmd_deploy(a: argparse.Namespace) -> int:
  """同步自研插件到 profile：转调同目录的 deploy.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('deploy.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script)]
  if a.all:
    cmd.append('--all')
  else:
    cmd += list(a.names)
  if a.check:
    cmd.append('--check')
  return _sp.run(cmd).returncode


def cmd_assets(a: argparse.Namespace) -> int:
  """资产盘点：转调同目录的 assets.py，保持单一实现（不复制逻辑）。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('assets.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script)]
  if a.json:
    cmd.append('--json')
  if a.junk:
    cmd.append('--junk')
  if a.top:
    cmd += ['--top', str(a.top)]
  if a.name:
    cmd += ['--name', a.name]
  if a.budget != 4.0:
    cmd += ['--budget', str(a.budget)]
  return _sp.run(cmd).returncode


def cmd_cost(a: argparse.Namespace) -> int:
  """这一步花了多少钱：转调同目录的 cost.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('cost.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), '--hours', str(a.hours)]
  if a.recent:
    cmd += ['--recent', str(a.recent)]
  if a.session is not None:
    cmd.append('--session')
    if a.session:
      cmd.append(a.session)
  if a.json:
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_cdp(a: argparse.Namespace) -> int:
  """浏览器操作：转调同目录的 cdp.py（P3 有眼无手）。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('cdp.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), '--port', str(a.port), a.action]
  if a.action == 'tabs':
    if a.json:
      cmd.append('--json')
  elif a.action == 'eval':
    cmd += ['--tab', str(a.tab)]
    if a.arg:
      cmd.append(a.arg)
    elif a.file:
      cmd += ['--file', a.file]
    if a.await_promise:
      cmd.append('--await-promise')
    if a.json:
      cmd.append('--json')
  elif a.action == 'click':
    cmd += [a.arg or '', '--tab', str(a.tab)]
    if a.wait_ms:
      cmd += ['--wait-ms', str(a.wait_ms)]
  elif a.action == 'goto':
    cmd += [a.arg or '', '--tab', str(a.tab), '--wait', str(a.wait)]
  elif a.action == 'shot':
    cmd += [a.arg or '', '--tab', str(a.tab)]
  else:
    print(f'[ERROR] 未知动作 {a.action}', file=sys.stderr)
    return 2
  return _sp.run(cmd).returncode


def cmd_errors(a: argparse.Namespace) -> int:
  """报错原文按工具聚合：转调同目录的 errors.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('errors.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), '--days', str(a.days), '--top', str(a.top)]
  if a.tool:
    cmd += ['--tool', a.tool]
  if a.json:
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_tier(a: argparse.Namespace) -> int:
  """开工前报数：转调同目录的 tier.py。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('tier.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script), a.task]
  if getattr(a, 'no_assets', False):
    cmd.append('--no-assets')
  if getattr(a, 'json', False):
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_skill(a: argparse.Namespace) -> int:
  """能力熟练度：转调同目录的 skill_stats.py，保持单一实现。"""
  import subprocess as _sp
  script = Path(__file__).resolve().with_name('skill_stats.py')
  if not script.is_file():
    print(f'[ERROR] 找不到 {script}', file=sys.stderr)
    return 2
  cmd = [sys.executable, str(script)]
  if getattr(a, 'json', False):
    cmd.append('--json')
  return _sp.run(cmd).returncode


def cmd_tools(a: argparse.Namespace) -> int:
  """工具使用率：从所有会话的 tool-call 事件里数，对照手写的 KNOWN 清单找零使用。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'tool_stats.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'top', 0):
    args += ['--top', str(a.top)]
  if getattr(a, 'never', False):
    args.append('--never')
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_selfcheck(a: argparse.Namespace) -> int:
  """机制随能力漂移检测：文档里写的子命令/路径/计数，跟磁盘上的是不是一回事。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'selfcheck.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'json', False):
    args.append('--json')
  if getattr(a, 'only', None):
    args += ['--only', str(a.only)]
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_claims(a: argparse.Namespace) -> int:
  """完成声明的证据对账（治 #1 形式完成）：我说的「做完了」，日志/提交/文件能不能接住。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'claims.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'date', None):
    args += ['--date', a.date]
  if getattr(a, 'file', None):
    args += ['--file', a.file]
  if getattr(a, 'all', False):
    args.append('--all')
  if getattr(a, 'chat', False):
    args.append('--chat')
    args += ['--days', str(getattr(a, 'days', 7))]
  if getattr(a, 'json', False):
    args.append('--json')
  if getattr(a, 'selftest', False):
    args.append('--selftest')
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_fact(a: argparse.Namespace) -> int:
  """事实核对（治「把记忆当事实」）：把话里的数字/路径/版本号/行号逐个验证。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'fact.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'file', None):
    args += ['--file', a.file]
  elif getattr(a, 'text', None):
    args += list(a.text)
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_balance(a: argparse.Namespace) -> int:
  """查 DeepSeek 余额 + 今日花费估算。抄自 dsh-balance-tracker，改成 CLI 不需要插件。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'balance.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'json', False):
    args.append('--json')
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_snapshot(a: argparse.Namespace) -> int:
  """文件快照。抄自 dsh-local-devkit 的 CheckpointStore——它能自动快照是因为挂了
  tools/execute 钩子；我拿不到钩子，所以只能手动拍，但存储/恢复逻辑一样。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'snapshot.py'
  cmd = a.snap_cmd
  args = [sys.executable, str(script), cmd]
  if cmd in ('now', 'undo'):
    args.append(a.path)
  elif cmd == 'restore':
    args.append(a.id)
  elif cmd == 'list':
    p = getattr(a, 'path', None)
    if p:
      args += ['--path', p]
    if getattr(a, 'limit', None):
      args += ['--limit', str(a.limit)]
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_encoding(a: argparse.Namespace) -> int:
  """判编码 / 解码 / 修乱码。抄自 dsh-encoding 的零依赖判据。
  治的是「Get-Content 按 GBK 解 UTF-8 → 我误判数据坏了」。"""
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'encoding.py'
  args = [sys.executable, str(script)] + list(getattr(a, 'rest', []) or [])
  if not args[2:]:
    print('用法: lab encoding {detect|read|fix} ...', file=sys.stderr)
    return 2
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_sessions(a: argparse.Namespace) -> int:
  """会话管理：列清单 / 读原文 / 搜索。治「想找 3 天前那次对话，翻了半天」。

  能力本来是有的（session_grep.py 早就写好了），缺的是**看得见的入口**——
  记不住关键词时，只有清单能救我。
  """
  import subprocess as _sp
  script = ROOT / 'tools' / 'lab' / 'session_grep.py'
  args = [sys.executable, str(script)]
  if getattr(a, 'stats', False):
    args.append('--stats')
  elif getattr(a, 'show', None):
    args += ['--show', a.show]
    if getattr(a, 'head', False):
      args.append('--head')
    if getattr(a, 'context', None) is not None:
      args += ['--context', str(a.context), '--before', str(getattr(a, 'before', 1))]
    args += ['--limit', str(a.limit)]
  elif getattr(a, 'list', False) or not (a.keywords or []):
    args.append('--list')
    if a.days:
      args += ['--days', str(a.days)]
    if a.limit:
      args += ['--limit', str(a.limit)]
  else:
    args += list(a.keywords)
    if getattr(a, 'all', False):
      args.append('--all')
    args += ['--limit', str(a.limit)]
    if a.days:
      args += ['--days', str(a.days)]
  r = _sp.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
  if r.stdout:
    print(r.stdout, end='')
  if r.stderr:
    print(r.stderr, file=sys.stderr, end='')
  return r.returncode


def cmd_lint(a: argparse.Namespace) -> int:
  """文档排版检查：用户 2026-11-03 给的排版五律里可机器判的那几条。

  只提示不阻断：lint 想解决的是「人读不下去」，如果拦下来，
  就会变成「为了过检查而改文档」，那就反了——同 lab commit 里的自检。
  """
  targets = [Path(p) for p in (a.path or [])] or [
    ROOT / 'dsh-workflow-skill' / 'skills' / 'workflow' / 'SKILL.md',
    DECISION_LOG,
  ]
  total = 0
  missing = 0
  for p in targets:
    if not p.is_file():
      print(f'[FAIL:参数] 找不到：{p}')
      missing += 1
      continue
    text = p.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    warns: list[tuple[int, str]] = []

    in_code = False
    for i, ln in enumerate(lines, 1):
      if ln.strip().startswith('```'):
        in_code = not in_code
        continue
      if in_code:
        continue
      m = re.match(r'^(#{1,6})\s+(.*)$', ln)
      if m:
        title = m.group(2).strip()
        # 带编号 / 日期 / 括号的标题是结构性标题，长短是必要的，不算问题
        structural = bool(re.match(r'^(?:§?[\d.]+|[①-⑳])', title)) or bool(re.search(r'\d{4}-\d{2}', title)) or ('（' in title or '(' in title)
        if not structural and len(title) > a.max_title:
          warns.append((i, f'小标题 {len(title)} 字（>{a.max_title}）：{title}'))
        continue
      body = ln.strip()
      if (not body or body.startswith(('|', '-', '*', '>'))
          or re.match(r'^\d+[.)]\s', body)):
        continue
      # 只数分号：顿号「、」多是并列列举，不是多事实
      n = body.count('；')
      if n >= a.max_facts:
        warns.append((i, f'一行 {n} 个「；」，事实挤在一起'))
      if len(ln) > a.max_line:
        warns.append((i, f'{len(ln)} 字（>{a.max_line}）'))

    run = 0
    run_start = 0
    for i, ln in enumerate(lines, 1):
      s = ln.strip()
      if (not s or s.startswith(('#', '-', '*', '|', '>', '```'))
          or re.match(r'^\d+[.)]\s', s)):
        run = 0
        continue
      if run == 0:
        run_start = i
      run += 1
      if run == a.max_para:
        warns.append((run_start, f'从 {run_start} 行起连续 {a.max_para} 行无留白（能列表就别写成段落）'))
        run = 0

    if not warns:
      print(f'[OK]   {p.name}：{len(lines)} 行，没查出排版问题')
    else:
      warns.sort()
      print(f'[WARN] {p.name}：{len(lines)} 行，{len(warns)} 处读起来费劲')
      for i, w in warns[:30]:
        print(f'   第 {i} 行  {w}')
      if len(warns) > 30:
        print(f'   …还有 {len(warns) - 30} 处')
      total += len(warns)

  if missing:
    return 2
  if total and a.strict:
    return 1
  return 0


def main(argv=None) -> int:
  args = build_parser().parse_args(argv)
  return args.func(args)


if __name__ == '__main__':
  sys.exit(main())
