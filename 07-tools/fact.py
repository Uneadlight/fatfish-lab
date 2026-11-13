"""lab fact —— 检查我说的话里，每个数字有没有「出处」。

设计转折（2026-11-03 第一次实测后改的）：
  初版想「自动验证每个数字对不对」——实测做不到。「43 条规矩」这种计数，机器不知道
  「什么算一条」。想验它，得先定义语义，而定义语义又回到「我以为」。

  所以换成能自动化的那一半：**验「有没有出处」，不验「对不对」。**
  「说 43 条规矩时，旁边有没有一个『见 SKILL.md:117』」——这是客观的。
  今天 8 次违规里 5 次是数字错，错的全是「没出处」——这个能抓。

四类输出：
  ✅ 有出处     数字附近有 文件:行 / 见 X / 实测 / grep / --help 等标记；sha 在仓库里真存在
  ⚠️ 无出处     数字附近什么都没有 —— 这就是「我编的」高发区；sha 在所有仓库都查不到
  💬 提示级     中文数字（「三个」「一处」）—— 常是叙述，列出来自己扫一眼，不算硬错
  ❌ 路径不存在  话里提到的路径查不到

2026-11-06 补：中文数字 + 短 sha 校验（这两个以前完全漏掉）。

另附：文件大小/行数的实际值（如果话里有路径），供人工比对。

用法：
  py lab.py fact "我改了 SKILL.md，43 条规矩"
  py lab.py fact --file note.txt
  echo "..." | py lab.py fact
"""

import re
import subprocess
import sys
from pathlib import Path

# 数字 + 单位（含中文）
RE_NUM = re.compile(
    r'([\d,]+(?:\.\d+)?)\s*(个|条|处|次|轮|批|家|类|份|行|B|字节|字符|项|种|页|张|秒|分钟|小时|元|MB|GB|%)'
)
# 出处标记：文件:行 / 见 xxx / 实测 / grep / --help / 查过
RE_CITE = re.compile(
    r'[^\s，。、；：（）]+\.(?:py|js|ts|md|json|yml|yaml|ps1|cmd|txt):\d+'
    r'|见\s*[^\s，。、；（）]{2,}'
    r'|查过|实测|grep|--help|退出码|回读|核对|比对'
)
RE_PATH = re.compile(r'[A-Za-z]:\\[^\s，。、；："\'）】（【〔〕\[］]+')
RE_LINEREF = re.compile(r'([A-Za-z]:\\[^\s:]+\.(?:py|js|ts|md|json|yml|yaml|ps1|cmd)):(\d+)')

# 中文数字 + 量词（「三处」「十二条」）。排除序数「第一轮」和纯口语「一个/一样」。
CN_NUM = '零一二三四五六七八九十百千万两'
RE_CN = re.compile(rf'(?<!第)([{CN_NUM}]{{1,6}})\s*(个|条|处|次|轮|批|家|类|份|行|项|种|页|张)')
CN_SKIP = frozenset('一个 一种 一次 一样 一起 一直 一定 一般 一行 一页 一张 一批 一家 一项 一份'.split())

# 短 sha（7-40 位小写 hex，必须含 a-f，排除纯数字）。最多验 MAX_SHA 个，避免满屏 hex 时拖慢。
RE_SHA = re.compile(r'(?<![0-9a-fA-F])([0-9a-f]{7,40})(?![0-9a-fA-F])')
MAX_SHA = 5

GIT_CANDIDATES = (Path(r'D:\work\tools\git\cmd\git.exe'),)
REPO_CANDIDATES = (
    Path(r'D:\work'),
    Path(r'D:\work\架构文档'),
    Path(r'D:\work\闭关'),
    Path(r'D:\work\worktree-repo'),
    Path(r'D:\work\Self-Opt'),
    Path(r'D:\work\repos\dafeiyu-lab'),
    Path(r'D:\work\repos\dafeiyu-lab-durable'),
)


def git_exe():
    for p in GIT_CANDIDATES:
        if p.is_file():
            return str(p)
    return 'git'


def find_sha(sha):
    """在所有已知仓库里找这个提交；返回 (仓库路径, 对象类型) 或 None。"""
    for repo in REPO_CANDIDATES:
        if not (repo / '.git').exists():
            continue
        try:
            r = subprocess.run([git_exe(), '-C', str(repo), 'cat-file', '-t', sha],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return repo, r.stdout.strip()
    return None


WINDOW = 150          # 数字前后多少字符内找出处


def num(s):
    return float(s.replace(',', ''))


def main(argv):
    if '--file' in argv:
        text = Path(argv[argv.index('--file') + 1]).read_text(encoding='utf-8')
    elif argv and not argv[0].startswith('-'):
        text = ' '.join(argv)
    else:
        text = sys.stdin.read()

    if not text.strip():
        print('没有输入', file=sys.stderr)
        return 2

    ok = bad = unknown = hint = 0
    lines = []

    # 1) 路径存在性（先剥掉可能的 :行号 尾巴，否则 E:\x\y.md:147 会被当成路径）
    seen_paths = set()
    for m in RE_PATH.finditer(text):
        p = re.sub(r':\d+$', '', m.group(0))
        if p in seen_paths:
            continue
        seen_paths.add(p)
        path = Path(p.rstrip('，。、；：）】'))
        if path.exists():
            size = f'{path.stat().st_size:,} B' if path.is_file() else '目录'
            lines.append(('OK', f'路径 {p}', f'存在，{size}'))
            ok += 1
        else:
            lines.append(('BAD', f'路径 {p}', '不存在'))
            bad += 1

    # 2) 行号引用
    for m in RE_LINEREF.finditer(text):
        f, n = m.group(1), int(m.group(2))
        path = Path(f)
        if not path.is_file():
            lines.append(('BAD', f'行号引用 {f}:{n}', '文件不存在'))
            bad += 1
            continue
        try:
            total = sum(1 for _ in path.open('r', encoding='utf-8', errors='replace'))
        except OSError as e:
            lines.append(('UNK', f'行号引用 {f}:{n}', str(e)))
            unknown += 1
            continue
        if n > total:
            lines.append(('BAD', f'行号引用 {f}:{n}', f'文件只有 {total} 行'))
            bad += 1
        else:
            lines.append(('OK', f'行号引用 {f}:{n}', f'文件 {total} 行，此行存在'))
            ok += 1

    # 3) 每个数字：附近有没有出处
    for m in RE_NUM.finditer(text):
        start = max(0, m.start() - WINDOW)
        end = min(len(text), m.end() + WINDOW)
        ctx = text[start:end]
        snippet = text[max(0, m.start() - 25):m.end() + 5].replace('\n', ' ')
        if RE_CITE.search(ctx):
            lines.append(('OK', f'数字「{m.group(0)}」', f'附近有出处标记  〔…{snippet}…〕'))
            ok += 1
        else:
            lines.append(('BAD', f'数字「{m.group(0)}」', f'**无出处，可能是编的**  〔…{snippet}…〕'))
            bad += 1

    # 3.5) 中文数字：同样的判据，但中文数字一直没被抓
    for m in RE_CN.finditer(text):
        token = m.group(0).replace(' ', '')
        if token in CN_SKIP:
            continue
        start = max(0, m.start() - WINDOW)
        end = min(len(text), m.end() + WINDOW)
        ctx = text[start:end]
        snippet = text[max(0, m.start() - 25):m.end() + 5].replace('\n', ' ')
        if RE_CITE.search(ctx):
            lines.append(('OK', f'中文数字「{m.group(0)}」', f'附近有出处标记  〔…{snippet}…〕'))
            ok += 1
        else:
            # 中文数字比阿拉伯数字更常是叙述（「读了一遍」「改了三个文件」），
            # 所以降成提示级：列出来供人扫一眼，不计入 bad、不影响退出码。
            lines.append(('HINT', f'中文数字「{m.group(0)}」', f'无出处（提示级，可能只是叙述）  〔…{snippet}…〕'))
            hint += 1

    # 3.6) 短 sha：话里提到的提交号，真的存在吗
    seen_sha = set()
    for m in RE_SHA.finditer(text):
        sha = m.group(1)
        if sha in seen_sha or sha.isdigit() or not any(c in 'abcdef' for c in sha):
            continue
        if len(seen_sha) >= MAX_SHA:
            break
        seen_sha.add(sha)
        hit = find_sha(sha)
        if hit:
            repo, kind = hit
            lines.append(('OK', f'提交 {sha}', f'在 {repo} 里，类型 {kind}'))
            ok += 1
        else:
            lines.append(('BAD', f'提交 {sha}', '已知仓库里都找不到这个提交'))
            bad += 1

    # 4) 文件实际大小（供人工比对）
    hints = []
    for p in seen_paths:
        path = Path(p.rstrip('，。、；：）】'))
        if path.is_file():
            try:
                n = sum(1 for _ in path.open('r', encoding='utf-8', errors='replace'))
                hints.append(f'  {path.name}: {path.stat().st_size:,} B / {n} 行')
            except OSError:
                pass

    SYM = {'OK': '✅', 'BAD': '⚠️', 'UNK': '❓', 'HINT': '💬'}
    print('=' * 66)
    print(f'从 {len(text)} 字符里查到 {len(lines)} 项')
    print('=' * 66)
    for v, what, note in lines:
        print(f'{SYM[v]} {what}')
        print(f'    {note}')
    print('=' * 66)
    print(f'✅ 有依据 {ok} / ⚠️ 无出处或缺依据 {bad} / 💬 中文数字待看 {hint} / ❓ 查不了 {unknown}')

    if hints:
        print('\n文件实际值（拿它比对你说的数字）：')
        for h in hints:
            print(h)

    if bad:
        print('\n有 ⚠️：这些话里的事实没有出处。补出处，或者改说「我没查，这是印象」。')
        return 1
    if hint:
        print(f'\n没有硬性无出处项；另有 {hint} 个中文数字没标出处，扫一眼是不是真的在陈述数量。')
    else:
        print('\n全部有出处。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
