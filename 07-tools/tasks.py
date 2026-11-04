"""计划任务体检：把所有 DSH-* 任务的条件、状态、上次结果摆在一起。

为什么需要它：
2026-11-04 发现 DSH-Ledger-Collect 报 0x800710E0 失败，查下去是
DisallowStartIfOnBatteries=True —— 笔记本用电池时任务根本不许启动。
更糟的是 6 个 DSH 任务全中，扫了一周才发现。

根因不是"查不到"，是"没有一个地方把这些条件一次摆出来"。
env_doctor 只看任务活没活，不看它**为什么**活不了。
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 任务结果码里最常见的几个，翻译成人话
RESULT_CODES = {
    0: '成功',
    1: '失败（脚本自己报错）',
    0x41301: '正在运行',
    0x41303: '从未运行',
    0x800710E0: '被拒绝启动（多半是电池/空闲/网络条件）',
    0x8007010B: '目录不存在',
    0x80070420: '服务启动失败',
}

PS = r"""
$out = @()
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'DSH-*' } | ForEach-Object {
  $t = $_
  $i = $t | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
  $out += [PSCustomObject]@{
    name     = $t.TaskName
    path     = $t.TaskPath
    state    = $t.State.ToString()
    last     = if ($i.LastRunTime) { $i.LastRunTime.ToUniversalTime().ToString('o') } else { $null }
    result   = $i.LastTaskResult
    next     = if ($i.NextRunTime) { $i.NextRunTime.ToUniversalTime().ToString('o') } else { $null }
    batt     = [bool]$t.Settings.DisallowStartIfOnBatteries
    stopbatt = [bool]$t.Settings.StopIfGoingOnBatteries
    idle     = [bool]$t.Settings.RunOnlyIfIdle
    net      = $t.Settings.RunOnlyIfNetworkAvailable
  }
}
ConvertTo-Json -InputObject $out -Compress
"""


def _ps_json(script: str):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, 'powershell 超时（60 秒）'
    s = (r.stdout or '').strip()
    if not s:
        return None, (r.stderr or '').strip()[:200] or 'powershell 没有输出'
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        return None, f'JSON 解析失败：{e}｜原始前 200 字：{s[:200]}'
    if isinstance(data, dict):
        data = [data]
    return data, None


def _fmt(iso: str | None) -> str:
    if not iso:
        return '—'
    try:
        t = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        return t.astimezone().strftime('%m-%d %H:%M')
    except Exception:
        return iso[:16]


def _code_text(code) -> str:
    try:
        n = int(code)
    except (TypeError, ValueError):
        return str(code)
    if n in RESULT_CODES:
        return RESULT_CODES[n]
    if n == 267009 or n == 267011:
        return '正在运行'
    return f'0x{n & 0xFFFFFFFF:08X}'


def main(argv: list[str] | None = None) -> int:
    data, err = _ps_json(PS)
    if err:
        print(f'[ERROR] 拿不到计划任务：{err}')
        return 2
    if not data:
        print('没有 DSH-* 计划任务。')
        return 0

    rows = sorted(data, key=lambda r: r.get('name') or '')
    bad: list[str] = []

    print(f'[TASKS] 共 {len(rows)} 个 DSH-* 计划任务')
    print()

    for r in rows:
        name = r.get('name') or '?'
        state = r.get('state') or '?'
        last = _fmt(r.get('last'))
        nxt = _fmt(r.get('next'))
        res = r.get('result')
        res_txt = _code_text(res)
        flags = []
        if r.get('batt'):
            flags.append('电池时不许启动')
        if r.get('stopbatt'):
            flags.append('切电池就停')
        if r.get('idle'):
            flags.append('空闲结束就停')
        if r.get('net'):
            flags.append('必须有网络')
        if state == 'Disabled':
            flags.append('已禁用')

        icon = '✅'
        if flags:
            icon = '⚠️'
            bad.append(name)
        if res is not None and int(res) not in (0, 0x41301, 0x41303):
            icon = '❌'
            if name not in bad:
                bad.append(name)

        print(f'{icon} {name}')
        print(f'     状态 {state} ｜ 上次 {last}（{res_txt}） ｜ 下次 {nxt}')
        if flags:
            print(f'     条件：{" / ".join(flags)}')

    print()
    if bad:
        print(f'—— {len(bad)} 个需要看 ——')
        for n in bad:
            print(f'   {n}')
        print()
        print('  电池/空闲/网络这三个条件是最常见的「任务看起来好好的，就是不跑」的原因。')
        print('  改法（管理员）：')
        print('    $s = (Get-ScheduledTask -TaskName "<名字>").Settings')
        print('    $s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false')
        print('    Set-ScheduledTask -TaskName "<名字>" -Settings $s')
    else:
        print('全部正常：没有条件陷阱，也没有失败记录。')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
