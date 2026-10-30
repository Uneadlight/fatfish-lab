"""pytest 公共配置。

两件"本机特色"必须在这里压住，否则每跑一次测试都会在仓库里留垃圾：

1. `pytest-of-<user>/` 是 pytest 自己的临时目录（`tmp_path` 默认落 cwd 下），
   里面的 `test_*.py` 是测试写出来的"题目文件"，不能被外层 pytest 再收集一遍，
   否则外跑会把内跑的失败当成自己的失败（实测踩到）。
2. 本机系统 Temp 目录对 Python 进程"能建目录、建文件卡死"，所以把 TMP/TEMP
   指到项目内 `.tmp/`（gitignore），pytest 的 tmp_path 也就跟着落在那儿。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

collect_ignore_glob = ["pytest-of-*", "**/pytest-of-*", ".tmp"]

_TMP = Path(__file__).resolve().parent / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
for _key in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_key] = str(_TMP)
# 关键：pytest 在自己启动早期就算过一遍 gettempdir()，结果被缓存在 tempfile.tempdir 里，
# 只改环境变量不够，必须把这个缓存也指过来（否则 tmp_path 仍旧落在仓库根目录）。
tempfile.tempdir = str(_TMP)
