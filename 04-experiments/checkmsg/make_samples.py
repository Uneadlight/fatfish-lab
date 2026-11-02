"""第一步：从真实提交历史造 20 条样本（10 一致 + 10 错配）。

设计要点：
1. 错配必须用**相近**的提交（同 type/scope），否则太容易，测不出能力
2. diff 要截断：3B 只有 8K 上下文，给全量它就读不懂了
3. 每条样本存 label + reason，便于我复核

输出：E:\\DS公作区\\tools\\lab\\checkmsg\\samples.json
"""

import json
import re
import subprocess
from pathlib import Path

# 路径按我本机写的，跑之前改这里（或直接用 PATH 上的 git）
GIT = r'D:\work\tools\git\cmd\git.exe'
REPOS = [
    ('fatfish', r'D:\work\repos\dafeiyu-lab'),
    ('study', r'D:\work\学习计划\01-编程'),
    ('adv', r'D:\work\进阶-20261029'),
    ('seclusion', r'D:\work\闭关'),
    ('arch', r'D:\work\架构文档'),
]
OUT = Path(r'D:\work\tools\lab\checkmsg\samples.json')

# diff 截断参数：3B 上下文有限
MAX_FILES = 6
MAX_LINES_PER_FILE = 12
MAX_TOTAL_CHARS = 3000


def run(args, cwd):
    # core.quotePath=false：否则中文文件名会变成 \346\216 这样的八进制转义，人机都读不懂
    r = subprocess.run([GIT, '-c', 'core.quotePath=false', '-C', cwd] + args,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.stdout


def collect():
    """收集所有提交的 (sha, subject, diff摘要)。"""
    commits = []
    for repo, path in REPOS:
        log = run(['log', '--all', '--pretty=%H%x1f%s%x1f%ad', '--date=short'], path)
        for line in log.splitlines():
            parts = line.split('\x1f')
            if len(parts) != 3:
                continue
            sha, subject, date = parts
            commits.append({'repo': repo, 'path': path, 'sha': sha,
                            'subject': subject, 'date': date})
    return commits


def diff_summary(path, sha):
    """拿文件列表 + 每个文件前 N 行 diff。"""
    stat = run(['show', '--stat=200', '--format=', sha], path)
    files = []
    for line in stat.splitlines():
        m = re.match(r'\s*(\S.*?)\s+\|\s+(\d+)', line)
        if m:
            files.append((m.group(1).strip(), int(m.group(2))))

    patch = run(['show', '--format=', '--unified=1', sha], path)
    blocks, cur, cur_lines = [], None, 0
    for line in patch.splitlines():
        if line.startswith('diff --git'):
            if cur is not None:
                blocks.append(cur)
            cur, cur_lines = [line], 1
        elif cur is not None:
            if cur_lines < MAX_LINES_PER_FILE:
                cur.append(line)
                cur_lines += 1
    if cur is not None:
        blocks.append(cur)

    text = ''
    if files:
        text += '改动文件：\n'
        for f, n in files[:MAX_FILES]:
            text += f'  - {f}  (+/-{n} 行)\n'
        if len(files) > MAX_FILES:
            text += f'  …还有 {len(files) - MAX_FILES} 个文件\n'
        text += '\n'
    text += '\n'.join('\n'.join(b) for b in blocks[:MAX_FILES])
    if len(text) > MAX_TOTAL_CHARS:
        text = text[:MAX_TOTAL_CHARS] + '\n…（截断）'
    return text, files


def key_of(subject):
    """取出 type(scope) 作为"相近"的分组键。"""
    m = re.match(r'^(\w+)(\([^)]*\))?!?:', subject)
    if m:
        return (m.group(1), m.group(2) or '')
    return ('other', '')


print('收集提交……')
commits = collect()
print(f'  共 {len(commits)} 条')

# 只保留有实际改动的（排除 merge / 空提交）
commits = [c for c in commits if not c['subject'].startswith('Merge')]
by_key = {}
for c in commits:
    by_key.setdefault(key_of(c['subject']), []).append(c)

# 找出能"相近错配"的组（同键 ≥3 条）
good_keys = [k for k, v in by_key.items() if len(v) >= 3]
print(f'  可用于相近错配的分组：{len(good_keys)} 个')
for k in sorted(good_keys, key=lambda x: -len(by_key[x]))[:8]:
    print(f'    {k[0]}{k[1]}  ×{len(by_key[k])}')

print('\n生成样本……')
samples = []
used = set()

# ---- 正例：按仓库轮转，每个仓库最多 2 条，保证多样性 ----
repos_order = [r for r, _ in REPOS]
by_repo = {}
for c in commits:
    by_repo.setdefault(c['repo'], []).append(c)

for c in [c for r in repos_order for c in by_repo.get(r, [])]:
    if len(samples) >= 10:
        break
    if used_count := sum(1 for s in samples if s['repo'] == c['repo']):
        if used_count >= 2:
            continue
    if c['sha'] in used:
        continue
    text, files = diff_summary(c['path'], c['sha'])
    if not files or len(text) < 80:
        continue
    used.add(c['sha'])
    samples.append({
        'id': f'p{len(samples) + 1:02d}',
        'label': 'consistent',
        'repo': c['repo'],
        'sha': c['sha'][:8],
        'subject': c['subject'],
        'diff': text,
        'message': c['subject'],
        'reason': '真实提交：message 与 diff 出自同一次改动',
    })

print(f'  正例 {len(samples)} 条（仓库分布：'
      f'{", ".join(f"{r}×{sum(1 for s in samples if s["repo"] == r)}" for r in repos_order if any(s["repo"] == r for s in samples))}）')

# ---- 反例：分三档难度，各 3-4 条 ----
# 容易：换个 type 完全不同的 message（docs ↔ fix/feat）
# 中等：同 type 不同 scope
# 难：同 type 同 scope，内容不同
DIFFICULTY_PLAN = [('easy', 3), ('medium', 4), ('hard', 3)]


def pick_pair(difficulty):
    """按难度挑 (diff提交, message提交)。"""
    if difficulty == 'easy':
        # 找一个 diff 提交，和一条 type 完全不同的 message
        for c in commits:
            if c['sha'] in used:
                continue
            k1 = key_of(c['subject']) if 'key_of' in globals() else ('', '')
            for d in commits:
                if d['sha'] == c['sha'] or d['sha'] in used:
                    continue
                k2 = key_of(d['subject'])
                if k2[0] != k1[0] and k2[0] in ('docs', 'feat', 'fix', 'test', 'ci'):
                    return c, d
    elif difficulty == 'medium':
        # 同 type、不同 scope
        for c in commits:
            if c['sha'] in used:
                continue
            k1 = key_of(c['subject'])
            for d in commits:
                if d['sha'] == c['sha'] or d['sha'] in used:
                    continue
                k2 = key_of(d['subject'])
                if k2[0] == k1[0] and k2[1] != k1[1] and k2[1]:
                    return c, d
    else:
        # 同 type 同 scope，内容不同
        for k, group in by_key.items():
            fresh = [x for x in group if x['sha'] not in used]
            if len(fresh) >= 2:
                return fresh[0], fresh[1]
    return None, None


neg = 0
for difficulty, count in DIFFICULTY_PLAN:
    for _ in range(count):
        a, b = pick_pair(difficulty)
        if not a or not b:
            continue
        text, files = diff_summary(a['path'], a['sha'])
        if not files or len(text) < 80:
            used.add(a['sha'])
            continue

        # 额外校验：如果两个 message 实质相同，就跳过（错配要看得出来）
        if a['subject'].strip() == b['subject'].strip():
            used.add(a['sha'])
            continue

        used.add(a['sha'])
        neg += 1
        samples.append({
            'id': f'n{neg:02d}',
            'label': 'suspect',
            'difficulty': difficulty,
            'repo': a['repo'],
            'sha': a['sha'][:8],
            'subject': b['subject'],
            'diff': text,
            'message': b['subject'],
            'reason': f'错配（{difficulty}）：diff 实际是「{a["subject"]}」，配的 message 是「{b["subject"]}」',
        })

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')

print(f'\n写入 {OUT}')
print(f'  总计 {len(samples)} 条：一致 {sum(1 for s in samples if s["label"] == "consistent")}，'
      f'错配 {sum(1 for s in samples if s["label"] == "suspect")}')
print(f'  文件大小 {OUT.stat().st_size:,} B')

print('\n=== 抽样预览（各 2 条）===')
for s in samples[:2] + samples[10:12]:
    print(f'\n[{s["id"]}] label={s["label"]}  repo={s["repo"]}')
    print(f'  message: {s["message"]}')
    print(f'  diff 前 3 行: {s["diff"].splitlines()[:3]}')
