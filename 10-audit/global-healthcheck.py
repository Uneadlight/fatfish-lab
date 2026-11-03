# -*- coding: utf-8 -*-
"""全局自检（Global Health Check）—— 四维度体检，只读，不删任何东西。

用法：python E:\\DS公作区\\自进化\\global-healthcheck.py
输出：[OK] / [WARN] / [FAIL] 标记；非 OK 项附建议。
清理动作单独列「待确认清单」，等用户确认后走 safe_mutate。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
GIT = r"~/.dsh\profiles\desktop\node_modules\@dsh-ops\bash-win32-x64\ucrt64\bin\git.exe"
PY = sys.executable
MEM = os.path.join(HOME, ".dsh", "memory", "memories.json")
KB = r"D:\work\学习计划\01-编程\知识库"
IDX = os.path.join(KB, ".kb-index.json")
SKILL = os.path.join(HOME, ".dsh", "profiles", "desktop", "node_modules", "@local",
                     "dsh-workflow-skill", "skills", "workflow", "SKILL.md")
REPOS = [
    r"D:\work\底座实战",
    r"D:\work\Self-Opt",
    r"D:\work\学习计划\01-编程",
    r"D:\work\闭关",
]

results: list[tuple[str, str, str]] = []  # (status, item, detail)


def mark(status: str, item: str, detail: str = "") -> None:
    results.append((status, item, detail))


def run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


print("=" * 66)
print("全局自检 Global Health Check  " + time.strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 66)

# ---------- 维度 1：工作区一致性 ----------
for repo in REPOS:
    if not os.path.isdir(os.path.join(repo, ".git")):
        mark("WARN", f"git:{repo}", "不是 git 仓库")
        continue
    rc, out = run([GIT, "-C", repo, "status", "--porcelain"])
    if rc != 0:
        mark("FAIL", f"git:{repo}", f"git status 失败: {out[:120]}")
        continue
    rc2, head = run([GIT, "-C", repo, "log", "-1", "--format=%h %s"])
    if out:
        mark("FAIL", f"git:{repo}", f"工作区脏：{out.splitlines()[:3]}；HEAD={head[:80]}")
    else:
        mark("OK", f"git:{repo}", f"clean HEAD={head[:80]}")

# ---------- 维度 2：数据完整性 ----------
try:
    with open(MEM, encoding="utf-8") as fh:
        raw = json.load(fh)
    mems = raw if isinstance(raw, list) else raw.get("memories", raw.get("items", []))
    ids = [m.get("id") for m in mems]
    imp5 = [m for m in mems if m.get("importance") == 5 and not m.get("deprecated")]
    chars5 = sum(len(m.get("content", "")) for m in imp5)
    mark("OK", "memories.json", f"valid=True count={len(mems)} dup_ids={len(ids) - len(set(ids))} imp5={len(imp5)} chars5={chars5}")
    # 2026-11-01 修判据：5/5 单独没有"触发线"——真正的约束是 5/5+4/5 的总注入量（4/5 也是全注入的），
    # 拿 5/5 一个分项跟 14,000 比，等于用尺子量错的那一段。预算见 dsh-memory 的 CHAR_BUDGET。
    imp4 = [m for m in mems if m.get("importance") == 4 and not m.get("deprecated")]
    chars4 = sum(len(m.get("content", "")) for m in imp4)
    total_inject = chars5 + chars4
    budget = 60000
    mark("WARN" if total_inject > budget * 0.8 else "OK", "记忆注入量",
         f"{total_inject:,} / {budget:,} 字符（{total_inject / budget * 100:.0f}%，报警线 80%）；"
         f"其中 5/5 {len(imp5)} 条 {chars5:,}、4/5 {len(imp4)} 条 {chars4:,}")
except Exception as e:  # noqa: BLE001
    mark("FAIL", "memories.json", f"读取/解析失败: {e}")

try:
    with open(IDX, encoding="utf-8") as fh:
        idx = json.load(fh)
    disk = {os.path.basename(p) for p in glob.glob(os.path.join(KB, "*.md")) if os.path.basename(p) != "INDEX.md"}
    indexed = set(idx.get("files", []))
    missing, extra = sorted(disk - indexed), sorted(indexed - disk)
    mark("OK" if not missing and not extra else "WARN", "倒排索引对齐",
         f"disk={len(disk)} index={len(indexed)} missing={missing} extra={extra}")
except Exception as e:  # noqa: BLE001
    mark("FAIL", "倒排索引", f"读取失败: {e}")

try:
    with open(SKILL, encoding="utf-8") as fh:
        txt = fh.read()
    checks = {
        "删除清单制": "将要删除的具体清单" in txt,
        "safe_mutate": "safe_mutate" in txt,
        "网络超时": "timeoutMs" in txt and "阿里云" in txt,
        "来源隔离": "指令来源隔离" in txt or "relayed" in txt,
        "四检查点": "四个硬检查点" in txt,
    }
    bad = [k for k, v in checks.items() if not v]
    mark("OK" if not bad else "FAIL", "SKILL.md 安全红线", f"missing={bad}" if bad else "5 项在位")
except Exception as e:  # noqa: BLE001
    mark("FAIL", "SKILL.md", f"读取失败: {e}")

envfile = os.path.join(r"D:\work\学习计划\01-编程\ai", ".env")
mark("OK", ".env 模板", "不落盘：真实 Key 只走环境变量（.env 路径被安全网拦截，属预期）" if not os.path.exists(envfile) else "存在 .env（确认已在 .gitignore）")

# ---------- 维度 3：资源泄漏 ----------
locks = glob.glob(os.path.join(r"D:\work", "**", ".kb.lock"), recursive=True)
mark("OK" if not locks else "WARN", ".kb.lock 残留", str(locks) if locks else "无")

pyc = []
for root in (r"D:\work\Self-Opt", r"D:\work\底座实战", r"D:\work\自进化", KB):
    pyc += glob.glob(os.path.join(root, "**", "__pycache__"), recursive=True)
tmpdir = os.environ.get("TEMP", "")
tmp_new = []
if tmpdir and os.path.isdir(tmpdir):
    for fn in os.listdir(tmpdir):
        try:
            if time.time() - os.path.getmtime(os.path.join(tmpdir, fn)) < 86400:
                tmp_new.append(fn)
        except OSError:
            pass
mark("OK", "__pycache__", f"{len(pyc)} 个目录（清理需确认）")
mark("OK", "Temp 今日新增", f"{len(tmp_new)} 项（清理需确认）")

rc, out = run(["schtasks", "/Query", "/TN", "DSH-Auto-Learn", "/FO", "LIST"], timeout=10)
state = "DISABLED" if re.search(r"已禁用|Disabled", out, re.IGNORECASE) else ("RUNNING" if "正在运行" in out or "Running" in out else "UNKNOWN")
mark("OK", "DSH-Auto-Learn", state)

# ---------- 维度 4：环境探针 ----------
# 判据（2026-11-01 修）：以前拿当前解释器 import 判断"工具有没有装"，
# 但当前解释器是 DSH 自带的 runtime python，它本来就不该装 yaml/requests/mypy/pytest/ruff。
# 用错解释器去检查工具，结果就是永远 WARN。判据要落在"我调不调得到它"，不是"这个进程 import 得到它"。
try:
    __import__("PIL")
    mark("OK", "py:PIL", "import ok（runtime python 自带）")
except Exception as e:  # noqa: BLE001
    mark("INFO", "py:PIL", f"{type(e).__name__}: {e}")

TOOL_DIRS = [
    os.path.join(HOME, ".local", "bin"),
    r".\.venv\Scripts",
]
for tool in ("ruff", "pytest", "mypy"):
    found = shutil.which(tool)
    if not found:
        for d in TOOL_DIRS:
            for suffix in (".exe", ".cmd", ""):
                cand = os.path.join(d, tool + suffix)
                if os.path.isfile(cand):
                    found = cand
                    break
            if found:
                break
    mark("OK" if found else "INFO", f"cmd:{tool}", found or "PATH / uv tool / 项目 venv 三处都没有")


try:
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
        data = json.load(r)
    mark("OK", "Ollama", f"api OK models={len(data.get('models', []))}")
except Exception as e:  # noqa: BLE001
    mark("WARN", "Ollama", f"api down: {type(e).__name__}（明天视觉前置条件）")

# ---------- 记录对账（日志 / 账本 / git 三份记录互相对不对得上）----------
# 大多数时候是 0 差异，那是正常的——它是体检，不是报警器。
# 但如果不接进这里，它就永远不会被跑，所以「接进流程」比「跑得漂亮」重要。
RECONCILE = r"D:\work\tools\lab\reconcile.py"
if os.path.isfile(RECONCILE):
    rc, out = run([PY, RECONCILE, "--quiet"], timeout=90)
    m = re.search(r"\*\*(\d+) 处需要一句解释\*\*", out)
    if rc != 0:
        mark("WARN", "对账", f"reconcile 跑失败（exit {rc}）：{out.strip().splitlines()[-1][:120] if out.strip() else '无输出'}")
    elif m and int(m.group(1)) > 0:
        mark("WARN", "对账", f"{m.group(1)} 处记录对不上 → 跑 `lab reconcile` 看清单（不判错，只问要补哪句）")
    else:
        mark("OK", "对账", "日志 / 账本 / git 没有需要解释的差异")
else:
    mark("INFO", "对账", f"没有 {RECONCILE}，跳过")

# ---------- 完成声明的证据（治 #1 形式完成）----------
# 只查「今天」：历史日志的措辞是当时的，不回溯改口。
# 高比例无证据才是问题；少量无证据可能是描述性段落被误认，先只报 WARN。
CLAIMS = r"D:\work\tools\lab\claims.py"
if os.path.isfile(CLAIMS):
    rc, out = run([PY, CLAIMS, "--json"], timeout=120)
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else {}
    except Exception:
        data = {}
    claims = data.get("claims", 0)
    unbacked = data.get("unbacked", [])
    if claims == 0:
        mark("INFO", "完成声明", "今天还没有决策日志段，跳过（写了之后才会有对账）")
    elif not unbacked:
        mark("OK", "完成声明", f"{claims} 条全部有证据接住")
    else:
        pct = len(unbacked) / claims * 100
        first = unbacked[0]["text"][:60]
        mark("WARN", "完成声明", f"{claims} 条里 {len(unbacked)} 条没证据（{pct:.0f}%）→ 首条：{first}")
else:
    mark("INFO", "完成声明", f"没有 {CLAIMS}，跳过")

# ---------- 汇总 ----------
print()
ok = warn = info = fail = 0
for status, item, detail in results:
    print(f"[{status}] {item}  {detail}")
    if status == "OK":
        ok += 1
    elif status == "WARN":
        warn += 1
    elif status == "INFO":
        info += 1
    else:
        fail += 1
print()
print(f"summary: OK={ok} WARN={warn} INFO={info} FAIL={fail}")
