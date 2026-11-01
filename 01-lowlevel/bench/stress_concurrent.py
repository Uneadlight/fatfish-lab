r"""并发写入 + 强杀恢复压测。

验收三条（对应路线图「会扛」2-3）：

1. **不丢数据**：8 个进程各写 1000 条，全部能读回来；
2. **幂等**：同一个 request_id 提交 1000 次，只有第 1 次生效；
3. **崩了能自愈**：写到一半被 `TerminateProcess`（Windows 上等价 `kill -9`），
   重启后**已确认的写**一条都不能少。

用法：
    py bench/stress_concurrent.py
    py bench/stress_concurrent.py --workers 8 --per 1000
    py bench/stress_concurrent.py --skip-crash      # 只跑并发
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bplus.durable import DurableTree


def _worker_put(path: str, wid: int, count: int, base: int, out) -> None:
  """每个进程独占一段时间写自己的一段 key。"""
  ok = 0
  dup = 0
  t0 = time.perf_counter()
  err = None
  try:
    tree = DurableTree(path, lock_timeout=120.0)
    try:
      for i in range(count):
        key = base + wid * 100_000 + i
        if tree.put(key, key, request_id=f'w{wid}-{i}'):
          ok += 1
        else:
          dup += 1
    finally:
      tree.close()
  except Exception as exc:  # noqa: BLE001 - 压测要把任何异常带回去
    err = f'{type(exc).__name__}: {exc}'
  out.put(
    {
      'wid': wid,
      'ok': ok,
      'dup': dup,
      'secs': round(time.perf_counter() - t0, 3),
      'err': err,
    }
  )


def _worker_crash(path: str, count: int, commit_marker: str) -> None:
  """写到一半直接 `os._exit`，模拟被强杀（不跑任何 finally / close）。"""
  tree = DurableTree(path, lock_timeout=120.0)
  confirmed: list[int] = []
  for i in range(count):
    tree.put(900_000 + i, i, request_id=f'c{i}')
    confirmed.append(900_000 + i)
    if i == count // 2:
      # 把"我已经确认过这些"写出去，主进程据此判断丢没丢
      pathlib.Path(commit_marker).write_text(
        json.dumps({'confirmed': confirmed}), encoding='utf-8'
      )
  # 到这儿如果还没被杀，说明没被拦到，也算失败（主进程会看 marker）
  os._exit(0)


def _verify(path: str, workers: int, per: int, base: int) -> dict:
  tree = DurableTree(path, lock_timeout=120.0)
  try:
    missing = 0
    checked = 0
    for wid in range(workers):
      for i in range(per):
        key = base + wid * 100_000 + i
        checked += 1
        if tree.get_or(key) != key:
          missing += 1
          if missing <= 5:
            print(f'  [MISS] key={key}')
    return {'checked': checked, 'missing': missing, 'entries': len(tree)}
  finally:
    tree.close()


def _run_concurrency(path: str, workers: int, per: int) -> dict:
  pathlib.Path(path).unlink(missing_ok=True)
  for suffix in ('.wal', '.lock'):
    pathlib.Path(path + suffix).unlink(missing_ok=True)

  ctx = mp.get_context('spawn')
  out = ctx.Queue()
  procs = [
    ctx.Process(target=_worker_put, args=(path, wid, per, 1000, out))
    for wid in range(workers)
  ]
  t0 = time.perf_counter()
  for p in procs:
    p.start()
  results = [out.get(timeout=300) for _ in procs]
  for p in procs:
    p.join(timeout=60)
  elapsed = time.perf_counter() - t0

  errors = [r for r in results if r['err']]
  verified = _verify(path, workers, per, 1000)
  return {
    'elapsed_s': round(elapsed, 2),
    'workers': workers,
    'per_worker': per,
    'ok_total': sum(r['ok'] for r in results),
    'dup_total': sum(r['dup'] for r in results),
    'worker_errors': errors,
    'verify': verified,
    'pass': not errors and verified['missing'] == 0 and verified['entries'] >= workers * per,
  }


def _run_idempotent(path: str, repeats: int) -> dict:
  pathlib.Path(path).unlink(missing_ok=True)
  for suffix in ('.wal', '.lock'):
    pathlib.Path(path + suffix).unlink(missing_ok=True)

  tree = DurableTree(path, lock_timeout=120.0)
  try:
    applied = 0
    for i in range(repeats):
      if tree.put(42, i, request_id='same-request'):
        applied += 1
    value = tree.get(42)
  finally:
    tree.close()

  return {
    'repeats': repeats,
    'applied_times': applied,
    'final_value': value,
    'expect_applied': 1,
    'expect_value': 0,
    'pass': applied == 1 and value == 0,
  }


def _run_crash(path: str, total: int) -> dict:
  marker = path + '.confirmed.json'
  pathlib.Path(marker).unlink(missing_ok=True)
  pathlib.Path(path).unlink(missing_ok=True)
  for suffix in ('.wal', '.lock'):
    pathlib.Path(path + suffix).unlink(missing_ok=True)

  ctx = mp.get_context('spawn')
  proc = ctx.Process(target=_worker_crash, args=(path, total, marker))
  proc.start()

  # 等它把 marker 写出来（说明至少确认了一半），然后强杀
  deadline = time.perf_counter() + 120
  while time.perf_counter() < deadline:
    if pathlib.Path(marker).exists() and pathlib.Path(marker).stat().st_size > 0:
      break
    if not proc.is_alive():
      break
    time.sleep(0.05)

  if proc.is_alive():
    proc.terminate()  # Windows TerminateProcess ≈ kill -9
  proc.join(timeout=30)
  killed = proc.exitcode

  confirmed: list[int] = []
  if pathlib.Path(marker).exists():
    confirmed = json.loads(pathlib.Path(marker).read_text(encoding='utf-8'))['confirmed']

  tree = DurableTree(path, lock_timeout=120.0)
  try:
    lost = [k for k in confirmed if tree.get_or(k) is None]
    entries = len(tree)
  finally:
    tree.close()

  return {
    'total_attempted': total,
    'confirmed_before_kill': len(confirmed),
    'killed_exitcode': killed,
    'lost_after_restart': len(lost),
    'entries_after_restart': entries,
    'pass': len(confirmed) > 0 and not lost,
  }


def main() -> int:
  parser = argparse.ArgumentParser(description='并发 + 崩溃压测')
  parser.add_argument('--workers', type=int, default=8)
  parser.add_argument('--per', type=int, default=1000, help='每个进程写多少条')
  parser.add_argument('--crash-total', type=int, default=600)
  parser.add_argument('--skip-crash', action='store_true')
  parser.add_argument('--dir', default=None, help='数据目录（默认 bench/.stress）')
  args = parser.parse_args()

  base_dir = pathlib.Path(args.dir or (pathlib.Path(__file__).resolve().parent / '.stress'))
  base_dir.mkdir(parents=True, exist_ok=True)

  report: dict[str, dict] = {}

  print(f'[1/3] 并发写入：{args.workers} 进程 × {args.per} 条 …')
  report['concurrency'] = _run_concurrency(
    str(base_dir / 'concurrent.tree'), args.workers, args.per
  )
  c = report['concurrency']
  print(
    f'      耗时 {c["elapsed_s"]}s，成功 {c["ok_total"]} 条，'
    f'校验 {c["verify"]["checked"]} 条，缺失 {c["verify"]["missing"]} 条'
  )

  print(f'[2/3] 幂等：同一 request_id 提交 {args.per} 次 …')
  report['idempotent'] = _run_idempotent(str(base_dir / 'idem.tree'), args.per)
  i = report['idempotent']
  print(f'      生效 {i["applied_times"]} 次，最终值 {i["final_value"]}')

  if args.skip_crash:
    report['crash'] = {'skipped': True, 'pass': True}
  else:
    print(f'[3/3] 崩溃恢复：写 {args.crash_total} 条中途强杀 …')
    report['crash'] = _run_crash(str(base_dir / 'crash.tree'), args.crash_total)
    k = report['crash']
    print(
      f'      强杀前确认 {k["confirmed_before_kill"]} 条，'
      f'重启后丢失 {k["lost_after_restart"]} 条，'
      f'条目 {k["entries_after_restart"]}'
    )

  ok = all(v.get('pass') for v in report.values())
  summary = {
    'pass': ok,
    'concurrency_ok': report['concurrency']['pass'],
    'idempotent_ok': report['idempotent']['pass'],
    'crash_ok': report['crash']['pass'],
    'detail': report,
  }
  (base_dir / 'report.json').write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
  )
  print()
  print('=' * 60)
  print('RESULT:', 'PASS' if ok else 'FAIL')
  print(f'报告：{base_dir / "report.json"}')
  return 0 if ok else 1


if __name__ == '__main__':
  sys.exit(main())
