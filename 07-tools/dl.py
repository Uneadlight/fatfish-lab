"""lab dl —— 下载的唯一入口：选源 -> 测速 -> 判断要不要继续。

为什么单独做一个命令，而不是继续手写 `curl`：

2026-11-17 下 FFmpeg（192.5 MB），六条源只有一条能跑：
gyan.dev 换手机热点后仍 0.02 MB/s（不是带宽是路由）、winget 30 KB/s、
ghproxy 超时、ghfast 403、清华/南大都没这个包、npm 的最高版本比本机还旧。
我手写 curl 试了五个源，花掉 20 分钟，而 `lab nettest` 早就存在
（SKILL.md:602 写着触发信号、`lab tier` 的能力盘点区会主动顶它）——
**工具在，触发信号在，我照样没跑，因为我把「下载一个文件」归类成了不用查的肌肉记忆。**

所以这里不是再加一个可选工具，而是把三步焊死在一次调用里：
1. **选源**：所有给的 URL 都测（只给一个 URL = 只有一个候选，但测速照样跑）
2. **测速**：各下 8 MB **落盘算真实字节**，不接受「响应快」当速度——
   Range 请求被 403 秒拒时，curl 照样 2.3 秒返回，只看耗时能算出 12.87 MB/s 的假速度
3. **判断要不要继续**：按实测速度算总耗时，超过 --max-minutes 就**停下来**，
   exit 3 让人决定，而不是闷头下 60 分钟然后在中途断掉

退出码：0=下完且字节校验通过 / 1=失败 / 2=用法错 / 3=超预算要求确认
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROBE_BYTES = 8 * 1024 * 1024
PROBE_TIMEOUT = 20
# 错误页/403 的量级：低于这个字节数一律当「没拿到真数据」
MIN_REAL_BYTES = 100_000


def _curl() -> str:
    return shutil.which('curl.exe') or shutil.which('curl') or 'curl.exe'


def head_size(url: str, timeout: int = PROBE_TIMEOUT) -> tuple[int, str]:
    """拿 Content-Length（跟随重定向）。返回 (bytes, 错误)。拿不到返回 0。"""
    cmd = [_curl(), '-sIL', '--max-time', str(timeout), url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout + 5)
    except FileNotFoundError:
        return 0, '找不到 curl'
    except subprocess.TimeoutExpired:
        return 0, 'HEAD 超时'
    sizes = [int(m) for m in re.findall(r'content-length:\s*(\d+)', (r.stdout or '').lower())]
    if not sizes:
        return 0, '没有 Content-Length（服务端可能不支持 Range）'
    return sizes[-1], ''


def probe(url: str, probe_bytes: int = PROBE_BYTES, timeout: int = PROBE_TIMEOUT) -> tuple[float, int, str]:
    """落盘测速。返回 (KB/s, 真实字节数, 错误)。

    **落盘是硬要求**：只信文件大小，不信 curl 报的耗时。
    """
    fd, tmp = tempfile.mkstemp(prefix='labdl-probe-')
    os.close(fd)
    try:
        cmd = [
            _curl(), '-L', '-s', '-o', tmp,
            '-r', f'0-{probe_bytes - 1}',
            '--max-time', str(timeout),
            '-w', '%{http_code} %{size_download}',
            url,
        ]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=timeout + 5)
        except FileNotFoundError:
            return 0.0, 0, '找不到 curl'
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            actual = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            if actual >= MIN_REAL_BYTES:
                return actual / 1024.0 / max(elapsed, 0.1), actual, '部分完成（超时）'
            return 0.0, actual, f'超时（>{timeout}s）且只拿到 {actual} 字节'
        elapsed = max(time.time() - t0, 0.05)
        actual = os.path.getsize(tmp) if os.path.exists(tmp) else 0

        meta = (r.stdout or '').strip()
        parts = meta.split()
        http = parts[0] if parts else '???'

        if actual < MIN_REAL_BYTES:
            return 0.0, actual, f'HTTP {http}，只拿到 {actual} 字节（多半是错误页/被拒）'
        return actual / 1024.0 / elapsed, actual, ''
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def human(kbps: float) -> str:
    if kbps >= 1024:
        return f'{kbps / 1024:.2f} MB/s'
    return f'{kbps:.0f} KB/s'


def human_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f'{n / 1024 ** 3:.2f} GB'
    if n >= 1024 ** 2:
        return f'{n / 1024 ** 2:.1f} MB'
    if n >= 1024:
        return f'{n / 1024:.0f} KB'
    return f'{n} B'


def main(argv: list[str]) -> int:
    # PS5.1 的控制台是 GBK，中文/符号直接 print 有编码风险；能重配就重配成 UTF-8
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        prog='lab dl',
        description='下载的唯一入口：先选源测速，预估超预算就停下问，再下并校验。')
    ap.add_argument('urls', nargs='+', help='一个或多个下载地址（多个 = 多源赛跑）')
    ap.add_argument('-o', '--output', help='存到哪；不给就取 URL 最后一段')
    ap.add_argument('--max-minutes', type=float, default=30.0,
                    help='预估耗时上限（分钟），超了就 exit 3 停下问，默认 30')
    ap.add_argument('--probe-only', action='store_true', help='只测速和预估，不下载')
    ap.add_argument('--no-resume', action='store_true', help='不续传（默认 -C - 续传）')
    a = ap.parse_args(argv)

    print(f'[DL] 候选 {len(a.urls)} 个源；先各下 {PROBE_BYTES // 1024 // 1024} MB 测真实吞吐')
    print()

    rows = []
    for url in a.urls:
        print(f'[DL] 测速 {url[:90]}', flush=True)
        total, err_head = head_size(url)
        kbps, got, err = probe(url)
        rows.append({'url': url, 'kbps': kbps, 'got': got, 'total': total,
                     'err': err or err_head})
        speed = human(kbps) if kbps else '失败'
        size = human_size(total) if total else '大小未知'
        print(f'     {speed:>10}  {size:>10}  {err if (err and not kbps) else ""}')
    print()

    rows.sort(key=lambda r: -r['kbps'])
    best = rows[0]

    print('[DL] 排名：')
    for i, r in enumerate(rows, 1):
        mark = '  << 用它' if i == 1 and r['kbps'] else ''
        print(f'  {i}. {human(r["kbps"]) if r["kbps"] else "失败":>10}  {r["url"][:76]}{mark}')
    print()

    if not best['kbps']:
        print('[DL] 所有源都没测出真实吞吐——检查网络、URL 是否需要 header，或改用别的源。')
        return 1

    # 第三步：判断要不要继续
    est_min = None
    if best['total']:
        est_min = (best['total'] / 1024.0) / best['kbps'] / 60.0
        print(f'[DL] 总大小 {human_size(best["total"])}，实测 {human(best["kbps"])}'
              f' -> 预估 {est_min:.1f} 分钟')
    else:
        print(f'[DL] 总大小未知（服务端没给 Content-Length），实测 {human(best["kbps"])}'
              f'；无法预估，按 --max-minutes 无法把关')

    if est_min is not None and est_min > a.max_minutes:
        print()
        print(f'[DL] [X] 预估 {est_min:.2f} 分钟 > 预算 {a.max_minutes:g} 分钟，**停下**。')
        print(f'[DL] 三条路：①继续跑：加 --max-minutes {int(est_min * 1.5) + 5}')
        print(f'[DL]          ②换源：这台机器上常见的原因是路由而非带宽')
        print(f'[DL]          ③放弃：先问这件事值不值得为它花 {est_min:.0f} 分钟')
        return 3

    if a.probe_only:
        print('[DL] --probe-only：到此为止，没下载。')
        return 0

    # 第四步：下载
    out = Path(a.output or Path(best['url'].split('?')[0]).name or 'download.bin')
    print()
    print(f'[DL] 下载 -> {out}')

    tmp_out = out.with_suffix(out.suffix + '.part')
    cmd = [_curl(), '-L', '--retry', '20', '--retry-delay', '3', '--retry-all-errors',
           '--connect-timeout', '20', '-o', str(tmp_out)]
    if not a.no_resume:
        cmd += ['-C', '-']
    cmd.append(best['url'])

    t0 = time.time()
    rc = subprocess.call(cmd)
    elapsed = time.time() - t0

    if rc != 0:
        got = tmp_out.stat().st_size if tmp_out.exists() else 0
        print(f'[DL] [X] curl 退出码 {rc}，{elapsed:.0f} 秒，已存 {human_size(got)}')
        print(f'[DL] 已下的部分在 {tmp_out}，重跑同一条命令会断点续传。')
        return 1

    # 第五步：校验字节数
    got = tmp_out.stat().st_size if tmp_out.exists() else 0
    if best['total'] and got != best['total']:
        print(f'[DL] [X] 大小不符：期望 {human_size(best["total"])}，实际 {human_size(got)}')
        print(f'[DL] 文件留在 {tmp_out}，重跑可续传。')
        return 1

    os.replace(tmp_out, out)
    speed = human(got / 1024.0 / max(elapsed, 0.1))
    print(f'[DL] [OK] {out}  {human_size(got)}  {elapsed:.0f} 秒  {speed}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
