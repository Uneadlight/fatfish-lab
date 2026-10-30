# -*- coding: utf-8 -*-
"""全局自检（Global Health Check）—— 四维度体检，只读，不删任何东西。

用法：python D:\work\\自进化\\global-healthcheck.py
输出：[OK] / [WARN] / [FAIL] 标记；非 OK 项附建议。
清理动作单独列「待确认清单」，等用户确认后走 safe_mutate。
"""
from __future__ import annotations

import glob
import json
import os
import re
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
    mark("WARN" if chars5 > 14000 else "OK", "memories 5/5 字符", f"{chars5} 字符（触发线 14,000）")
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
for mod in ("PIL", "yaml", "requests", "mypy", "pytest", "ruff"):
    try:
        __import__(mod)
        mark("OK", f"py:{mod}", "import ok")
    except Exception as e:  # noqa: BLE001
        mark("WARN", f"py:{mod}", f"{type(e).__name__}: {e}")

rc, out = run([PY, "-m", "mypy", "--version"], timeout=20)
mark("OK" if rc == 0 else "WARN", "mypy", out[:80])
rc, out = run([PY, "-m", "pytest", "--version"], timeout=20)
mark("OK" if rc == 0 else "WARN", "pytest", out[:80])

try:
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
        data = json.load(r)
    mark("OK", "Ollama", f"api OK models={len(data.get('models', []))}")
except Exception as e:  # noqa: BLE001
    mark("WARN", "Ollama", f"api down: {type(e).__name__}（明天视觉前置条件）")

# ---------- 汇总 ----------
print()
ok = warn = fail = 0
for status, item, detail in results:
    print(f"[{status}] {item}  {detail}")
    if status == "OK":
        ok += 1
    elif status == "WARN":
        warn += 1
    else:
        fail += 1
print()
print(f"summary: OK={ok} WARN={warn} FAIL={fail}")
