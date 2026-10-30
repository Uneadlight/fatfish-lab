"""工作区：两个 agent 唯一共享的地方（只能通过文件交流）。

每个 run 一个独立临时目录，里面是"题目初始代码 + 后续所有改动"。
- Dev 改实现、QA 写测试，都在这里；
- orchestrator 只负责建目录、塞初稿、量差异，不替他们写代码。
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .tmpdir import default_tmp_root


class WorkspaceError(ValueError):
    pass


def _safe_rel(rel: str) -> Path:
    """只接受工作区内的相对路径。绝对路径 / `..` 一律拒绝。"""
    p = Path(rel)
    if p.is_absolute() or p.drive:
        raise WorkspaceError(f"不要绝对路径：{rel}")
    if any(part == ".." for part in p.parts):
        raise WorkspaceError(f"不要 ..：{rel}")
    return p


@dataclass
class RunWorkspace:
    root: Path
    created: list[str] = field(default_factory=list)

    # -- 构造 -------------------------------------------------------------- #
    @classmethod
    def create(cls, base: Path | None = None, prefix: str = "orch-ws-") -> RunWorkspace:
        # 不用系统 tempfile.gettempdir()：本机那份 Temp 目录建文件会卡死，见 tmpdir.py
        root = Path(tempfile.mkdtemp(prefix=prefix, dir=str(base or default_tmp_root())))
        return cls(root=root)

    # -- 路径 -------------------------------------------------------------- #
    def path(self, rel: str = ".") -> Path:
        if rel in (".", ""):
            return self.root
        return self.root / _safe_rel(rel)

    # -- 写入 / 读取 -------------------------------------------------------- #
    def write(self, rel: str, text: str) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.created.append(rel)
        return p

    def seed(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            self.write(rel, text)

    def copy_tree(self, src: Path, dest_rel: str, pattern: str = "*.py") -> list[str]:
        src = Path(src)
        if not src.exists():
            raise WorkspaceError(f"要拷的源不存在：{src}")
        out: list[str] = []
        for f in sorted(src.rglob(pattern)):
            if "__pycache__" in f.parts:
                continue
            rel = str(Path(dest_rel) / f.relative_to(src))
            self.write(rel, f.read_text(encoding="utf-8", errors="replace"))
            out.append(rel)
        return out

    def read(self, rel: str) -> str | None:
        p = self.path(rel)
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="replace")

    # -- 观察 -------------------------------------------------------------- #
    def list_files(self, suffixes: tuple[str, ...] = (".py",)) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            if p.suffix in suffixes:
                # 统一用 / 分隔：Windows 上 rglob 给的是反斜杠，快照/报告里两套写法会互相认不出
                out.append(p.relative_to(self.root).as_posix())
        return out

    def snapshot(self, suffixes: tuple[str, ...] = (".py",)) -> dict[str, str]:
        return {
            rel: hashlib.sha256((self.root / rel).read_bytes()).hexdigest()
            for rel in self.list_files(suffixes)
        }

    # -- 清理 -------------------------------------------------------------- #
    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> RunWorkspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()
