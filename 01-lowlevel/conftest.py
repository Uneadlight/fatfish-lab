"""pytest 公共配置：把临时目录从系统 Temp 挪到项目内 `.tmp/`。

本机 `%LOCALAPPDATA%\Temp` 对 Python 进程是"能建目录、建文件卡死"的
状态（`tempfile.mkstemp()` 进去就挂住），`gettempdir()` 会回落到 cwd，于是 pytest 的
`tmp_path` 把 `pytest-of-<user>/` 建进仓库。这里三处一起改：
环境变量 + `tempfile.tempdir` 缓存（pytest 启动早期已经算过一次）。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

_TMP = pathlib.Path(__file__).resolve().parent / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
for _key in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_key] = str(_TMP)
tempfile.tempdir = str(_TMP)

collect_ignore_glob = ["pytest-of-*", "**/pytest-of-*"]
