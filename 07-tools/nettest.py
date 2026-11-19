"""lab nettest —— 下载前先量吞吐，别凭 HEAD 延迟选源。

为什么有这个命令：2026-11-02 我写过一条记忆「下载先测三个源，别用默认路径闷头跑」，
2026-11-06 装 Blender 时还是先选了阿里云镜像（因为 HEAD 延迟最低 236ms），
下到 93.9 MB 只有 0.38 MB/s 才发现不对，换官方源 7 MB/s。
**记忆里写着，但那一刻没被检索出来——所以它 4 天里生效 0 次。**
这条命令就是把「先测源」从记忆挪到动作：想不起记忆没关系，跑一下就知道了。
"""
from __future__ import annotations

import subprocess
import sys

# 只下载前 8 MB 测速：够反映吞吐，又不会为了测试本身浪费时间
PROBE_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 10


def probe(url: str, probe_bytes: int = PROBE_BYTES, timeout: int = TIMEOUT_S) -> tuple[float, str]:
    """返回 (KB/s, 错误说明)。速度 0 表示没测出来。"""
    cmd = [
        'curl.exe', '-L', '-s', '-o', 'NUL',
        '-r', f'0-{probe_bytes - 1}',
        '--max-time', str(timeout),
        '-w', '%{speed_download}',
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout + 5)
    except FileNotFoundError:
        return 0.0, '找不到 curl.exe'
    except subprocess.TimeoutExpired:
        return 0.0, f'超时（>{timeout}s）'
    raw = (r.stdout or '').strip()
    try:
        # curl 的 speed_download 单位是 bytes/s
        bps = float(raw or 0)
    except ValueError:
        return 0.0, f'curl 输出看不懂：{raw[:40]!r}'
    if bps <= 0:
        return 0.0, (r.stderr or '').strip()[:60] or '没拿到数据'
    return bps / 1024.0, ''


def human(kbps: float) -> str:
    if kbps >= 1024:
        return f'{kbps / 1024:.1f} MB/s'
    return f'{kbps:.0f} KB/s'


def main(argv: list[str]) -> int:
    if not argv:
        print('用法：lab nettest <url> [url2 ...]')
        print('      先各下 8 MB 测吞吐，再决定用哪个源——别只看 HEAD 延迟，它和速度差 7 倍都正常。')
        return 2

    rows = []
    for url in argv:
        print(f'[NTT] 测速 {url[:80]} …', flush=True)
        kbps, err = probe(url)
        rows.append((kbps, url, err))
        print(f'      {human(kbps) if kbps else "失败"}  {err}')

    if not rows:
        return 1

    rows.sort(key=lambda x: -x[0])
    best = rows[0]
    print()
    print('[NTT] 排名：')
    for i, (kbps, url, err) in enumerate(rows, 1):
        mark = ' << 用它' if i == 1 and kbps else ''
        print(f'  {i}. {human(kbps) if kbps else "失败":>10}  {url[:72]}{mark}')

    if best[0] > 0:
        print()
        print(f'[NTT] 最快的是 {human(best[0])}；建议用这一条，下载大文件时开 curl -C - 支持断点续传。')
        return 0
    print()
    print('[NTT] 全都没测出来——检查网络，或者这些 URL 需要额外 header。')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
