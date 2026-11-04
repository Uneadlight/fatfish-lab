#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""unattended.py —— 无人值守跑一个 headless 任务。

治的是本质问题 P8「我不在场就断线」：
  `dsh --profile headless` 本身能跑，但**每次工具调用都会弹审批框**，
  没有应答方就永远卡在那里等（2026-11-01 实测，用户连点十多回）。

正解不是把整个沙箱开到 danger-full-access，而是只覆盖「审批」这一条：
  approval 的 policy 从 DSH_PERMISSION_MODE 推导，默认 'ask'；
  用 --patch 把它改成 'never'，sandbox-policy 不动 —— 于是
  **不需要人点，但写入仍被限制在 workspace-write 范围内**。

边界（诚实声明）：
  - 本工具只保证「进程跑完 + 输出落盘」，不保证「任务真的做成了」。
    headless 的退出码 0 只说明模型认为它答完了，任务层成败要看 stdout 和文件现场。
  - 超时会 taskkill /T 杀整棵进程树，并留下 meta.json 标记 timed_out。
  - 不自动重试：重试可能造成重复副作用（写一半的文件、重复提交）。

用法:
  lab unattended "把 X 做完" --timeout 600
  lab unattended --task-file task.md --name review-deps --timeout 1800
  lab unattended --list
  lab unattended --last
  lab unattended --show 20261104-220115-xxxx
  lab unattended --dry "先看看会跑什么"

退出码: 0 跑完且 rc=0 / 1 跑完但 rc!=0 / 2 超时被杀 / 3 用途错误 / 4 环境缺失 / 5 已有运行占用锁
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r'D:\work')
DSH = Path(r'D:\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd')
OUT_ROOT = ROOT / '自进化' / 'unattended'
JOURNAL = ROOT / 'tools' / 'lab' / 'journal.jsonl'

# 只覆盖审批策略，不碰 sandbox-policy（后者仍读 DSH_PERMISSION_MODE，默认 workspace-write）。
# 为什么还要补 permission-presets：它的默认表只有三种组合
#   read-only+ask / workspace-write+ask / danger-full-access+never。
# 直接拼 workspace-write+never 会让它 derive 出 "custom" 并在构造时抛错
# （stderr: permission (@deepseek-ai/dsh-permission-presets): Error: composed sandbox
#  and approval defaults match no preset; configure defaultPreset explicitly），
# 整个插件不激活。所以这里把 unattended 组合显式加进预设表并设为默认。
PATCH_YAML = """- id: permission
  name: '@deepseek-ai/dsh-permission-presets'
  config:
    presets:
      read-only:
        sandbox: read-only
        approval: ask
      workspace-write:
        sandbox: workspace-write
        approval: ask
      danger-full-access:
        sandbox: danger-full-access
        approval: never
      unattended:
        sandbox: workspace-write
        approval: never
    defaultPreset: unattended
- id: approval
  name: '@deepseek-ai/dsh-user-approval'
  config:
    policy: never
"""

DEFAULT_TIMEOUT = 600


# ---------------------------------------------------------------- 基础设施

def journal(action: str, **fields) -> None:
  """先落盘再执行。写不了日志不阻断主流程，但要喊出来。"""
  row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'action': action, **fields}
  try:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open('a', encoding='utf-8', newline='\n') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError as exc:
    print(f'[WARN] journal 写入失败（不影响本次执行）: {exc}', file=sys.stderr)


def slugify(text: str, n: int = 24) -> str:
  """把任务文本压成一个能当目录名的短标签：只留中文/字母/数字，其余折成 -。"""
  text = (text or '').strip().replace('\n', ' ')
  text = re.sub(r'[^\w\u4e00-\u9fff]+', '-', text)
  text = text.strip('-')
  return (text[:n] or 'task').rstrip('-')


def new_run_id(name: str | None, task: str) -> str:
  stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
  return f'{stamp}-{slugify(name or task)}'


def write_json(path: Path, obj: dict) -> None:
  path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n',
                  encoding='utf-8', newline='\n')


def kill_tree(pid: int) -> None:
  """杀整棵进程树。p.kill() 只杀直接子进程，node 会被留下来继续烧 API。"""
  try:
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                   capture_output=True, text=True, errors='replace', timeout=30)
  except (OSError, subprocess.SubprocessError) as exc:
    print(f'[WARN] taskkill 失败，进程可能残留 pid={pid}: {exc}', file=sys.stderr)


# ---------------------------------------------------------------- 并发锁
#
# 两个 unattended 同时跑会抢同一个 profile（headless）和同一个记忆库
# （记忆库并发写铁律 mem_mvteo1tj_6eoinh 要求同一时刻只有一个会话在写）。
# 用目录锁：mkdir 是原子的；陈旧判定只看 pid 是否真的还活着。

LOCK_NAME = '.runlock'


def pid_alive(pid: int) -> bool:
  """判活。**不能用 os.kill(pid, 0)**：Windows 上 os.kill 走 TerminateProcess，
  信号 0 会真的把进程杀掉。用 tasklist；判断不了就当活着（宁可拒绝并发）。"""
  try:
    out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                         capture_output=True, text=True, errors='replace', timeout=15)
  except (OSError, subprocess.SubprocessError):
    return True
  return str(pid) in (out.stdout or '')


def acquire_runlock(out_root: Path, run_id: str) -> tuple[bool, str]:
  """拿目录锁。返回 (成功, 锁路径或原因)。"""
  lock = out_root / LOCK_NAME
  try:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.mkdir()
  except FileExistsError:
    owner_file = lock / 'owner.json'
    try:
      info = json.loads(owner_file.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
      return False, f'锁目录存在但读不到 owner.json（崩在 mkdir 之后、写 owner 之前）: {lock}'
    pid = int(info.get('pid') or 0)
    if pid and pid_alive(pid):
      return False, (f'已有运行在跑：run_id={info.get("run_id", "?")} pid={pid}；'
                     f'起于 {info.get("at", "?")}')
    shutil.rmtree(lock, ignore_errors=True)
    try:
      lock.mkdir()
    except OSError as exc:
      return False, f'清理陈旧锁后重建失败: {exc}（手动删 {lock} 即可）'
  except OSError as exc:
    return False, f'建锁失败: {exc}'

  import os
  try:
    (lock / 'owner.json').write_text(
      json.dumps({'run_id': run_id, 'pid': os.getpid(),
                  'at': datetime.now().isoformat(timespec='seconds')},
                 ensure_ascii=False) + '\n',
      encoding='utf-8', newline='\n')
  except OSError as exc:
    shutil.rmtree(lock, ignore_errors=True)
    return False, f'锁已建但写不了 owner.json: {exc}'
  return True, str(lock)


def release_runlock(lock: Path) -> None:
  shutil.rmtree(lock, ignore_errors=True)


# ---------------------------------------------------------------- 执行

def do_run(task: str, timeout: int, out_root: Path, name: str | None,
           cwd: Path, dry: bool) -> int:
  run_id = new_run_id(name, task)
  run_dir = out_root / run_id
  # 同一秒同一名字撞车时加后缀，不覆盖别人的运行记录
  n = 1
  while run_dir.exists():
    n += 1
    run_dir = out_root / f'{run_id}-{n}'

  patch_file = run_dir / 'approval-never.yml'
  task_file = run_dir / 'task.md'
  stdout_file = run_dir / 'stdout.log'
  stderr_file = run_dir / 'stderr.log'
  meta_file = run_dir / 'meta.json'

  cmd = [str(DSH), '--profile', 'headless', '--patch', str(patch_file), '-']

  print(f'[RUN] {run_id}')
  print(f'      task   : {task.strip()[:120].replace(chr(10), " ")}')
  print(f'      timeout: {timeout}s')
  print(f'      cwd    : {cwd}')
  print(f'      沙箱   : workspace-write（未放宽）；只把审批改成 never')
  print(f'      输出   : {run_dir}')

  if dry:
    print('[DRY] 将执行:')
    print('      ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
    print('[DRY] patch 内容:')
    print('      ' + PATCH_YAML.replace('\n', '\n      ').rstrip())
    return 0

  if not DSH.is_file():
    print(f'[FAIL:能力缺失] 找不到 dsh CLI: {DSH}', file=sys.stderr)
    return 4

  ok, info = acquire_runlock(out_root, run_id)
  if not ok:
    print(f'[BUSY] {info}', file=sys.stderr)
    print(f'  两个 unattended 同时跑会抢同一个 profile 和记忆库。确认没有活进程了再手动删锁：{out_root / LOCK_NAME}', file=sys.stderr)
    return 5
  lock_dir = Path(info)
  try:
    run_dir.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(PATCH_YAML, encoding='utf-8', newline='\n')
    task_file.write_text(task, encoding='utf-8', newline='\n')

    meta = {
      'run_id': run_id,
      'task_preview': task.strip()[:300],
      'task_chars': len(task),
      'timeout_s': timeout,
      'cwd': str(cwd),
      'sandbox': 'workspace-write',
      'approval': 'never',
      'started_at': datetime.now().isoformat(timespec='seconds'),
      'dry': False,
    }
    write_json(meta_file, meta)
    journal('unattended.start', run_id=run_id, timeout_s=timeout,
            task_chars=len(task), cwd=str(cwd))

    t0 = time.time()
    timed_out = False
    rc: int | None = None
    with task_file.open('r', encoding='utf-8') as fin, \
         stdout_file.open('w', encoding='utf-8', newline='\n') as fout, \
         stderr_file.open('w', encoding='utf-8', newline='\n') as ferr:
      proc = subprocess.Popen(cmd, stdin=fin, stdout=fout, stderr=ferr, cwd=str(cwd))
      meta['pid'] = proc.pid
      write_json(meta_file, meta)
      try:
        rc = proc.wait(timeout=timeout)
      except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        try:
          rc = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
          rc = None
          print(f'[WARN] pid={proc.pid} 15 秒内没退出，可能仍有残留', file=sys.stderr)

    duration = round(time.time() - t0, 1)
    out_size = stdout_file.stat().st_size if stdout_file.exists() else 0
    err_size = stderr_file.stat().st_size if stderr_file.exists() else 0
    out_tail = ''
    if out_size:
      out_tail = stdout_file.read_text(encoding='utf-8', errors='replace').strip()[-400:]

    meta.update({
      'finished_at': datetime.now().isoformat(timespec='seconds'),
      'duration_s': duration,
      'rc': rc,
      'timed_out': timed_out,
      'stdout_bytes': out_size,
      'stderr_bytes': err_size,
      'stdout_tail': out_tail,
    })
    write_json(meta_file, meta)

    if timed_out:
      journal('unattended.timeout', run_id=run_id, duration_s=duration, pid=meta.get('pid'))
    elif rc == 0:
      journal('unattended.done', run_id=run_id, duration_s=duration, rc=rc)
    else:
      journal('unattended.failed', run_id=run_id, duration_s=duration, rc=rc)

    print()
    print(f'[DONE] rc={rc}  {duration}s  stdout={out_size}B  stderr={err_size}B'
          + ('  [TIMEOUT 已杀进程树]' if timed_out else ''))
    if out_tail:
      print('--- stdout 末尾 ---')
      print(out_tail)
    if timed_out:
      print(f'[注意] 任务被 {timeout}s 超时打断，现场可能只做了一半。'
            f'续跑请先看 {run_dir} 里的 stdout.log / task.md。')
      return 2
    if rc != 0:
      print(f'[注意] 进程退出码 {rc}，原因看 {stderr_file}')
      return 1
    return 0
  finally:
    release_runlock(lock_dir)


# ---------------------------------------------------------------- 查询

def list_runs(out_root: Path) -> int:
  if not out_root.exists():
    print('还没有 unattended 运行记录。')
    return 0
  rows = []
  for d in sorted(out_root.iterdir(), reverse=True):
    if not d.is_dir():
      continue
    meta_file = d / 'meta.json'
    if not meta_file.is_file():
      continue
    try:
      meta = json.loads(meta_file.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
      continue
    rows.append(meta)
  if not rows:
    print('还没有 unattended 运行记录。')
    return 0
  print(f'共 {len(rows)} 次运行（最近在前）：')
  print(f'{"run_id":<34} {"时长":>7} {"rc":>4} {"超时":>4}  任务')
  for m in rows[:30]:
    flag = 'YES' if m.get('timed_out') else ''
    preview = (m.get('task_preview') or '').replace('\n', ' ')[:52]
    print(f'{m.get("run_id", "?"):<34} {str(m.get("duration_s", "?")) + "s":>7} '
          f'{str(m.get("rc")):>4} {flag:>4}  {preview}')
  return 0


def show_run(out_root: Path, run_id: str) -> int:
  run_dir = out_root / run_id
  if not run_dir.is_dir():
    print(f'[FAIL:用途错误] 没有这个运行记录: {run_dir}', file=sys.stderr)
    return 3
  meta_file = run_dir / 'meta.json'
  if meta_file.is_file():
    print(meta_file.read_text(encoding='utf-8', errors='replace'))
  for name in ('stdout.log', 'stderr.log'):
    f = run_dir / name
    if not f.is_file():
      continue
    text = f.read_text(encoding='utf-8', errors='replace')
    print(f'--- {name}（{len(text)} 字符，显示末尾 3000）---')
    print(text[-3000:])
  return 0


def last_run(out_root: Path) -> int:
  if not out_root.exists():
    print('还没有 unattended 运行记录。')
    return 0
  dirs = sorted([d for d in out_root.iterdir() if d.is_dir() and (d / 'meta.json').is_file()],
                reverse=True)
  if not dirs:
    print('还没有 unattended 运行记录。')
    return 0
  return show_run(out_root, dirs[0].name)


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
  ap = argparse.ArgumentParser(
    prog='lab unattended',
    description='无人值守跑一个 headless 任务（只关审批，沙箱仍是 workspace-write）')
  ap.add_argument('task', nargs='?', help='任务文本（与 --task-file 二选一）')
  ap.add_argument('--task-file', help='从文件读任务文本（长任务用这个，避免命令行长度限制）')
  ap.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT,
                  help=f'硬超时秒数，默认 {DEFAULT_TIMEOUT}；到点杀整棵进程树')
  ap.add_argument('--name', help='运行名（决定目录名，缺省从任务文本取）')
  ap.add_argument('--out', default=str(OUT_ROOT), help=f'输出根目录，默认 {OUT_ROOT}')
  ap.add_argument('--cwd', default=str(ROOT), help='headless 的工作目录（决定沙箱可写范围）')
  ap.add_argument('--dry', action='store_true', help='只打印将执行的命令，不真跑')
  ap.add_argument('--list', action='store_true', help='列出历史运行')
  ap.add_argument('--show', metavar='RUN_ID', help='看某一次运行的 meta 和输出')
  ap.add_argument('--last', action='store_true', help='看最近一次运行')
  a = ap.parse_args(argv)

  out_root = Path(a.out)
  if a.list:
    return list_runs(out_root)
  if a.show:
    return show_run(out_root, a.show)
  if a.last:
    return last_run(out_root)

  task = a.task
  if a.task_file:
    tf = Path(a.task_file)
    if not tf.is_file():
      print(f'[FAIL:用途错误] 找不到任务文件: {tf}', file=sys.stderr)
      return 3
    task = tf.read_text(encoding='utf-8', errors='replace')
  if not task or not task.strip():
    print('[FAIL:用途错误] 没有任务文本：给位置参数或 --task-file', file=sys.stderr)
    return 3

  if a.timeout <= 0:
    print('[FAIL:用途错误] --timeout 必须 > 0', file=sys.stderr)
    return 3

  cwd = Path(a.cwd)
  if not cwd.is_dir():
    print(f'[FAIL:用途错误] --cwd 不是目录: {cwd}', file=sys.stderr)
    return 3

  return do_run(task, a.timeout, out_root, a.name, cwd, a.dry)


if __name__ == '__main__':
  sys.exit(main())
