"""ghctl —— 把「改文件 → 提交 → 推送 → 验远端」收成一条命令。

用法：
  ghctl whoami
  ghctl use Uneadlight/fatfish-lab        # 设默认仓库，之后不用每次 --repo
  ghctl sync -m "提交说明" [--all | --files a.py b.md] [--repo PATH] [--no-push]
  ghctl readme [--line N | --head N | --grep 关键词]
  ghctl meta [--desc "..."] [--topics a,b,c]
  ghctl release get    --tag v1.0.0
  ghctl release create --tag v1.0.0 --title "..." --notes-file path.md
  ghctl issue 750                         # 看某个 issue 的正文
  ghctl issue list --state open --limit 30

--repo 可以给 owner/name（远端项目），也可以给本地目录（自动读 origin 推 slug）。

设计约定 —— 把踩过的坑写成默认行为：
  * git 一律用绝对路径（本机 PATH 里没有 git）
  * commit message 走 UTF-8 无 BOM 临时文件 + `-F`，避免 Windows GBK 转录乱码
  * push 自动带 http.extraheader 认证 + HTTP/1.1 + 最多 5 次退避重试
  * 取 README 用 Accept: application/vnd.github.raw（否则拿到的是 JSON 元数据）
  * token 只从文件读、永不打印；所有网络调用带超时
  * 任何失败都按「能力缺失 / 权限被拒 / 执行失败」三选一自报，不等用户追问
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
TOKEN_PATH = HOME / '.dsh' / 'github-token.txt'
API = 'https://api.github.com'
TIMEOUT = 45

GIT_CANDIDATES = (
  r'D:\work\tools\git\cmd\git.exe',
  r'C:\Program Files\Git\cmd\git.exe',
)


class Fail(Exception):
  """带定性的失败。kind 三选一：能力缺失 / 权限被拒 / 执行失败。"""

  def __init__(self, kind: str, msg: str, hint: str = ''):
    super().__init__(msg)
    self.kind = kind
    self.msg = msg
    self.hint = hint


# ---------------------------------------------------------------- 基础设施


def find_git() -> str:
  for c in GIT_CANDIDATES:
    if Path(c).is_file():
      return c
  found = shutil.which('git')
  if found:
    return found
  raise Fail(
    '能力缺失',
    '本机和 PATH 里都找不到 git',
    '这不是权限问题。装 Git，或把它的路径加进本文件的 GIT_CANDIDATES。',
  )


def token() -> str:
  if not TOKEN_PATH.is_file():
    raise Fail('能力缺失', f'没有 token 文件：{TOKEN_PATH}', '先跑 github_device_login.py 授权')
  t = TOKEN_PATH.read_text(encoding='utf-8').strip()
  if not t:
    raise Fail('能力缺失', f'{TOKEN_PATH} 是空的', '重新跑授权流程')
  return t


def scrub(text: str) -> str:
  """输出前的最后一道保险：绝不把 token / 认证头打到屏幕上。

  只替换真实的 token 与 base64 形式，不做模糊的「长字符串」匹配——
  否则会把 40 位 commit sha 一起吃掉。
  """
  try:
    t = TOKEN_PATH.read_text(encoding='utf-8').strip()
  except OSError:
    t = ''
  if t:
    text = text.replace(t, '<redacted>')
    try:
      text = text.replace(base64.b64encode(f'x-access-token:{t}'.encode()).decode(), '<redacted>')
    except Exception:
      pass
  return re.sub(r'(Authorization:\s*basic)\s+\S+', r'\1 <redacted>', text, flags=re.I)



def run_git(git: str, args: list[str], cwd: Path, check: bool = True) -> tuple[int, str]:
  p = subprocess.run([git, *args], cwd=str(cwd), capture_output=True)
  out = (p.stdout + p.stderr).decode('utf-8', 'replace')
  out = scrub(out)
  if check and p.returncode != 0:
    raise Fail('执行失败', f'git {" ".join(args[:2])} 返回 {p.returncode}\n{out.strip()[:800]}')
  return p.returncode, out


def api(method: str, path: str, payload: dict | None = None, raw: bool = False):
  data = json.dumps(payload).encode() if payload is not None else None
  headers = {
    'Authorization': f'Bearer {token()}',
    'Accept': 'application/vnd.github.raw' if raw else 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'dsh-ghctl',
  }
  if data:
    headers['Content-Type'] = 'application/json'
  req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
  try:
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
      body = resp.read()
      if raw:
        return resp.status, body.decode('utf-8', 'replace')
      return resp.status, json.loads(body.decode('utf-8') or '{}')
  except urllib.error.HTTPError as exc:
    detail = exc.read().decode('utf-8', 'replace')[:600]
    if exc.code in (401, 403):
      raise Fail(
        '权限被拒',
        f'HTTP {exc.code}：{detail}',
        '跑 `ghctl whoami` 看账号、`ghctl scopes` 看 scope；私有仓库需要 scope=repo。',
      )
    if exc.code == 404:
      raise Fail('执行失败', f'HTTP 404：{detail}', '仓库不存在，或者这个 token 看不到它。')
    raise Fail('执行失败', f'HTTP {exc.code}：{detail}')
  except urllib.error.URLError as exc:
    raise Fail('执行失败', f'网络错误：{exc.reason}', '线路抖动，重试一次通常就好。')


def find_repo_root(start: Path) -> Path:
  cur = start.resolve()
  for p in [cur, *cur.parents]:
    if (p / '.git').exists():
      return p
  raise Fail('能力缺失', f'{start} 及上层目录都没有 .git', '用 --repo 指定仓库目录，或先在仓库里执行')


def slug_from_git(git: str, cwd: Path) -> str:
  _, out = run_git(git, ['remote', 'get-url', 'origin'], cwd)
  m = re.search(r'github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$', out.strip())
  if not m:
    raise Fail('执行失败', f'origin 不是 GitHub 地址：{out.strip()[:200]}', '检查 remote 配置')
  return f'{m.group(1)}/{m.group(2)}'


DEFAULT_SLUG_FILE = HOME / '.dsh' / 'ghctl-default.txt'


def resolve_slug(value: str | None) -> tuple[str, Path | None]:
  """返回 (owner/name, 本地仓库路径或 None)。value 可以是 slug 也可以是目录。

  优先级：--repo 参数 → 当前目录向上找 .git → ~/.dsh/ghctl-default.txt（`ghctl use` 写入）
  """
  if value:
    if re.match(r'^[A-Za-z]:[\\/]', value) or value.startswith('\\\\') or Path(value).is_dir():
      git = find_git()
      root = find_repo_root(Path(value))
      return slug_from_git(git, root), root
    if '/' not in value:
      raise Fail('执行失败', f'--repo 需要 owner/name 或目录路径，收到 {value!r}')
    return value, None

  try:
    git = find_git()
    root = find_repo_root(Path.cwd())
    return slug_from_git(git, root), root
  except Fail:
    pass

  if DEFAULT_SLUG_FILE.is_file():
    saved = DEFAULT_SLUG_FILE.read_text(encoding='utf-8').strip()
    if '/' in saved:
      return saved, None

  raise Fail(
    '执行失败',
    '不知道要操作哪个仓库：当前目录不在 git 仓库里，也没有默认仓库',
    '给 --repo owner/name，或先跑一次 `ghctl use owner/name` 把它设为默认。',
  )


# ---------------------------------------------------------------- 子命令


def cmd_whoami(_a) -> int:
  code, data = api('GET', '/user')
  print(f'[OK] status={code} login={data.get("login")} type={data.get("type")}')
  req = urllib.request.Request(
    API + '/user',
    headers={'Authorization': f'Bearer {token()}', 'User-Agent': 'dsh-ghctl'},
  )
  with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
    print(f'     scopes={resp.headers.get("x-oauth-scopes") or "(empty)"}')
  return 0


def cmd_sync(a) -> int:
  git = find_git()
  cwd = Path(a.repo).resolve() if a.repo else find_repo_root(Path.cwd())
  if not (cwd / '.git').exists():
    raise Fail('能力缺失', f'{cwd} 不是 git 仓库', '用 --repo 指定仓库')
  slug = slug_from_git(git, cwd)

  # 1) 暂存
  if a.all:
    run_git(git, ['add', '-A'], cwd)
  elif a.files:
    run_git(git, ['add', *a.files], cwd)
  _, staged = run_git(git, ['diff', '--cached', '--name-only'], cwd)
  staged_files = [x for x in staged.splitlines() if x.strip()]
  if not staged_files:
    print('[OK] 没有待提交的改动（工作区干净），跳过提交')
    return 0
  print(f'     暂存 {len(staged_files)} 个文件：')
  for f in staged_files[:12]:
    print(f'       - {f}')
  if len(staged_files) > 12:
    print(f'       … 还有 {len(staged_files) - 12} 个')

  # 2) 提交（UTF-8 无 BOM + -F，避开 GBK 转录）
  msg_file = cwd / '.git' / 'GHCTL_LAST_MESSAGE.txt'
  msg_file.write_text(a.message.rstrip() + '\n', encoding='utf-8', newline='\n')
  run_git(git, ['-c', 'i18n.commitEncoding=utf-8', 'commit', '-F', str(msg_file)], cwd)
  _, head = run_git(git, ['log', '-1', '--format=%h'], cwd)
  short = head.strip()

  # 3) 校验落库字节（终端乱码 ≠ 落库乱码，判据只看原始字节）
  p = subprocess.run([git, 'cat-file', 'commit', 'HEAD'], cwd=str(cwd), capture_output=True)
  raw = p.stdout
  try:
    text = raw.decode('utf-8')
    subject = text.split('\n\n', 1)[1].splitlines()[0]
    print(f'[OK] commit {short} | message 字节校验通过 | {subject}')
  except (UnicodeDecodeError, IndexError) as exc:
    raise Fail('执行失败', f'commit message 字节不是合法 UTF-8：{exc}', '落库可能已乱，考虑 --amend 修正')

  if a.no_push:
    print('     已按 --no-push 停在本地')
    return 0

  # 4) 推送（认证头 + HTTP/1.1 + 退避重试）
  b64 = base64.b64encode(f'x-access-token:{token()}'.encode()).decode()
  last = ''
  for i in range(1, a.tries + 1):
    rc, out = run_git(
      git,
      ['-c', f'http.extraheader=AUTHORIZATION: basic {b64}',
       '-c', 'http.version=HTTP/1.1', 'push', 'origin', 'HEAD:main'],
      cwd,
      check=False,
    )
    if rc == 0:
      tail = [ln for ln in out.splitlines() if '->' in ln]
      print(f'[OK] push 成功（第 {i} 次尝试）{slug} | ' + (tail[-1].strip() if tail else ''))
      return 0
    last = out.strip()[:300]
    if i < a.tries:
      print(f'     push 第 {i} 次失败，5 秒后重试：{last.splitlines()[-1] if last else ""}')
      time.sleep(5)
  raise Fail('执行失败', f'push 重试 {a.tries} 次仍失败：{last}', '线路问题，稍后手动重跑 `ghctl sync` 不可行（已提交），改用 push 单独重试')


def cmd_use(a) -> int:
  """把某个仓库记成默认目标，之后 readme/meta/release 不用每次带 --repo。"""
  slug, _ = resolve_slug(a.slug)
  if '/' not in slug:
    raise Fail('执行失败', f'需要 owner/name，收到 {slug!r}')
  DEFAULT_SLUG_FILE.parent.mkdir(parents=True, exist_ok=True)
  DEFAULT_SLUG_FILE.write_text(slug + '\n', encoding='utf-8', newline='\n')
  print(f'[OK] 默认仓库已设为 {slug}（记在 {DEFAULT_SLUG_FILE}）')
  return 0


def cmd_readme(a) -> int:
  slug, _ = resolve_slug(a.repo)
  code, text = api('GET', f'/repos/{slug}/readme', raw=True)
  lines = text.splitlines()
  print(f'[OK] {slug} README | {len(lines)} 行 / {len(text)} 字符 / status={code}')
  if a.grep:
    hits = [(i, ln) for i, ln in enumerate(lines, 1) if a.grep in ln]
    print(f'     含「{a.grep}」的行 {len(hits)} 处')
    for i, ln in hits[:20]:
      print(f'       L{i}: {ln[:160]}')
    return 0 if hits else 2
  if a.line:
    if not 1 <= a.line <= len(lines):
      raise Fail('执行失败', f'要第 {a.line} 行，但 README 只有 {len(lines)} 行')
    print(f'     L{a.line}: {lines[a.line - 1]}')
    return 0
  head = a.head or 0
  for i, ln in enumerate(lines[:head] if head else lines, 1):
    print(f'     L{i}: {ln}')
  return 0


def cmd_meta(a) -> int:
  slug, _ = resolve_slug(a.repo)
  if a.desc is None and not a.topics:
    code, data = api('GET', f'/repos/{slug}')
    print(f'[OK] {slug} | private={data.get("private")} | branch={data.get("default_branch")}')
    print(f'     desc  ({len(data.get("description") or "")} 字符): {data.get("description")}')
    print(f'     topics({len(data.get("topics") or [])}): {", ".join(data.get("topics") or [])}')
    return 0
  if a.desc is not None:
    if len(a.desc) > 350:
      raise Fail('执行失败', f'description {len(a.desc)} 字符，GitHub 上限 350')
    code, _ = api('PATCH', f'/repos/{slug}', {'description': a.desc})
    print(f'[OK] description 已设（{len(a.desc)} 字符）status={code}')
  if a.topics:
    names = [t.strip() for t in a.topics.split(',') if t.strip()]
    code, data = api('PUT', f'/repos/{slug}/topics', {'names': names})
    print(f'[OK] topics 已设 {len(data.get("names") or names)} 个 status={code}: {", ".join(data.get("names") or names)}')
  return 0


def cmd_release(a) -> int:
  slug, _ = resolve_slug(a.repo)
  if a.action == 'get':
    code, data = api('GET', f'/repos/{slug}/releases/tags/{a.tag}')
    body = data.get('body') or ''
    print(f'[OK] {slug} {a.tag} | draft={data.get("draft")} | {len(body)} 字符 | status={code}')
    print(f'     name: {data.get("name")}')
    print(f'     url : {data.get("html_url")}')
    if a.show_body:
      print('     ---- body ----')
      for ln in body.splitlines():
        print(f'     {ln}')
    return 0
  if not a.title or not a.notes_file:
    raise Fail('执行失败', 'release create 需要 --title 和 --notes-file')
  notes = Path(a.notes_file).read_text(encoding='utf-8').strip()
  code, data = api(
    'POST',
    f'/repos/{slug}/releases',
    {'tag_name': a.tag, 'name': a.title, 'body': notes, 'draft': False},
  )
  print(f'[OK] release 已创建 status={code} | {data.get("html_url")} | body {len(data.get("body") or "")} 字符')
  if code >= 400:
    raise Fail('执行失败', f'创建失败：{data}')
  return 0


def cmd_issue(a) -> int:
  """读 issue：不带编号列列表（自动滤掉 PR），带编号看正文。"""
  slug, _ = resolve_slug(a.repo)
  if a.number in (None, 'list'):
    code, data = api('GET', f'/repos/{slug}/issues?state={a.state}&per_page={a.limit}')
    if not isinstance(data, list):
      raise Fail('执行失败', f'期望列表，收到 {type(data).__name__}：{str(data)[:200]}')
    rows = [d for d in data if 'pull_request' not in d]
    print(f'[OK] {slug} {a.state} issues | {len(rows)} 条（已滤掉 PR）| status={code}')
    for d in rows:
      labels = ','.join(lb['name'] for lb in d.get('labels') or [])
      tail = f'  [{labels}]' if labels else ''
      print(f'  #{d["number"]:<5} {d["title"][:86]}' + tail)
    return 0
  code, data = api('GET', f'/repos/{slug}/issues/{a.number}')
  if not isinstance(data, dict):
    raise Fail('执行失败', f'期望对象，收到 {type(data).__name__}')
  labels = ','.join(lb['name'] for lb in data.get('labels') or [])
  print(f'[OK] {slug} #{data["number"]} | state={data["state"]} '
        f'| comments={data.get("comments")} | labels={labels or "-"}')
  print(f'     {data["title"]}')
  print(f'     {data.get("html_url")}')
  body = data.get('body') or ''
  print(f'     ---- body ({len(body)} 字符) ----')
  for ln in body.splitlines():
    print(f'     {ln}')
  return 0


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(prog='ghctl', description='GitHub 日常链路一条命令')
  sub = p.add_subparsers(dest='cmd', required=True)

  sub.add_parser('whoami', help='看当前 token 是哪个账号、什么 scope')

  s = sub.add_parser('use', help='把某个仓库设为默认目标（之后不用每次 --repo）')
  s.add_argument('slug', help='owner/name 或本地仓库目录')

  s = sub.add_parser('sync', help='暂存 + 提交（UTF-8 安全）+ 推送（自动重试）')
  s.add_argument('-m', '--message', required=True)
  s.add_argument('--repo', help='本地仓库目录')
  s.add_argument('--all', action='store_true', help='git add -A')
  s.add_argument('--files', nargs='*', help='只暂存这些文件')
  s.add_argument('--no-push', action='store_true')
  s.add_argument('--tries', type=int, default=5)

  s = sub.add_parser('readme', help='取远端 README 正文（raw，不是 JSON 元数据）')
  s.add_argument('--repo', help='owner/name 或本地目录')
  s.add_argument('--line', type=int)
  s.add_argument('--head', type=int)
  s.add_argument('--grep')

  s = sub.add_parser('meta', help='看或设 About / Topics')
  s.add_argument('--repo', help='owner/name 或本地目录')
  s.add_argument('--desc')
  s.add_argument('--topics', help='逗号分隔')

  s = sub.add_parser('issue', help='看 issue 列表或正文')
  s.add_argument('number', nargs='?', help='issue 编号；给 list 或省略则列列表')
  s.add_argument('--repo', help='owner/name 或本地目录')
  s.add_argument('--state', default='open', choices=['open', 'closed', 'all'])
  s.add_argument('--limit', type=int, default=30)

  s = sub.add_parser('release', help='看或建 Release')
  s.add_argument('action', choices=['get', 'create'])
  s.add_argument('--tag', required=True)
  s.add_argument('--title')
  s.add_argument('--notes-file')
  s.add_argument('--repo', help='owner/name 或本地目录')
  s.add_argument('--show-body', action='store_true')
  return p


def main(argv: list[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  handlers = {
    'whoami': cmd_whoami,
    'use': cmd_use,
    'sync': cmd_sync,
    'readme': cmd_readme,
    'meta': cmd_meta,
    'release': cmd_release,
    'issue': cmd_issue,
  }
  try:
    return handlers[args.cmd](args)
  except Fail as exc:
    print(f'[FAIL:{exc.kind}] {exc.msg}', file=sys.stderr)
    if exc.hint:
      print(f'         -> {exc.hint}', file=sys.stderr)
    return 1
  except KeyboardInterrupt:
    print('[FAIL:执行失败] 被中断', file=sys.stderr)
    return 130


if __name__ == '__main__':
  raise SystemExit(main())
