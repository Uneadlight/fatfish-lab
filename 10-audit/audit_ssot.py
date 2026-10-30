"""SSOT（单一事实来源）一致性审计。

用途：找出"写在记忆/文档里、但代码早已变了"的过期参数，索引里的幽灵文件、
没声明的第三方依赖、死代码候选、死链，以及崩溃残留的锁/临时文件。

设计上的三条原则：
1. **代码是真值**：参数对比一律以代码里读出来的值为准，文字只作为"声称"去比对。
   不硬编码我脑子里的数字（那正是上次翻车的来源）。
2. **只读**：本脚本不删不改任何文件，只输出 JSON + Markdown 报告。
3. **不确定就标成候选**：死代码用"定义处之外零引用"判定，可能误报（反射/字符串调用），
   所以输出叫 candidate，不叫 dead。

用法：
    python audit_ssot.py                # 控制台摘要
    python audit_ssot.py --json a.json --md a.md   # 同时落盘
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(r"D:\work")
MEMORY = Path(os.path.expandvars(r"%USERPROFILE%\.dsh\memory\memories.json"))
KB_DIR = ROOT / "学习计划" / "01-编程" / "知识库"
KB_INDEX = KB_DIR / ".kb-index.json"
OUT_DIR = ROOT / "自进化" / "audit"

EXCLUDE_DIRS = {
    "node_modules", ".venv", "venv", "site-packages", "cache", "__pycache__",
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".dsh",
    "备份", "Open Design", "models", ".data",
    "_asar_out", "_safe-mutate-backup", "edge-bill-profile",
}
# 这些目录里只有第三方/打包产物，扫了没意义还慢
EXCLUDE_PATHS = {"备份", "Open Design", "cache", "进阶-20261029\\.venv"}

# 死代码扫描要跳过测试/夹具/生成物：pytest 按命名约定收集，不是"被引用"
DEAD_CODE_SKIP_PARTS = {"tests", "test", "skeletons", "_asar_out", "_safe-mutate-backup",
                        "贵曼盲写-20261028", "费曼盲写-20261028"}
DEAD_CODE_SKIP_PREFIX = ("Test", "test_", "_")

STDLIB = set(sys.stdlib_module_names) | {"__future__"}


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
def walk_files(exts: Iterable[str], limit_bytes: int = 2_000_000) -> Iterable[Path]:
    """遍历工作区里的文本文件（跳过重量级目录）。"""
    exts = tuple(exts)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        if rel == ".":
            rel = ""
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS and os.path.join(rel, d) not in EXCLUDE_PATHS
        ]
        for fn in filenames:
            if not fn.endswith(exts):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > limit_bytes:
                    continue
            except OSError:
                continue
            yield p


def read_text(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def load_memory() -> list[dict[str, Any]]:
    if not MEMORY.exists():
        return []
    try:
        data = json.loads(MEMORY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = data.get("memories", data) if isinstance(data, dict) else data
    return [m for m in items if isinstance(m, dict)]


# --------------------------------------------------------------------------- #
# 维度一：参数漂移（代码 vs 文字）
# --------------------------------------------------------------------------- #
@dataclass
class ParamSpec:
    name: str
    code_file: str
    code_regex: str
    # 文字里出现该参数时，同一个句子/行里能抓到的数字
    text_regex: str
    text_scope: str = "all"          # memory | docs | all
    kind: int | str = "int"


PARAM_SPECS: list[ParamSpec] = [
    # CHAR_BUDGET / FOURS_MIN 是 IIFE 写法，真值在 IIFE 最后的 return 分支里
    ParamSpec("记忆注入字符预算", r"dsh-memory\lib\index.js",
              r"CHAR_BUDGET\s*=\s*\(\(\)\s*=>\s*\{[\s\S]{0,800}?:\s*(\d{4,6});",
              r"(?:总预算|注入预算|注入上限)[^\n。；]{0,6}?([\d][\d,]{3,6})"),
    ParamSpec("4/5 保底额度", r"dsh-memory\lib\index.js",
              r"FOURS_MIN_ALLOWANCE\s*=\s*\(\(\)\s*=>\s*\{[\s\S]{0,400}?:\s*(\d{4,6});",
              r"保底[^\n。；]{0,20}?([\d][\d,]{3,6})"),
    ParamSpec("4/5 摘要字数", r"dsh-memory\lib\index.js",
              r"SNIPPET_CHARS\s*=\s*([\d_]+)",
              r"摘要[^\n。；]{0,12}?([\d]{3,4})"),
    ParamSpec("env_doctor 5/5 字符上限", r"dsh-env-doctor\index.js",
              r"LIMIT_FIVE_CHARS\s*=\s*([\d_]+)",
              r"5/5[^\n。；]{0,20}?≤\s*([\d][\d,]{3,6})"),
    # "5/5 条数" 的代码值 40 是上限，文中 31/23 是当前实际条数——语义不同，不可比
    ParamSpec("env_doctor 5/5 条数上限", r"dsh-env-doctor\index.js",
              r"LIMIT_FIVES\s*=\s*([\d_]+)", r"", kind="code_only"),
    ParamSpec("GPU 温度冷却线(℃)", r"进阶-20261029\task1_local\guard\monitor.py",
              r"DEFAULT_TEMP_LIMIT_C\s*=\s*([\d.]+)",
              r"(?:冷却(?:线|阈值|上限)?[^\n。；]{0,12}|温度上限[^\n。；]{0,12})[^\d]{0,6}(\d{2})\s*[℃°]"),
    ParamSpec("显存红线比例", r"进阶-20261029\task1_local\guard\policy.py",
              r"RED_LINE_RATIO\s*=\s*([\d.]+)",
              r"红线[^\n。；]{0,20}?(\d{2})\s*%", kind="code_only"),
    ParamSpec("Cookie 清理阈值(字节)", r"tools\dsh-launcher\launch.vbs",
              r"COOKIE_LIMIT\s*=\s*([\d_]+)",
              r"(?:12\.?288|12\s*KB)[^\n]{0,20}",
              kind="literal"),
    ParamSpec("bili sidecar 端口", r"",
              r"",
              r"18787", kind="code_only"),
]

# 代码真值 → 需要逐个比对的文字来源
DOC_SOURCES = [
    ROOT / "救回手册.md",
    ROOT / "大肥鱼系统架构.md",
    ROOT / "进阶-20261029" / "RFC.md",
    ROOT / "进阶-20261029" / "PROGRESS.md",
    ROOT / "进阶-20261029" / "reports" / "Task1-本地算力护栏与ModelRouter.md",
    ROOT / "进阶-20261029" / "reports" / "Task2-B+树与RPC.md",
    ROOT / "tools" / "dsh-launcher" / "README.md",
    ROOT / "自进化" / "记忆库优化规则.md",
    ROOT / "自进化" / "迭代章程.md",
]
SKILL_DIRS = [
    Path(os.path.expandvars(r"%USERPROFILE%\.dsh\profiles\desktop\node_modules\@local\dsh-workflow-skill\skills")),
    ROOT / "dsh-workflow-skill" / "skills",
]


def extract_code_value(spec: ParamSpec) -> str | None:
    if not spec.code_file or not spec.code_regex:
        return None
    p = ROOT / spec.code_file
    if not p.exists():
        return None
    m = re.search(spec.code_regex, read_text(p))
    if not m:
        return None
    val = m.group(1) if m.re.groups >= 1 else m.group(0)
    return val.replace("_", "")


def text_corpus() -> list[tuple[str, str]]:
    """(来源名, 正文) —— 记忆 + 关键文档 + SKILL。"""
    out: list[tuple[str, str]] = []
    for i, m in enumerate(load_memory()):
        out.append((f"memory[{m.get('id', i)}]", str(m.get("content", ""))))
    for p in DOC_SOURCES:
        if p.exists():
            out.append((str(p.relative_to(ROOT)), read_text(p)))
    for d in SKILL_DIRS:
        if d.exists():
            for p in d.rglob("SKILL.md"):
                out.append((str(p), read_text(p)))
    return out


def is_current_state(src: str) -> bool:
    """判断来源是否是"当前态"文档。

    记忆、SKILL、规则手册属于当前态；日志/进度/RFC/报告天然包含历史值，
    拿它们比"过期"会制造大量误报，只能当 context 展示。
    """
    if src.startswith("memory["):
        return True
    name = src.replace("/", "\\").lower()
    return any(k in name for k in (
        "skill.md", "记忆库优化规则", "救回手册", "大肥鱼系统架构",
        "readme.md",
    ))


# 行内含这些词的，是"历史值/实测值"而不是"当前配置值"
HISTORY_MARKERS = re.compile(r"实测|历史|演进|当时|旧值|此前|曾经|原来|已作废|已改|→|->|第[一二三]次")

# 上下文里出现这些词的路径，是"将来才会存在"的前向引用（回滚目标、待生成目录），不算死链
FORWARD_MARKERS = re.compile(r"回滚|还原|待生成|之后才|会生成|还没建|尚未创建|前向|等.{0,6}跑完")


def _claim_is_current(body: str, start: int, end: int, src: str) -> bool:
    if not is_current_state(src):
        return False
    ctx = body[max(0, start - 40): end + 40]
    return not HISTORY_MARKERS.search(ctx)


def check_params(corpus: list[tuple[str, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for spec in PARAM_SPECS:
        code_val = extract_code_value(spec)
        claims: list[dict[str, Any]] = []
        if spec.text_regex and spec.kind != "code_only":
            for src, body in corpus:
                if spec.kind == "literal":
                    if re.search(spec.text_regex, body):
                        m = re.search(spec.text_regex, body)
                        claims.append({"source": src, "claim": "提到该阈值",
                                       "current": _claim_is_current(body, m.start(), m.end(), src)})
                    continue
                for m in re.finditer(spec.text_regex, body):
                    grp = 1 if m.re.groups >= 1 else 0
                    claims.append({"source": src, "claim": m.group(grp),
                                   "current": _claim_is_current(body, m.start(), m.end(), src)})
        finding: dict[str, Any] = {
            "param": spec.name,
            "code_value": code_val,
            "claims": claims[:20],
            "claim_count": len(claims),
            "kind": str(spec.kind),
        }
        if code_val is not None and spec.kind not in ("literal", "code_only"):
            norm = lambda s: s.replace(",", "").replace("_", "")  # noqa: E731
            bad = [c for c in claims if c["current"] and norm(c["claim"]) != norm(code_val)]
            finding["stale"] = bad
            finding["ok"] = not bad
        else:
            finding["stale"] = []
            finding["ok"] = None
        findings.append(finding)
    return findings


# --------------------------------------------------------------------------- #
# 维度二：倒排索引的幽灵数据
# --------------------------------------------------------------------------- #
def check_kb_index() -> dict[str, Any]:
    result: dict[str, Any] = {"index": str(KB_INDEX)}
    if not KB_INDEX.exists():
        result["error"] = "索引文件不存在"
        return result
    try:
        idx = json.loads(KB_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        result["error"] = f"索引无法解析: {e}"
        return result

    files: list[str] = list(idx.get("files", []))
    postings: dict[str, dict[str, int]] = idx.get("postings", {})
    actual = {p.name for p in KB_DIR.glob("*.md")}

    ghosts = [f for f in files if f not in actual]
    # 索引器按设计排除 INDEX.md（Self-Opt/lib/kb_index.py:56），不算漏建
    unindexed = sorted(actual - set(files) - {"INDEX.md"})
    by_design = ["INDEX.md"] if "INDEX.md" in actual else []
    bad_refs = 0
    for gram, refs in postings.items():
        for fidx in refs:
            try:
                if not (0 <= int(fidx) < len(files)):
                    bad_refs += 1
            except (TypeError, ValueError):
                bad_refs += 1

    result.update({
        "indexed_files": len(files),
        "actual_files": len(actual),
        "ghost_files": ghosts,
        "unindexed_files": unindexed,
        "excluded_by_design": by_design,
        "postings": len(postings),
        "out_of_range_refs": bad_refs,
        "has_hash": bool(idx.get("hashes") or idx.get("mtime")),
        "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(KB_INDEX.stat().st_mtime)),
    })
    return result


# --------------------------------------------------------------------------- #
# 维度三：依赖声明 / 死代码 / 死链
# --------------------------------------------------------------------------- #
PROJECT_ROOTS = [
    ROOT / "Self-Opt",
    ROOT / "进阶-20261029",
    ROOT / "底座实战",
    ROOT / "学习计划" / "01-编程",
    ROOT / "自进化",
    ROOT / "tools",
]


def declared_deps(project: Path) -> set[str]:
    names: set[str] = set()
    req = project / "requirements.txt"
    if req.exists():
        for line in read_text(req).splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            names.add(re.split(r"[<>=!~\[ ]", line)[0].lower().replace("-", "_"))
    pyproj = project / "pyproject.toml"
    if pyproj.exists():
        body = read_text(pyproj)
        for m in re.finditer(r"^\s*[\"']([A-Za-z0-9_.\-]+)[><=!~\[ ]", body, re.M):
            names.add(m.group(1).lower().replace("-", "_"))
        for m in re.finditer(r"^dependencies\s*=\s*\[(.*?)\]", body, re.S | re.M):
            for d in re.findall(r"[\"']([A-Za-z0-9_.\-]+)", m.group(1)):
                names.add(d.lower().replace("-", "_"))
    return names


# import 名 ≠ 分发名：requirements 里写"装什么"（Pillow），代码里写"import 什么"（PIL）。
# 这张表只收真正会撞上的常见对，避免审计把"已声明"误报成"未声明"。
IMPORT_DIST_ALIASES: dict[str, set[str]] = {
    "pil": {"pillow"},
    "bs4": {"beautifulsoup4"},
    "cv2": {"opencv_python", "opencv_contrib_python", "opencv_python_headless"},
    "yaml": {"pyyaml"},
    "dotenv": {"python_dotenv"},
    "sklearn": {"scikit_learn"},
    "skimage": {"scikit_image"},
    "dateutil": {"python_dateutil"},
    "docx": {"python_docx"},
    "pptx": {"python_pptx"},
    "fitz": {"pymupdf"},
    "win32api": {"pywin32"},
    "win32con": {"pywin32"},
    "win32gui": {"pywin32"},
    "crypto": {"pycryptodome", "pycrypto"},
    "jwt": {"pyjwt"},
    "serial": {"pyserial"},
    "usb": {"pyusb"},
    "magic": {"python_magic"},
    "openssl": {"pyopenssl"},
    "attr": {"attrs"},
    "google": {"protobuf"},
}


def _declared(module: str, declared: set[str]) -> bool:
    """判断某个 import 名是否已被 requirements/pyproject 声明（含分发名别名）。"""
    key = module.lower().replace("-", "_")
    if key in declared:
        return True
    return any(a.lower().replace("-", "_") in declared for a in IMPORT_DIST_ALIASES.get(key, ()))


def python_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(read_text(path))
    except (SyntaxError, ValueError):
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def check_deps() -> dict[str, Any]:
    out: dict[str, Any] = {"projects": [], "undeclared": []}
    for project in PROJECT_ROOTS:
        if not project.exists():
            continue
        py_files = [
            p for p in project.rglob("*.py")
            if not any(part in EXCLUDE_DIRS for part in p.parts)
        ]
        if not py_files:
            continue
        used: dict[str, set[str]] = {}
        for p in py_files:
            for mod in python_imports(p):
                used.setdefault(mod, set()).add(str(p.relative_to(ROOT)))
        third = {m: v for m, v in used.items() if m not in STDLIB}
        # 本地模块：项目里任何含 __init__.py 的包目录名 + 顶层 .py 文件名 + 一级子目录
        local = {p.stem for p in py_files} | {
            d.name for d in project.iterdir() if d.is_dir()
        }
        local |= {p.parent.name for p in py_files if p.name == "__init__.py"}
        third = {m: v for m, v in third.items() if m not in local}
        declared = declared_deps(project)
        missing = sorted(m for m in third if not _declared(m, declared))
        out["projects"].append({
            "project": project.name,
            "py_files": len(py_files),
            "third_party": sorted(third),
            "declared": sorted(declared),
            "undeclared": missing,
        })
        for m in missing:
            out["undeclared"].append({"project": project.name, "module": m,
                                      "used_in": sorted(third[m])[:3]})
    return out


def check_dead_code() -> dict[str, Any]:
    """只报告"非测试文件里的定义"，但引用计数要算上全部 py（含测试）。

    为什么分开：`check_invariants` 这种断言辅助函数只在 tests 里被调用，
    若把测试文件整体排除出语料，就会把它们全判成死代码。

    另外跳过：带装饰器的函数（Flask `@app.route` 这类由框架按字符串调用）、
    名字以 Test/test_/_ 开头的（pytest 收集约定）。
    """
    defs: dict[str, list[str]] = {}
    all_bodies: list[tuple[str, str]] = []
    skipped = 0
    decorated = 0
    for p in walk_files((".py",)):
        rel = str(p.relative_to(ROOT))
        body = read_text(p)
        all_bodies.append((rel, body))
        if any(part in DEAD_CODE_SKIP_PARTS for part in p.parts):
            skipped += 1
            continue
        try:
            tree = ast.parse(body)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                if name.startswith("__") or name in {"main"}:
                    continue
                if name.startswith(DEAD_CODE_SKIP_PREFIX):
                    continue
                if getattr(node, "decorator_list", None):
                    decorated += 1
                    continue          # 框架/装饰器注册的入口，不是"没人调"
                defs.setdefault(name, []).append(rel)

    candidates = []
    for name, where in defs.items():
        hits = sum(len(re.findall(rf"\b{re.escape(name)}\b", body)) for _, body in all_bodies)
        if hits <= len(where):          # 只在定义处出现
            group = "study" if any(k in w for w in where
                                   for k in ("学习计划", "休闲", "底座实战", "费曼盲写")) else "deliverable"
            candidates.append({"name": name, "defined_in": where,
                               "occurrences": hits, "group": group})
    candidates.sort(key=lambda c: (c["group"] != "deliverable", c["name"]))
    return {"candidates": candidates, "count": len(candidates),
            "deliverable_count": sum(1 for c in candidates if c["group"] == "deliverable"),
            "skipped_test_files": skipped, "skipped_decorated": decorated}


WIN_PATH_RE = re.compile(r"[EeDd]:\\[^\s\)\]\"'`，。；、）]+")
MD_LINK_RE = re.compile(r"\]\(([^)\s]+?)\)")
BACKTICK_RE = re.compile(r"`([^`\n]{2,300})`")
TEMPLATE_CHARS = set("<>*{}[]$%")
PATH_START_RE = re.compile(r"^(?:[A-Za-z]:\\|\.\\|\.\.\\)")


def _looks_like_path(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 300:
        return False
    if any(ch in TEMPLATE_CHARS for ch in s):
        return False          # <日期> / <hash> / *.md / ${VAR} 都是模板，不是真链接
    return bool(PATH_START_RE.match(s))


def _clean_span(s: str) -> str:
    """去掉反引号里附带的章节号/括号说明/省略号。"""
    s = s.strip().strip("`")
    s = re.split(r"\s+[§（(]|（|§", s)[0].strip()
    return s.rstrip("，。；、,.;:")


FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
RUNTIME_SUFFIXES = (".lock",)


def _mask_code_fences(body: str) -> str:
    """把 ``` 围栏代码块整段换成空格（保留行数）。

    代码块里是示例命令（如 `--quarantine D:\\重复图`），指向的是用户自己的目录，
    不是"本工作区的文档引用"，扫它会天天误报。
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return FENCE_RE.sub(_blank, body)


def check_dead_links() -> dict[str, Any]:
    bad: list[dict[str, str]] = []
    checked = 0
    skipped_template = 0
    skipped_runtime = 0
    skipped_context = 0
    skipped_forward = 0
    for p in walk_files((".md",)):
        body = _mask_code_fences(read_text(p))
        src = str(p.relative_to(ROOT))
        if src.startswith("自进化\\audit"):     # 报告自身含被抓取的原文路径，扫它只会自我复制
            continue
        # 只有"当前态"文档（记忆/SKILL/规则/README/架构/救回手册）的死链才算真腐化；
        # 学习笔记、周报、日志里写的是"当时的环境"，记的是历史事实，不该被要求跟着改。
        is_current = is_current_state(src)

        def _report(target: str, at: int = -1) -> None:
            nonlocal skipped_context, skipped_forward
            # 前向引用：回滚目标 / 待生成目录。它在"现在"当然不存在，但写它是有意的。
            if at >= 0 and FORWARD_MARKERS.search(body[max(0, at - 120): at + 120]):
                skipped_forward += 1
                return
            if not is_current:
                skipped_context += 1
                return
            bad.append({"source": src, "target": target})

        # 1) 反引号里的路径：允许空格（`D:\Deepseek\DeepSeek Harness.exe`）
        for m in BACKTICK_RE.finditer(body):
            span = _clean_span(m.group(1))
            if "..." in span or "…" in span:
                skipped_template += 1
                continue
            if not _looks_like_path(span):
                if any(ch in TEMPLATE_CHARS for ch in span) and PATH_START_RE.match(span):
                    skipped_template += 1
                continue
            # 锁文件是运行时才存在的（后台在跑才写），不能按"文件存在"判死
            if span.lower().endswith(RUNTIME_SUFFIXES):
                skipped_runtime += 1
                continue
            checked += 1
            if not os.path.exists(span):
                _report(span, m.start(1))
        # 2) 裸路径：正则遇到空格会截断，若存在"以它开头的真实路径"就说明是截断，跳过
        for m in WIN_PATH_RE.finditer(body):
            raw = m.group(0).rstrip(".,;:")
            if any(ch in TEMPLATE_CHARS for ch in raw):
                skipped_template += 1
                continue
            if raw.lower().endswith(RUNTIME_SUFFIXES):
                skipped_runtime += 1
                continue
            checked += 1
            if os.path.exists(raw):
                continue
            try:
                parent = os.path.dirname(raw) or raw
                base = os.path.basename(raw)
                if os.path.isdir(parent) and any(
                    n and (n.startswith(base) or base.startswith(n))
                    for n in os.listdir(parent)
                ):
                    continue      # 路径含空格被截断 / 后面粘了 " §0.5" 之类
            except OSError:
                pass
            _report(raw, m.start())
        # 3) markdown 相对链接
        for m in MD_LINK_RE.finditer(body):
            target = m.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            clean = target.split("#")[0].strip()
            if not clean or any(ch in TEMPLATE_CHARS for ch in clean):
                skipped_template += 1
                continue
            cand = (p.parent / clean.replace("\\", "/")).resolve()
            checked += 1
            if not cand.exists():
                _report(target, m.start(1))
    seen = set()
    uniq = []
    for b in bad:
        key = (b["source"], b["target"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return {
        "checked": checked,
        "broken": uniq,
        "count": len(uniq),
        "skipped_runtime": skipped_runtime,
        "skipped_context": skipped_context,
        "skipped_forward": skipped_forward,
    }


# --------------------------------------------------------------------------- #
# 维度四：锁 / 临时文件 / 僵尸进程
# --------------------------------------------------------------------------- #
JUNK_PATTERNS = ("*.lock", "*.tmp", "*-journal", "*.partial*", "~$*", "*.orig", "*.rej")


def check_junk() -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    skipped_noise = 0
    for pattern in JUNK_PATTERNS:
        for p in ROOT.rglob(pattern):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            # 项目内的 .tmp/ 是**故意的**运行时工作目录（pytest tmp_path、agent home 都往这写），
            # 不是"腐化残留"；它的清理靠各项目自己的 conftest/清理逻辑，不由审计管。
            if ".tmp" in p.parts:
                skipped_noise += 1
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            # Chromium/Edge 的 *-journal 是 SQLite 正常伴生文件，不是残留
            if pattern == "*-journal":
                skipped_noise += 1
                continue
            # uv/pip 在自己 venv 根目录写的 .lock 是安装器状态文件，不是"腐化残留"
            if p.name == ".lock" and any(part.startswith(("ocr-venv", ".venv")) or part == "venv" for part in p.parts):
                skipped_noise += 1
                continue
            found.append({
                "path": str(p.relative_to(ROOT)),
                "size": st.st_size,
                "age_days": round((time.time() - st.st_mtime) / 86400, 1),
            })
    found.sort(key=lambda f: -f["age_days"])
    return {"files": found, "count": len(found), "skipped_noise": skipped_noise}


def check_zombies() -> dict[str, Any]:
    """进程的可执行文件已不存在（典型：更新/卸载后的残留）。"""
    ps = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | "
        "Select-Object ProcessId,Name,ExecutablePath | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True, timeout=60)
        data = json.loads(proc.stdout or "[]")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        return {"error": str(e), "zombies": []}
    if isinstance(data, dict):
        data = [data]
    zombies = [
        {"pid": d.get("ProcessId"), "name": d.get("Name"), "path": d.get("ExecutablePath")}
        for d in data
        if d.get("ExecutablePath") and not os.path.exists(d["ExecutablePath"])
    ]
    return {"zombies": zombies, "count": len(zombies)}


# --------------------------------------------------------------------------- #
# 安装路径漂移：脚本里写死的绝对路径，指向已经搬走/改名的目录
# --------------------------------------------------------------------------- #
STALE_EXTS = (".ps1", ".mjs", ".js", ".cmd", ".bat", ".py")
STALE_PATH_RE = re.compile(r"\b([A-Za-z]:\\[^\s\"'`\)\]\},;:*?<>|]+)")
_STALE_BAD = set("[]{}$%`")


def _path_literal_ok(s: str) -> bool:
    """过滤掉正则片段、模板、太短/太长的东西——只留像真路径的字面量。"""
    if len(s) < 6 or len(s) > 260:
        return False
    if s.endswith("\\") or s.count("\\") < 2:
        return False
    if any(ch in _STALE_BAD for ch in s):
        return False
    if "\\.." in s or "\\\\" in s:
        return False
    return True


def _guess_drifted_root(stale: Path) -> list[str]:
    """同一个盘符下，找名字最像原路径第二段的目录（Deepseek → DeepSeek Harness）。"""
    try:
        root = Path(stale.drive + "\\")
        if not root.exists() or len(stale.parts) < 3:
            return []
        head = stale.parts[1].lower().replace(" ", "")
        if not head:
            return []
        hits: list[str] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            name = child.name.lower().replace(" ", "")
            if name == head:
                continue
            if head in name or name in head:
                hits.append(child.name)
    except OSError:
        return []
    return hits[:4]


def check_stale_paths() -> dict[str, Any]:
    """脚本里写死的绝对路径：已不存在，但同盘下有名字相近的目录 → 疑似安装目录漂移。

    只扫脚本/代码文件（不扫 .md）：文档里的旧路径是历史记录，本来就该留着。
    判据刻意保守——同盘下找不到相近目录就不报，宁可漏也不刷屏。
    """
    seen: dict[str, dict[str, Any]] = {}
    scanned = 0
    for p in walk_files(STALE_EXTS, limit_bytes=1_500_000):
        text = read_text(p)
        if ":\\" not in text:
            continue
        scanned += 1
        rel = str(p.relative_to(ROOT))
        for lineno, line in enumerate(text.splitlines(), 1):
            if ":\\" not in line:
                continue
            probe = line.lstrip()
            if probe.startswith(("#", "//", ";", "::", "*")):
                continue  # 整行注释：示例/历史路径，不算漂移
            code = line.split("#", 1)[0]
            if ":\\" not in code:
                continue
            for m in STALE_PATH_RE.finditer(code):
                lit = m.group(1).rstrip(".,;")
                if not _path_literal_ok(lit):
                    continue
                try:
                    if Path(lit).exists():
                        continue
                except (OSError, ValueError):
                    continue
                rec = seen.setdefault(lit, {"path": lit, "refs": []})
                if len(rec["refs"]) < 8:
                    rec["refs"].append({"source": rel, "line": lineno})
    items = []
    for rec in seen.values():
        guess = _guess_drifted_root(Path(rec["path"]))
        if not guess:
            continue
        rec["guess"] = guess
        items.append(rec)
    items.sort(key=lambda r: (-len(r["refs"]), r["path"]))
    return {"count": len(items), "scanned_files": scanned, "items": items}


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def build_report() -> dict[str, Any]:
    corpus = text_corpus()
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(ROOT),
        "dimensions": {
            "params": check_params(corpus),
            "kb_index": check_kb_index(),
            "deps": check_deps(),
            "dead_code": check_dead_code(),
            "dead_links": check_dead_links(),
            "junk": check_junk(),
            "zombies": check_zombies(),
            "stale_paths": check_stale_paths(),
        },
    }
    d = report["dimensions"]
    report["summary"] = {
        "stale_params": sum(1 for p in d["params"] if p.get("stale")),
        "ghost_index_files": len(d["kb_index"].get("ghost_files", [])),
        "unindexed_files": len(d["kb_index"].get("unindexed_files", [])),
        "out_of_range_refs": d["kb_index"].get("out_of_range_refs", 0),
        "undeclared_imports": len(d["deps"]["undeclared"]),
        "dead_code_candidates": d["dead_code"]["count"],
        "dead_links": d["dead_links"]["count"],
        "junk_files": d["junk"]["count"],
        "zombie_processes": d["zombies"].get("count", 0),
        "stale_paths": d["stale_paths"].get("count", 0),
    }
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    d = rep["dimensions"]
    s = rep["summary"]
    L: list[str] = []
    L.append("# 数据腐化体检报告（SSOT）")
    L.append("")
    L.append(f"- 生成时间：{rep['generated_at']}")
    L.append(f"- 扫描根目录：`{rep['root']}`")
    L.append("")
    L.append("## 摘要")
    L.append("")
    L.append("| 维度 | 数量 |")
    L.append("|---|---|")
    L.append(f"| 过期参数 | {s['stale_params']} |")
    L.append(f"| 幽灵索引文件 | {s['ghost_index_files']} |")
    L.append(f"| 未入索引文件 | {s['unindexed_files']} |")
    L.append(f"| 索引越界引用 | {s['out_of_range_refs']} |")
    L.append(f"| 未声明第三方依赖 | {s['undeclared_imports']} |")
    L.append(f"| 死代码候选 | {s['dead_code_candidates']} |")
    L.append(f"| 死链 | {s['dead_links']} |")
    L.append(f"| 锁/临时文件 | {s['junk_files']} |")
    L.append(f"| 僵尸进程 | {s['zombie_processes']} |")
    L.append(f"| 安装路径漂移 | {s['stale_paths']} |")
    L.append("")
    L.append("## 一、参数漂移")
    L.append("")
    L.append("| 参数 | 代码真值 | 文字声称 | 结论 |")
    L.append("|---|---|---|---|")
    for p in d["params"]:
        shown = [c for c in p.get("claims", []) if c.get("current")]
        tail = f"（另 {p['claim_count'] - len(shown)} 处历史/日志记录）" if p["claim_count"] > len(shown) else ""
        claims = "；".join(f"{c['claim']}" for c in shown[:4]) or "—"
        if p.get("ok") is None:
            verdict = "仅核对代码值"
        elif p.get("ok"):
            verdict = "OK"
        else:
            who = "、".join(sorted({c["source"] for c in p["stale"]}))[:60]
            verdict = f"⚠️ 与当前态文字不一致（{who}）"
        L.append(f"| {p['param']} | {p.get('code_value') or '—'} | {claims}{tail} | {verdict} |")
    L.append("")
    L.append("## 二、索引一致性")
    L.append("")
    kb = d["kb_index"]
    if "error" in kb:
        L.append(f"- 错误：{kb['error']}")
    else:
        L.append(f"- 索引文件：`{kb['index']}`（{kb['mtime']}）")
        L.append(f"- 索引 {kb['indexed_files']} 个 vs 实际 {kb['actual_files']} 个")
        L.append(f"- 幽灵（索引里有、磁盘没有）：{kb['ghost_files'] or '无'}")
        L.append(f"- 未入索引：{kb['unindexed_files'] or '无'}")
        L.append(f"- postings 越界引用：{kb['out_of_range_refs']}")
        L.append(f"- 索引是否带哈希/时间戳：{'是' if kb['has_hash'] else '否（无法检测内容漂移）'}")
    L.append("")
    L.append("## 三、依赖 / 死代码 / 死链")
    L.append("")
    for proj in d["deps"]["projects"]:
        L.append(f"- **{proj['project']}**：{proj['py_files']} 个 py，第三方 {len(proj['third_party'])} 个，"
                 f"未声明 {len(proj['undeclared'])} 个 {proj['undeclared'] or ''}")
    L.append("")
    L.append(f"死代码候选 {d['dead_code']['count']} 个：")
    for c in d["dead_code"]["candidates"][:25]:
        L.append(f"- `{c['name']}`（{', '.join(c['defined_in'][:2])}）")
    L.append("")
    L.append(f"死链 {d['dead_links']['count']} 处（共检查 {d['dead_links']['checked']}）：")
    for b in d["dead_links"]["broken"][:25]:
        L.append(f"- `{b['source']}` → `{b['target']}`")
    L.append("")
    L.append("## 四、锁 / 临时文件 / 僵尸进程")
    L.append("")
    for j in d["junk"]["files"][:25]:
        L.append(f"- `{j['path']}`（{j['size']} B，{j['age_days']} 天）")
    if not d["junk"]["files"]:
        L.append("- 无")
    L.append("")
    if d["zombies"].get("zombies"):
        for z in d["zombies"]["zombies"][:10]:
            L.append(f"- pid {z['pid']} `{z['name']}` → {z['path']}（已不存在）")
    else:
        L.append("- 僵尸进程：无")
    L.append("")
    sp = d["stale_paths"]
    L.append("## 五、安装路径漂移")
    L.append("")
    L.append(f"扫了 {sp.get('scanned_files', 0)} 个脚本文件，疑似漂移 {sp.get('count', 0)} 处。")
    L.append("")
    for it in sp.get("items", [])[:25]:
        refs = "、".join(f"{r['source']}:{r['line']}" for r in it["refs"][:3])
        L.append(f"- `{it['path']}`")
        L.append(f"  - 疑似已搬到：{it['guess']}")
        L.append(f"  - 引用：{refs}")
    if not sp.get("items"):
        L.append("- 无")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    rep = build_report()
    elapsed = time.time() - t0

    if not args.quiet:
        print(f"审计完成，耗时 {elapsed:.1f}s")
        for k, v in rep["summary"].items():
            print(f"  {k:24} {v}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = Path(args.json) if args.json else OUT_DIR / f"ssot-{stamp}.json"
    md_path = Path(args.md) if args.md else OUT_DIR / f"ssot-{stamp}.md"
    json_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(rep), encoding="utf-8")
    if not args.quiet:
        print(f"  JSON: {json_path}")
        print(f"  MD  : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
