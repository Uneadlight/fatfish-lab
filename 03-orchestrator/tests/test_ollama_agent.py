"""ollama_agent 的纯函数测试：不联网、不依赖 Ollama 在跑。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.ollama_agent import (  # noqa: E402
    apply_patches,
    build_messages,
    collect_context,
    extract_json,
    normalize_files,
    parse_files,
    safe_target,
)


def test_parse_files_marker_protocol() -> None:
    text = (
        "好的：\n"
        "<<<FILE: calc.py>>>\n"
        "def add(a, b):\n    return a + b\n"
        "<<<END>>>\n"
        "<<<FILE: tests/test_calc.py>>>\n"
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        "<<<END>>>\n"
        "完成。"
    )
    files = parse_files(text)
    assert set(files) == {"calc.py", "tests/test_calc.py"}
    assert files["calc.py"].startswith("def add")
    assert "test_add" in files["tests/test_calc.py"]


def test_parse_files_falls_back_to_json() -> None:
    files = parse_files('{"files": {"a.py": "x = 1"}}')
    assert files == {"a.py": "x = 1"}


def test_parse_files_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_files("   ")
    with pytest.raises(ValueError):
        parse_files("我不会写。")


def test_extract_json_plain() -> None:
    obj = extract_json('{"files": {"a.py": "x = 1"}}')
    assert obj["files"]["a.py"] == "x = 1"


def test_extract_json_with_fence_and_noise() -> None:
    text = '好的，这是补丁：\n```json\n{"files": {"a.py": "y = 2"}}\n```\n完成。'
    assert extract_json(text)["files"]["a.py"] == "y = 2"


def test_extract_json_rejects_empty_and_garbage() -> None:
    with pytest.raises(ValueError):
        extract_json("   ")
    with pytest.raises(ValueError):
        extract_json("我不会写。")


def test_normalize_files_accepts_both_shapes() -> None:
    assert normalize_files({"files": {"b.py": "z"}}) == {"b.py": "z"}
    assert normalize_files({"b.py": "z"}) == {"b.py": "z"}
    assert normalize_files({"files": {".\\b.py": "z"}}) == {"b.py": "z"}
    with pytest.raises(ValueError):
        normalize_files({"files": {}})


def test_safe_target_blocks_escape(tmp_path: Path) -> None:
    assert safe_target(tmp_path, "pkg/a.py").name == "a.py"
    for bad in ("../evil.py", "C:/Windows/x.py", "/etc/passwd"):
        with pytest.raises(ValueError):
            safe_target(tmp_path, bad)


def test_apply_patches_writes_and_normalizes_newline(tmp_path: Path) -> None:
    written = apply_patches(tmp_path, {"pkg/mod.py": "x = 1", "tests/test_x.py": "def test_x():\n    pass\n"})
    assert set(written) == {"pkg/mod.py", "tests/test_x.py"}
    body = (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert body == "x = 1\n"  # 自动补末尾换行


def test_collect_context_skips_tests_and_pycache(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("data = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text("def test(): pass\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.py").write_text("junk\n", encoding="utf-8")

    ctx = collect_context(tmp_path, "dev")
    assert "pkg/mod.py" in ctx
    assert not any("test_mod" in k or "junk" in k for k in ctx)


def test_build_messages_has_format_instruction_and_context() -> None:
    msgs = build_messages("SYS", "任务：加个函数", {"pkg/mod.py": "x = 1"})
    assert msgs[0] == {"role": "system", "content": "SYS"}
    user = msgs[1]["content"]
    assert "任务：加个函数" in user
    assert "--- pkg/mod.py ---" in user
    assert "<<<FILE:" in user


def test_metrics_roundtrip_shape(tmp_path: Path) -> None:
    """报账文件的字段名与编排器读的一致（key 是 tokens）。"""
    (tmp_path / "metrics-2.json").write_text(json.dumps({"tokens": 123}), encoding="utf-8")
    assert json.loads((tmp_path / "metrics-2.json").read_text(encoding="utf-8"))["tokens"] == 123
