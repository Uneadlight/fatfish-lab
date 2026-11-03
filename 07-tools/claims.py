"""claims.py —— 把「我说做完了」变成「证据说得对」。

治 #1（形式完成）：我说"扫完了 256 个插件"时，脚本去问——
  有条目数吗？抽样结果呢？提交号呢？文件真的存在吗？
对不上的，列出来。

用法：
  py claims.py                        # 今天的决策日志
  py claims.py --date 2026-11-02      # 指定日期
  py claims.py --file some.md         # 指定文件
  py claims.py --all                  # 全部日期汇总

判据（一条声明算「有证据」，段落内必须出现至少一个）：
  ① 提交号：7-40 位 hex（且能在某个仓库 git cat-file 到）
  ② 测试结果：`\\d+ passed` / `\\d+ failed` / `exit=0` / `exit 0` / `[OK]`
  ③ 实测数字：`\\d+ 个` / `\\d+ 条` / `\\d+ 项` / `\\d+ B` / `\\d+ 秒`
  ④ 文件路径：反引号或裸路径，且文件真的存在
  ⑤ 外部读回：`远端` / `回读` / `hash` / `SHA256` / `HTTP 200`
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG = Path(r'D:\work\自进化\决策日志.md')
REPOS_ROOT = Path(r'D:\work')
GIT = Path(r'D:\work\tools\git\cmd\git.exe')

# 「完成声明」——只在明确说自己做成了什么时触发
CLAIM_RE = re.compile(
    r'(完成了|做好了|写完了|写好了|读完了|跑通了|修好了|搞定了|做完了|扫完了|'
    r'改好了|装好了|发布成功|推送成功|上线了|全部通过|全绿|已交付|已落地|'
    r'已完成|已修复|已发布|已实现|已上传|已提交|已同步)'
)

# 五种证据
SHA_RE = re.compile(r'\b[0-9a-f]{7,40}\b')
TEST_RE = re.compile(r'(\d+ passed|\d+ failed|exit[= ]0|\[OK\]|\[PASS\])', re.IGNORECASE)
NUM_RE = re.compile(r'(\d[\d,]*\s*(个|条|项|B|秒|分钟|行|字符|MB|KB|GB|次))')
PATH_RE = re.compile(r'([A-Za-z]:[\\/][^\s`\'"，、)）]+\.(py|js|mjs|md|json|yml|yaml|ps1|txt|toml|cjs))')
READBACK_RE = re.compile(r'(远端|回读|哈希|SHA256|HTTP 200|status.*200)', re.IGNORECASE)


def git_has_sha(sha: str) -> bool:
    """这个 hex 是不是某个仓库里的真提交。"""
    for repo in REPOS_ROOT.iterdir():
        if not (repo / '.git').exists():
            continue
        try:
            r = subprocess.run(
                [str(GIT), 'cat-file', '-e', f'{sha}^{{commit}}'],
                cwd=repo, capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def evidence_of(para: str) -> list[str]:
    """一个段落里找到了哪几种证据。"""
    found = []

    for m in SHA_RE.finditer(para):
        sha = m.group(0)
        if len(sha) >= 7 and git_has_sha(sha):
            found.append(f'提交 {sha}')
            break

    if TEST_RE.search(para):
        found.append('测试/退出码')
    if NUM_RE.search(para):
        found.append('实测数字')
    if READBACK_RE.search(para):
        found.append('外部读回')

    for m in PATH_RE.finditer(para):
        p = Path(m.group(1))
        if p.exists():
            found.append(f'文件存在 {p.name}')
            break

    return found


def split_paras(text: str):
    """按标题切段，返回 [(行号, 段落文本)]。"""
    lines = text.splitlines()
    out = []
    buf, start = [], 0
    for i, ln in enumerate(lines, 1):
        if ln.startswith('## '):
            if buf and start:
                out.append((start, '\n'.join(buf)))
            buf, start = [ln], i
        else:
            buf.append(ln)
    if buf:
        out.append((start, '\n'.join(buf)))
    return out


def analyze(text: str) -> dict:
    claims, backed, unbacked = 0, 0, []

    for start, para in split_paras(text):
        if not CLAIM_RE.search(para):
            continue
        ev = evidence_of(para)
        if ev:
            claims += 1
            backed += 1
        else:
            claims += 1
            # 挑出触发的那句话
            hit = None
            for ln in para.splitlines():
                if CLAIM_RE.search(ln) and ln.strip():
                    hit = ln.strip()
                    break
            unbacked.append({
                'line': start,
                'text': (hit or para.splitlines()[0])[:110],
            })

    return {'claims': claims, 'backed': backed, 'unbacked': unbacked}


def main() -> None:
    ap = argparse.ArgumentParser(description='完成声明的证据对账')
    ap.add_argument('--date', help='YYYY-MM-DD')
    ap.add_argument('--file', help='直接指定文件')
    ap.add_argument('--all', action='store_true', help='全部日期汇总')
    ap.add_argument('--json', action='store_true', help='JSON 输出')
    args = ap.parse_args()

    if args.file:
        # utf-8-sig：PowerShell 的 Set-Content -Encoding UTF8 会写 BOM，
        # 而 BOM 会让 `ln.startswith('## ')` 对第一行失配，整段被吞。
        text = Path(args.file).read_text(encoding='utf-8-sig')
        print(f'[CLAIMS] {args.file}')
        r = analyze(text)
        report(r, args.json)
        return

    full = LOG.read_text(encoding='utf-8-sig')

    if args.all:
        total, backed, all_unbacked = 0, 0, []
        for start, para in split_paras(full):
            m = re.match(r'## (\d{4}-\d{2}-\d{2})', para)
            if not m:
                continue
            r = analyze(para)
            total += r['claims']
            backed += r['backed']
            for u in r['unbacked']:
                all_unbacked.append({'date': m.group(1), **u})
        print(f'[CLAIMS] 全部日期：{total} 条声明，有证据 {backed}，无证据 {len(all_unbacked)}')
        if all_unbacked:
            print('\n无证据清单：')
            for u in all_unbacked[:30]:
                print(f"  {u['date']} L{u['line']}: {u['text']}")
        return

    date = args.date or datetime.now().strftime('%Y-%m-%d')
    # 取该日期的所有段
    section = []
    for start, para in split_paras(full):
        if para.startswith(f'## {date}'):
            section.append(para)
    if not section:
        print(f'[CLAIMS] {date} 没有日志段')
        return

    print(f'[CLAIMS] {date}（{len(section)} 段）')
    total, backed, unbacked = 0, 0, []
    for para in section:
        r = analyze(para)
        total += r['claims']
        backed += r['backed']
        unbacked.extend(r['unbacked'])

    report({'claims': total, 'backed': backed, 'unbacked': unbacked}, args.json)


def report(r: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    c, b = r['claims'], r['backed']
    pct = (b / c * 100) if c else 0
    print(f'  完成声明 {c} 条')
    print(f'  有证据 {b} 条（{pct:.0f}%）')
    print(f'  无证据 {len(r["unbacked"])} 条')
    if r['unbacked']:
        print('\n  无证据清单（这些话说出口时没有东西接着）：')
        for u in r['unbacked']:
            print(f"    L{u['line']}: {u['text']}")
    sys.exit(0 if not r['unbacked'] else 1)


if __name__ == '__main__':
    main()
