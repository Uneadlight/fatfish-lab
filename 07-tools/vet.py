"""装插件前扫一遍代码：它要联网吗？读我哪些数据？要不要执行外部命令？

用法（经 `lab vet` 调用，也可直接跑）：
    py tools/lab/vet.py <插件目录>
    py tools/lab/vet.py <插件目录> --json
    py tools/lab/vet.py <插件目录> --max 5

设计原则：**不判「安全/不安全」**——我没有这个能力，判了也是假的。
它只把「这个插件申请了什么能力」摆到眼前，让装之前有一个三秒钟的判断机会。
所以分两级：HIGH = 值得停下来看一眼；MED = 大多数正常插件也有，数量本身说明体量。

边界：静态扫描，正则匹配。拼接出来的调用（`ev` + `al`）、压缩过的代码、
动态 require 都可能漏。它挡的是「随手装一个来路不明的东西」这个习惯，不是定向攻击。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# (id, level, title, why, regex)
RULES: list[tuple[str, str, str, str, str]] = [
    ('proc', 'HIGH', '执行外部进程',
     '能跑任意命令，等于把本机交给它',
     r'\b(child_process|execSync|spawnSync|execFileSync)\b|(?<![\w.])exec\s*\('),
    ('eval', 'HIGH', '动态执行代码',
     '能跑任意代码，静态扫描看不穿它要干什么',
     r'\b(eval|new\s+Function)\s*\('),
    ('secret', 'HIGH', '读会话/记忆/凭据',
     '摸的是我最私密的数据：对话原文、长期记忆、token',
     r'\.dsh[\\/](memory|sessions)|hosts\.yml|github-token|vision-key|credentials|memories\.json'),
    ('postinstall', 'HIGH', '安装时执行脚本',
     '装上那一刻就跑，还没等我用',
     r'"(pre|post)install"\s*:'),
    ('b64', 'HIGH', '超长 base64 块',
     '正常代码不需要藏 400+ 字符的编码数据，混淆常见',
     r'[A-Za-z0-9+/]{400,}={0,2}'),
    ('net', 'MED', '联网',
     '会把数据发出去；域名和时机决定风险',
     r'\b(fetch|axios|https?\.request|https?\.get|new\s+WebSocket|XMLHttpRequest)\b'),
    ('fs-write', 'MED', '写/删文件',
     '动的是我的磁盘，路径决定动到哪',
     r'\b(writeFileSync|appendFileSync|unlinkSync|rmSync|rmdirSync|mkdirSync|copyFileSync)\b'
     r'|\bfs\.(writeFile|appendFile|rename|unlink|rm|rmdir|mkdir|copyFile|truncate)\b'),
    ('env', 'MED', '读环境变量',
     '可能读到 token；也可能只是读 PATH',
     r'\bprocess\.env\b'),
]

SCAN_SUFFIXES = {'.js', '.mjs', '.cjs', '.ts', '.jsx', '.tsx', '.json'}
SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.cache', 'coverage'}
# 开发目录不随包发布，扫它们只会拿测试脚本吓自己；--all 才扫
DEV_DIRS = {'iterate', 'test', 'tests', 'spec', 'specs', 'scripts', 'dev',
            'examples', 'docs', '.github', '__tests__'}
MAX_BYTES = 2 * 1024 * 1024      # 单文件超过 2MB 当构建产物，跳过
LONG_LINE = 2000                  # 单行超过 2000 字符当压缩代码，只跑 b64 规则

COMPILED = [(rid, lvl, title, why, re.compile(pat)) for rid, lvl, title, why, pat in RULES]
B64_ONLY = next(c for c in COMPILED if c[0] == 'b64')


def iter_files(root: Path, include_dev: bool = False):
  for p in sorted(root.rglob('*')):
    if not p.is_file() or p.suffix.lower() not in SCAN_SUFFIXES:
      continue
    skip = SKIP_DIRS | (set() if include_dev else DEV_DIRS)
    if any(part in skip for part in p.parts):
      continue
    try:
      if p.stat().st_size > MAX_BYTES:
        continue
    except OSError:
      continue
    yield p


def scan_file(path: Path, root: Path) -> list[dict]:
  hits = []
  try:
    text = path.read_text(encoding='utf-8', errors='replace')
  except OSError:
    return hits
  rel = path.relative_to(root).as_posix()
  for no, line in enumerate(text.splitlines(), 1):
    rules = [B64_ONLY] if len(line) > LONG_LINE else COMPILED
    for rid, lvl, title, why, rx in rules:
      m = rx.search(line)
      if not m:
        continue
      snippet = line.strip()
      if len(snippet) > 120:
        start = max(0, m.start() - 40)
        snippet = ('…' if start else '') + line[start:start + 120].strip() + '…'
      hits.append({'rule': rid, 'level': lvl, 'title': title, 'why': why,
                   'file': rel, 'line': no, 'snippet': snippet})
  return hits


def vet(root: Path, max_per_rule: int = 4, include_dev: bool = False) -> dict:
  files = list(iter_files(root, include_dev))
  hits: list[dict] = []
  for f in files:
    hits.extend(scan_file(f, root))

  pkg = root / 'package.json'
  meta = {}
  if pkg.exists():
    try:
      data = json.loads(pkg.read_text(encoding='utf-8'))
      meta = {
        'name': data.get('name', ''),
        'version': data.get('version', ''),
        'deps': len(data.get('dependencies') or {}),
        'peer': len(data.get('peerDependencies') or {}),
        'scripts': sorted((data.get('scripts') or {}).keys()),
        'dsh_client': bool(data.get('dsh', {}).get('client')) if isinstance(data.get('dsh'), dict) else False,
      }
    except Exception as exc:  # noqa: BLE001 - 坏 package.json 不影响扫描
      meta = {'error': f'package.json 解析失败: {exc}'}

  by_rule: dict[str, dict] = {}
  for h in hits:
    r = by_rule.setdefault(h['rule'], {'title': h['title'], 'level': h['level'],
                                       'why': h['why'], 'count': 0, 'shown': []})
    r['count'] += 1
    if len(r['shown']) < max_per_rule:
      r['shown'].append({'file': h['file'], 'line': h['line'], 'snippet': h['snippet']})

  return {'root': str(root), 'files': len(files), 'meta': meta,
          'rules': by_rule, 'total_hits': len(hits),
          'high_rules': sorted(k for k, v in by_rule.items() if v['level'] == 'HIGH')}


def report(res: dict) -> None:
  print(f"[VET] {res['root']}")
  print(f"  扫描 {res['files']} 个文件，命中 {res['total_hits']} 处")
  m = res['meta']
  if m:
    if 'error' in m:
      print(f"  package.json: {m['error']}")
    else:
      print(f"  package: {m.get('name','')}@{m.get('version','')}  "
            f"deps={m.get('deps',0)} peer={m.get('peer',0)} client={m.get('dsh_client')}")
      if m.get('scripts'):
        print(f"  scripts: {', '.join(m['scripts'])}")
  if not res['rules']:
    print("\n[结论] 没扫到任何能力申请——要么很干净，要么它没写代码（看一眼文件数）")
    return
  for lvl in ('HIGH', 'MED'):
    rows = [(k, v) for k, v in res['rules'].items() if v['level'] == lvl]
    if not rows:
      continue
    rows.sort(key=lambda kv: -kv[1]['count'])
    print(f"\n{'='*8} {lvl} {'='*8}")
    for rid, v in rows:
      print(f"[{rid}] {v['title']} ×{v['count']}  ← {v['why']}")
      for s in v['shown']:
        print(f"    {s['file']}:{s['line']}  {s['snippet'][:110]}")
      if v['count'] > len(v['shown']):
        print(f"    …还有 {v['count'] - len(v['shown'])} 处（--max N 看更多）")
  if res['high_rules']:
    print(f"\n[结论] HIGH 规则命中 {len(res['high_rules'])} 类：{', '.join(res['high_rules'])}")
    print("       装之前至少看一眼每个 HIGH 命中在干什么——不是不能装，是要知道它拿这个干什么")
  else:
    print("\n[结论] 没有 HIGH 命中；MED 是大多数插件的常态（联网/写文件/读环境变量）")


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('path', help='插件目录')
  ap.add_argument('--json', action='store_true', help='输出 JSON')
  ap.add_argument('--max', type=int, default=4, help='每条规则最多展示几处（默认 4）')
  ap.add_argument('--all', action='store_true', help='连开发目录（test/iterate/scripts 等）一起扫')
  a = ap.parse_args()
  root = Path(a.path)
  if not root.is_dir():
    print(f'[FAIL] 不是目录: {root}')
    return 2
  res = vet(root, a.max, a.all)
  if a.json:
    print(json.dumps(res, ensure_ascii=False, indent=2))
  else:
    report(res)
  return 0


if __name__ == '__main__':
  sys.exit(main())
