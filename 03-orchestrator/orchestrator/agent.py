"""一个"角色"= 一个独立子进程。

隔离做法（不是靠自觉）：
- 每个角色一个**独立临时家目录**，用 `tempfile.mkdtemp()` 直接建，彼此不在同一父目录下，
  所以谁也枚举不到谁（想读对方的 prompt 连路径都猜不出来）。
- 家目录里只有：本轮 prompt、本轮日志、它自己报的 metrics。
- 共享的只有 `DSH_WORKSPACE`（工作区）——那是唯一合法的交流通道。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .tmpdir import default_tmp_root


@dataclass(frozen=True)
class AgentSpec:
    name: str
    cmd: tuple[str, ...]
    timeout_s: float = 300.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("agent 要有名字")
        if not self.cmd:
            raise ValueError(f"{self.name}: cmd 不能为空")


@dataclass
class AgentResult:
    name: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    tokens: int
    duration_s: float
    log_path: str
    home: str

    def tail(self, n: int = 1200) -> str:
        text = (self.stdout or "").strip()
        if not text and self.stderr:
            text = "[stderr] " + self.stderr.strip()
        return text if len(text) <= n else text[-n:]


class Agent:
    """把"调一次角色"封装成可测的东西：写 prompt → 起子进程 → 读日志/报账。"""

    def __init__(self, spec: AgentSpec, home: str | Path | None = None) -> None:
        self.spec = spec
        self._own_home = home is None
        if home is None:
            # 自家目录放编排器的临时根（不用系统 Temp：本机那份建文件会卡死，见 tmpdir.py）
            self.home = Path(tempfile.mkdtemp(prefix=f"orch-{spec.name}-", dir=str(default_tmp_root())))
        else:
            self.home = Path(home)
            self.home.mkdir(parents=True, exist_ok=True)

    # -- 文件约定 ---------------------------------------------------------- #
    def prompt_path(self, round_no: int) -> Path:
        return self.home / f"prompt-{round_no}.txt"

    def log_path(self, round_no: int) -> Path:
        return self.home / f"log-{round_no}.txt"

    def metrics_path(self, round_no: int) -> Path:
        return self.home / f"metrics-{round_no}.json"

    # -- 运行 -------------------------------------------------------------- #
    def run(self, prompt: str, workspace: str | Path, round_no: int) -> AgentResult:
        pfile = self.prompt_path(round_no)
        pfile.write_text(prompt, encoding="utf-8")
        env = {
            **os.environ,
            "DSH_AGENT_NAME": self.spec.name,
            "DSH_AGENT_HOME": str(self.home),
            "DSH_WORKSPACE": str(workspace),
            "DSH_ROUND": str(round_no),
            "DSH_PROMPT_FILE": str(pfile),
            "PYTHONIOENCODING": "utf-8",
        }
        started = time.monotonic()
        try:
            proc = subprocess.run(
                list(self.spec.cmd),
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.spec.timeout_s,
                env=env,
            )
            rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            rc = -9
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            err = f"超时 {self.spec.timeout_s:.0f}s 被杀"
        duration = round(time.monotonic() - started, 3)

        self.log_path(round_no).write_text(
            f"# {self.spec.name} · round {round_no}\n## cmd\n{' '.join(self.spec.cmd)}\n"
            f"## rc\n{rc}\n## stdout\n{out}\n## stderr\n{err}\n",
            encoding="utf-8",
        )
        return AgentResult(
            name=self.spec.name,
            ok=rc == 0,
            returncode=rc,
            stdout=out,
            stderr=err,
            tokens=self._read_tokens(round_no),
            duration_s=duration,
            log_path=str(self.log_path(round_no)),
            home=str(self.home),
        )

    def _read_tokens(self, round_no: int) -> int:
        """角色自己报账（`metrics-<n>.json` 里 `{"tokens": N}`）；没报记 0，不猜。"""
        p = self.metrics_path(round_no)
        if not p.is_file():
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        try:
            return max(0, int(data.get("tokens", 0)))
        except (TypeError, ValueError):
            return 0

    def cleanup(self) -> None:
        if self._own_home:
            import shutil

            shutil.rmtree(self.home, ignore_errors=True)
