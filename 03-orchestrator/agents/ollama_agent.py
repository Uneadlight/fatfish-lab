"""活体 LLM 角色（Dev / QA）：走本机 Ollama，给编排器提供"真的会犯错"的对手。

为什么不用云端 API：本机 qwen2.5:3b 是**真实 LLM**，成本 0、延迟低、被 GPU 红线约束，
正好对应架构里"廉价敢死队"这个生态位。

文件协议（**刻意不用 JSON**）：3b 这种小模型写"多行文件内容塞进 JSON 字符串"必然漏转义，
实测一轮就翻车（`json.loads` 直接炸）。所以改成显式分节符号：

    <<<FILE: tests/test_calc.py>>>
    import pytest
    ...
    <<<END>>>

解析时按标记切，内容原样落盘。JSON 形式作为兼容分支保留（云端大模型更喜欢它）。

退出码：0=至少写了一个文件；2=模型没给出可用补丁；3=应用补丁失败。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"
MAX_FILE_CHARS = 6000
MAX_FILES = 6

FILE_BLOCK = re.compile(
    r"<<+FILE:\s*(?P<name>[^\n>]+?)\s*>+\s*\n?"
    r"(?P<body>.*?)\n?"
    r"(?:<<+\s*END\s*>+|^\s*END\s*$)",
    re.DOTALL | re.MULTILINE,
)

SYSTEM_DEV = """你是 Dev，负责改代码。按下面格式输出文件，不要输出任何解释。

格式（每个文件一段）：
<<<FILE: 相对路径>>>
完整文件内容
<<<END>>>

规矩：
- 相对路径相对工作区根，例如 calc.py。
- 给的是**整个文件**的完整内容，不是 diff。
- **保留原有的函数与 import，一个都不删。**
- **绝对不要写 test_ 开头的函数**，测试由 QA 负责。
- 不要输出 markdown 代码围栏，不要写解释。"""

SYSTEM_QA = """你是 QA，负责写 pytest 测试。按下面格式输出文件，不要输出任何解释。

格式（每个文件一段）：
<<<FILE: 相对路径>>>
完整文件内容
<<<END>>>

规矩：
- 只在 tests/ 下写文件，例如 tests/test_calc.py。
- **只测任务里明确写出的行为**：任务没提的行为一律不测（不要给 clamp 写除零测试、不要给 safe_div 写区间测试）。
- 测试函数**必须不带参数**：def test_xxx():  不要 self，不要 unittest.TestCase。
- 用 assert 断言，不用 self.assertEqual。
- 文件开头写 from calc import safe_div, clamp（用工作区里真实的模块名）。
- 异常用 with pytest.raises(ValueError):。
- 函数签名照任务给的写：safe_div(a, b) 只收两个参数；clamp(x, lo, hi) 收三个参数。
- 不要输出 markdown 代码围栏，不要写解释。"""


# ---------------------------------------------------------------- 纯函数（可测）


def parse_files(text: str) -> dict[str, str]:
    """从回复里切出 路径->内容；<<<FILE>>> 优先，JSON 作兼容兜底。"""
    if not text or not text.strip():
        raise ValueError("模型回复为空")
    out: dict[str, str] = {}
    for m in FILE_BLOCK.finditer(text):
        name = m.group("name").strip().replace("\\", "/").lstrip("./")
        body = m.group("body").strip("\n")
        if name:
            out[name] = body
    if out:
        return out
    return normalize_files(extract_json(text))


def extract_json(text: str) -> dict[str, Any]:
    """从模型回复里取出 JSON 对象；容忍 markdown 围栏和前后废话。"""
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("回复里既没有 <<<FILE>>> 块，也没有 JSON 对象") from None
        obj = json.loads(raw[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError(f"顶层不是对象，而是 {type(obj).__name__}")
    return obj


def normalize_files(obj: dict[str, Any]) -> dict[str, str]:
    """把 {"files": {...}} 或 {"路径": "内容"} 都规整成 dict[str, str]。"""
    files = obj.get("files", obj)
    if not isinstance(files, dict) or not files:
        raise ValueError("JSON 里没有 files 映射")
    out: dict[str, str] = {}
    for name, body in files.items():
        if not isinstance(name, str) or not isinstance(body, str):
            continue
        key = name.strip().replace("\\", "/").lstrip("./")
        if key:
            out[key] = body
    if not out:
        raise ValueError("files 里没有有效的 路径->内容 对")
    return out


def safe_target(root: Path, rel: str) -> Path:
    """把相对路径解析到 root 之内；越界一律拒绝。"""
    if Path(rel).is_absolute() or rel.startswith("/") or ":" in rel:
        raise ValueError(f"拒绝绝对路径：{rel}")
    target = (root / rel).resolve()
    base = root.resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"路径越界：{rel}")
    return target


def apply_patches(root: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for rel, body in files.items():
        target = safe_target(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = body if body.endswith("\n") else body + "\n"
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(rel)
    return written


def collect_context(root: Path, role: str) -> dict[str, str]:
    """挑几个文件塞进提示词：两个角色都要看实现（QA 要照着写测试）。"""
    skip_dirs = {"tests", ".git", "__pycache__", ".tmp", ".venv"}
    files: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        rel_parts = set(p.relative_to(root).parts)
        if rel_parts & skip_dirs:
            continue
        files.append(p)
    files = files[:MAX_FILES]
    ctx: dict[str, str] = {}
    for p in files:
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            continue
        ctx[str(p.relative_to(root)).replace("\\", "/")] = body[:MAX_FILE_CHARS]
    return ctx


def public_names(source: str) -> list[str]:
    """文件里已有的顶层函数/类名（不含下划线开头的）。用来防"改着改着把旧函数删了"。"""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not node.name.startswith("_"):
            names.append(node.name)
    return names


def build_messages(
    system: str,
    prompt: str,
    context: dict[str, str],
    keep_names: list[str] | None = None,
) -> list[dict[str, str]]:
    parts = [prompt.strip(), "", "当前文件内容："]
    for name, body in context.items():
        parts += [f"--- {name} ---", body, ""]
    if keep_names:
        parts += [
            "注意：当前实现里已有这些公开函数/类：" + "、".join(keep_names),
            "你输出的完整文件**必须仍然包含它们**（可以改内部实现，但名字一个都不许少）。",
            "",
        ]
    parts += ["现在按约定格式输出文件（<<<FILE: 路径>>> ... <<<END>>>），不要解释。"]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]


def call_ollama(
    messages: list[dict[str, str]],
    *,
    url: str = DEFAULT_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 180.0,
) -> tuple[str, int]:
    """返回 (回复文本, 用掉的 token 数)。"""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 本机 loopback
        data = json.loads(resp.read().decode("utf-8"))
    text = (data.get("message") or {}).get("content", "")
    tokens = int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0))
    return text, tokens


# ---------------------------------------------------------------- 入口


def main() -> int:
    role = os.environ.get("DSH_AGENT_NAME", "dev")
    home = Path(os.environ.get("DSH_AGENT_HOME", "."))
    ws = Path(os.environ.get("DSH_WORKSPACE", "."))
    round_no = os.environ.get("DSH_ROUND", "1")
    prompt_file = os.environ.get("DSH_PROMPT_FILE", "")
    model = os.environ.get("DSH_MODEL", DEFAULT_MODEL)
    url = os.environ.get("DSH_OLLAMA_URL", DEFAULT_URL)

    home.mkdir(parents=True, exist_ok=True)

    prompt = Path(prompt_file).read_text(encoding="utf-8") if prompt_file else "实现任务。"
    system = SYSTEM_QA if role == "qa" else SYSTEM_DEV
    context = collect_context(ws, role)
    keep = []
    if role != "qa":
        for body in context.values():
            keep.extend(public_names(body))
    messages = build_messages(system, prompt, context, keep_names=keep or None)

    try:
        text, tokens = call_ollama(messages, url=url, model=model)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[{role}] 调用 Ollama 失败：{exc}", file=sys.stderr)
        return 2

    (home / f"metrics-{round_no}.json").write_text(
        json.dumps({"tokens": tokens, "role": role, "model": model}), encoding="utf-8"
    )
    (home / f"reply-{round_no}.txt").write_text(text, encoding="utf-8")

    try:
        files = parse_files(text)
        written = apply_patches(ws, files)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"[{role}] 补丁不可用：{exc}", file=sys.stderr)
        print(f"[{role}] 原始回复前 400 字：{text[:400]}", file=sys.stderr)
        return 2

    print(f"[{role}] 写了 {len(written)} 个文件：{', '.join(written)}（tokens={tokens}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
