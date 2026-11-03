"""编码检测 / 解码 / 乱码修复。抄自 dsh-encoding（`src/encoding.js`，187 行，零依赖）的判据，
改成 Python 版并加上 CLI——因为我最常踩的坑不是"插件读不了文件"，是**我自己用错解码器**：

    Get-Content 读 UTF-8 → 按 GBK 解码 → 满屏乱码 → 我误判"数据坏了"去抢救

2026-11-02 真栽过一次（dispatch 的 tasks.json 明明 4,664 B 完全正常）。
所以这个工具的主场是 `read`：**给定文件，先判编码，再解码，把结果吐出来**。

判据（与 dsh-encoding 一致，改为可解释的三段式）：
  1. BOM 最硬：FF FE → utf-16le；EF BB BF → utf-8
  2. UTF-16LE 启发式：奇数位零字节占比 >= 0.5
  3. 严格 UTF-8 校验（不合法就不是 UTF-8）
  4. GBK 启发式：高位字节（0x81-0xFE）占比 >= 0.2
  5. 都不中 → binary（按 latin1 逐字节映射）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ENCODINGS = ['utf-8', 'utf-16le', 'gbk', 'binary']

_PY_CODEC = {
    'utf-8': 'utf-8',
    'utf8': 'utf-8',
    'utf-16le': 'utf-16-le',
    'utf16le': 'utf-16-le',
    'utf-16': 'utf-16',
    'gbk': 'gbk',
    'gb18030': 'gb18030',
    'binary': 'latin-1',
    'latin1': 'latin-1',
    'latin-1': 'latin-1',
}


def _codec(name: str) -> str:
    return _PY_CODEC.get(name.lower(), name)


def is_valid_utf8(raw: bytes) -> bool:
    try:
        raw.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def detect_encoding(raw: bytes) -> str:
    """返回 'utf-8' | 'utf-16le' | 'gbk' | 'binary'。"""
    if not raw:
        return 'utf-8'
    if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
        return 'utf-16le'
    if len(raw) >= 3 and raw[0] == 0xEF and raw[1] == 0xBB and raw[2] == 0xBF:
        return 'utf-8'

    # UTF-16LE：奇数位（高字节）大量为 0
    odd = len(raw) // 2
    if odd >= 2:
        zero_odd = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
        if zero_odd / odd >= 0.5:
            return 'utf-16le'

    if is_valid_utf8(raw):
        return 'utf-8'

    high = sum(1 for b in raw if 0x81 <= b <= 0xFE)
    if len(raw) and high / len(raw) >= 0.2:
        return 'gbk'

    return 'binary'


def decode(raw: bytes, encoding: str = 'auto') -> str:
    enc = detect_encoding(raw) if encoding == 'auto' else encoding
    return raw.decode(_codec(enc), errors='replace')


def suggest_recovery(text: str) -> tuple[str, str]:
    """猜乱码方向：返回 (from, to)。"""
    if '\u0000' in text:
        return ('latin1', 'utf-16le')
    if any(ord(c) > 0xFF for c in text):
        return ('utf-16le', 'gbk')
    return ('latin1', 'gbk')


def recover_mojibake(text: str, src: str = 'latin1', dst: str = 'gbk') -> dict:
    """把乱码还原。返回 {ok, text, note, from, to}；ok=False 表示结果不可信。"""
    notes = []
    if src == 'auto' or dst == 'auto':
        g_src, g_dst = suggest_recovery(text)
        if src == 'auto':
            src = g_src
        if dst == 'auto':
            dst = g_dst

    if '\uFFFD' in text:
        notes.append('输入里已有 U+FFFD：那些字符在更早的误解码时就被销毁了，救不回来')
    if src in ('latin1', 'latin-1', 'binary') and any(ord(c) > 0xFF for c in text):
        notes.append('输入含 latin1 范围外的字符，按单字节回编码会被截断，可能丢信息')

    try:
        raw = text.encode(_codec(src))
    except UnicodeEncodeError as e:
        return {'ok': False, 'text': '', 'note': '回编码失败：%s' % e, 'from': src, 'to': dst}

    try:
        out = raw.decode(_codec(dst), errors='replace')
    except LookupError as e:
        return {'ok': False, 'text': '', 'note': '目标编码不认识：%s' % e, 'from': src, 'to': dst}

    if '\uFFFD' in out:
        notes.append('输出里有 U+FFFD：部分字节序列在目标编码下非法，已被替换')

    return {'ok': not notes, 'text': out, 'note': ' '.join(notes), 'from': src, 'to': dst}


def _read_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def cmd_detect(a) -> int:
    raw = _read_bytes(a.file)
    enc = detect_encoding(raw)
    print('%s  %s  (%d B)' % (a.file, enc, len(raw)))
    if a.explain:
        if raw[:2] == b'\xff\xfe':
            print('  依据: BOM FF FE → utf-16le')
        elif raw[:3] == b'\xef\xbb\xbf':
            print('  依据: BOM EF BB BF → utf-8')
        elif enc == 'utf-16le':
            odd = len(raw) // 2
            z = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
            print('  依据: 奇数位零字节 %d/%d = %.2f >= 0.5' % (z, odd, z / max(odd, 1)))
        elif enc == 'utf-8':
            print('  依据: 严格 UTF-8 校验通过')
        elif enc == 'gbk':
            high = sum(1 for b in raw if 0x81 <= b <= 0xFE)
            print('  依据: 高位字节 %d/%d = %.2f >= 0.2' % (high, len(raw), high / max(len(raw), 1)))
        else:
            print('  依据: 以上都不中 → 按 latin1 逐字节映射')
    if a.json:
        print(json.dumps({'file': a.file, 'encoding': enc, 'size': len(raw)}, ensure_ascii=False))
    return 0


def cmd_read(a) -> int:
    raw = _read_bytes(a.file)
    enc = a.encoding if a.encoding != 'auto' else detect_encoding(raw)
    text = decode(raw, enc)
    if a.json:
        print(json.dumps({'file': a.file, 'encoding': enc, 'text': text}, ensure_ascii=False))
    else:
        print('# %s  [%s, %d B]' % (a.file, enc, len(raw)))
        print(text, end='' if text.endswith('\n') else '\n')
    return 0


def cmd_fix(a) -> int:
    """把乱码文字还原。不给 --text 就走 stdin。"""
    if a.file:
        raw = _read_bytes(a.file)
        src_text = decode(raw, a.encoding if a.encoding != 'auto' else detect_encoding(raw))
    else:
        # 注意 nargs='*' 给的是 list，必须拼成 str——否则 recover 里 `in` 判断会炸
        src_text = ' '.join(a.text) if a.text else sys.stdin.read()
    r = recover_mojibake(src_text, a.frm, a.to)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(r['text'])
        if r['note']:
            print('\n[注意] ' + r['note'], file=sys.stderr)
    return 0 if r['ok'] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='encoding', description='判编码 / 解码 / 修乱码')
    sub = p.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('detect', help='判一个文件是什么编码')
    d.add_argument('file')
    d.add_argument('--explain', action='store_true', help='说明依据')
    d.add_argument('--json', action='store_true')
    d.set_defaults(func=cmd_detect)

    r = sub.add_parser('read', help='按自动识别的编码读出来（治 Get-Content 乱码）')
    r.add_argument('file')
    r.add_argument('--encoding', default='auto')
    r.add_argument('--json', action='store_true')
    r.set_defaults(func=cmd_read)

    f = sub.add_parser('fix', help='修乱码：GBK 被当 latin1 / UTF-16 被当单字节')
    f.add_argument('text', nargs='*')
    f.add_argument('--file', help='从文件读乱码原文')
    f.add_argument('--encoding', default='auto', help='读文件时用的编码')
    f.add_argument('--from', dest='frm', default='auto', help='latin1 / utf-16le / gbk')
    f.add_argument('--to', default='auto', help='gbk / utf-16le')
    f.add_argument('--json', action='store_true')
    f.set_defaults(func=cmd_fix)

    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == '__main__':
    sys.exit(main())
