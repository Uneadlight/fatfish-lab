"""本地 Ollama 调用封装（只用标准库 urllib，不装 ollama 的 python 包）。

护栏就装在这里：每次 generate 之前先采样一次显存，按 VramPolicy 预检，
超红线直接 VramRefused —— 让"超限拒绝"成为代码里真的会执行的一条路径，
而不是文档里的一句话。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .gpu import GpuSampler
from .policy import VramDecision, VramPolicy

__all__ = [
    "DEFAULT_HOST",
    "LocalLLMError",
    "LocalResult",
    "ModelNotPulled",
    "OllamaClient",
    "VramRefused",
]

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_KEEP_ALIVE = "60s"
DEFAULT_NUM_CTX = 2048


class LocalLLMError(RuntimeError):
    """本地模型通道不可用。"""


class VramRefused(LocalLLMError):
    """预检判定会破显存红线，拒绝起模型。"""

    def __init__(self, decision: VramDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class ModelNotPulled(LocalLLMError):
    """本地没有这个模型。"""


@dataclass(frozen=True)
class LocalResult:
    model: str
    text: str
    prompt_eval_count: int
    eval_count: int
    eval_duration_ns: int
    total_duration_ns: int
    wall_s: float

    @property
    def tokens_per_sec(self) -> float:
        if self.eval_duration_ns <= 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)

    def as_row(self) -> str:
        return (
            f"{self.model} out={self.eval_count} tok "
            f"in={self.prompt_eval_count} tok "
            f"{self.tokens_per_sec:.1f} tok/s "
            f"wall={self.wall_s:.2f}s"
        )


class OllamaClient:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        policy: VramPolicy | None = None,
        sampler: GpuSampler | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.policy = policy
        self.sampler = sampler or GpuSampler()
        self.timeout = timeout

    # -- 底层 -------------------------------------------------------------- #
    def _get(self, path: str, timeout: float | None = None) -> dict:
        url = f"{self.host}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout or 5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LocalLLMError(
                f"连不上 Ollama（{url}）：{exc}。先 `ollama serve` 或启动桌面端。"
            ) from exc

    def _post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LocalLLMError(f"请求 Ollama 失败（{url}）：{exc}") from exc

    # -- 查询 -------------------------------------------------------------- #
    def version(self) -> str:
        return str(self._get("/api/version").get("version", "unknown"))

    def models(self) -> list[str]:
        data = self._get("/api/tags")
        return [m.get("name", "") for m in data.get("models", [])]

    def ps(self) -> list[dict]:
        return list(self._get("/api/ps").get("models", []))

    def model_loaded_mib(self, model: str) -> int:
        """该模型当前驻留的显存（MiB）；没驻留返回 0。

        预检要用它，否则暖机时会重复计算自身占用、把命中判成超线。
        查不到（Ollama 挂了）就按 0 处理 —— 预检本来就 fail-closed，宁可多算不冒险。
        """
        try:
            entries = self.ps()
        except LocalLLMError:
            return 0
        for entry in entries:
            name = str(entry.get("name", ""))
            if name == model or name.split(":")[0] == model.split(":")[0]:
                return int(entry.get("size_vram", 0)) // (1024 * 1024)
        return 0

    # -- 推理 -------------------------------------------------------------- #
    def generate(
        self,
        prompt: str,
        model: str = "qwen2.5:3b",
        *,
        num_ctx: int = DEFAULT_NUM_CTX,
        temperature: float = 0.2,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        check_vram: bool = True,
    ) -> LocalResult:
        if check_vram and self.policy is not None:
            sample = self.sampler.sample()
            decision = self.policy.check(
                model, sample.used_mib, already_loaded_mib=self.model_loaded_mib(model)
            )
            if not decision.allowed:
                raise VramRefused(decision)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature},
        }
        started = time.monotonic()
        data = self._post("/api/generate", payload)
        wall = time.monotonic() - started

        if data.get("error"):
            msg = str(data["error"])
            if "not found" in msg.lower():
                raise ModelNotPulled(f"本地没有模型 {model!r}：{msg}")
            raise LocalLLMError(f"Ollama 报错：{msg}")

        return LocalResult(
            model=model,
            text=str(data.get("response", "")),
            prompt_eval_count=int(data.get("prompt_eval_count", 0)),
            eval_count=int(data.get("eval_count", 0)),
            eval_duration_ns=int(data.get("eval_duration", 0)),
            total_duration_ns=int(data.get("total_duration", 0)),
            wall_s=wall,
        )

    def unload(self, model: str) -> None:
        """把模型踢出显存（keep_alive=0 是 Ollama 的官方卸载写法）。"""
        self._post(
            "/api/generate",
            {"model": model, "prompt": "", "keep_alive": 0, "stream": False},
            timeout=30.0,
        )
