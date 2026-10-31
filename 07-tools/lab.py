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
import sys
from pathlib import Path

ROOT = Path(r'D:\work')
DECISION_LOG = ROOT / '自进化' / '决策日志.md'
ASAR = Path(r'D:\DeepSeek Harness\resources\app.asar')
DEFAULT_REPO = ROOT / 'repos' / 'dafeiyu-lab'  # 本地目录名仍是 dafeiyu-lab，远端仓库名是 fatfish-lab
DEFAULT_PLAN = ROOT / 'tools' / 'lab' / 'release-plan.txt'

REQUIRED_SECTIONS = ('**做了什么**', '**为什么**', '**取舍**', '**教训**')


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
    for idx, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
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
    return 1
  print('  [OK] 可以发布')
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

  ar = sub.add_parser('asar', help='读 app.asar（不解包）')
  ar.add_argument('action', choices=['list', 'desc', 'read'])
  ar.add_argument('keyword', nargs='?', help='list/desc 的关键字过滤；read 的包内路径')
  ar.add_argument('--max', type=int, default=1200, help='read 最多输出多少字符，0 表示全部')
  ar.set_defaults(func=cmd_asar)

  return parser


def main(argv=None) -> int:
  args = build_parser().parse_args(argv)
  return args.func(args)


if __name__ == '__main__':
  sys.exit(main())
