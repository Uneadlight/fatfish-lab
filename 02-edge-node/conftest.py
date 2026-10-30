"""pytest 公共配置：sys.path + 临时目录改到项目内 `.tmp/`（理由见 task2_lowlevel/conftest.py）。"""

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
