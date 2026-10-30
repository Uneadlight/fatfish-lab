"""临时目录选择：**不用系统临时目录**。

起因（2026-10-29 实测）：本机 `%LOCALAPPDATA%\\Temp` 对
Python 进程是"能建目录、建文件会卡死"的状态，`tempfile.mkstemp()` 进去就挂住不返回
（用 `pwsh` 建目录却正常，所以一开始没往 temp 上想）。表现是：
`tempfile.gettempdir()` 回落到 cwd，pytest 的 `tmp_path` 也落进仓库里，
`__pycache__` 之外还多出 `pytest-of-<user>/`。

结论：编排器自己的临时目录一律放项目内 `.tmp/`（可删、可 gitignore），
需要换位置就设环境变量 `DSH_ORCH_TMP`。
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_KEY = "DSH_ORCH_TMP"


def default_tmp_root() -> Path:
    """返回一个确定可写的临时根目录（按需创建）。"""
    raw = os.environ.get(ENV_KEY, "").strip()
    root = Path(raw) if raw else Path(__file__).resolve().parents[1] / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root
