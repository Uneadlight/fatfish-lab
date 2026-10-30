"""RPC 客户端：一条连接多请求复用，超时/异常统一成 RemoteError。

线程安全：同一个 client 可以被多线程共享，内部用一把锁串行化
「发请求 → 收响应」。原因是没有请求 ID 匹配表时，两个线程交错收发
会把响应配错请求；简单场景串行化更省事也更不容易错。
需要真正的多路并发送时就一个线程一个 client（测试里就是这么做的）。
"""

from __future__ import annotations

import contextlib
import socket
import threading
from typing import Any

from codec.tlv import CodecError, decode, encode

from .framing import (
    MSG_HEARTBEAT,
    MSG_REQUEST,
    MSG_RESPONSE,
    FrameError,
    pack_frame,
    read_frame,
)
from .server import RemoteError

__all__ = ["RPCClient"]


class RPCClient:
    """同步 RPC 客户端。"""

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    # -- 连接管理 ---------------------------------------------------------- #
    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._sock.settimeout(self._timeout)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()

    def __enter__(self) -> RPCClient:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- 业务接口 ---------------------------------------------------------- #
    def call(self, method: str, params: dict | None = None) -> Any:
        """调用远端方法；``ok=False`` 或链路失败一律抛 :class:`RemoteError`。"""
        payload = {
            "id": self._take_id(),
            "method": method,
            "params": params or {},
        }
        with self._lock:
            self.connect()
            frame = pack_frame(MSG_REQUEST, encode(payload))
            try:
                self._sock.sendall(frame)  # type: ignore[union-attr]
                msg_type, body = read_frame(self._sock)  # type: ignore[arg-type]
            except TimeoutError as exc:
                self._broken()
                raise RemoteError(f"调用 {method} 超时（{self._timeout}s）") from exc
            except (FrameError, OSError) as exc:
                self._broken()
                raise RemoteError(f"调用 {method} 链路中断: {exc}") from exc

            if msg_type != MSG_RESPONSE:
                self._broken()
                raise RemoteError(f"期望响应帧，收到类型 {msg_type}")

            try:
                response = decode(body)
            except CodecError as exc:
                self._broken()
                raise RemoteError(f"响应解码失败: {exc}") from exc

            if not isinstance(response, dict):
                self._broken()
                raise RemoteError("响应载荷不是 dict")

            if response.get("ok") is True:
                return response.get("result")

            error = response.get("error") or {}
            etype = error.get("type", "RemoteError")
            message = error.get("message", "")
            raise RemoteError(f"[{etype}] {message}")

    def ping(self) -> bool:
        """心跳：只验证链路活着，不走业务方法表。"""
        with self._lock:
            self.connect()
            try:
                self._sock.sendall(pack_frame(MSG_HEARTBEAT, b""))  # type: ignore[union-attr]
                msg_type, body = read_frame(self._sock)  # type: ignore[arg-type]
            except TimeoutError as exc:
                self._broken()
                raise RemoteError("心跳超时") from exc
            except (FrameError, OSError) as exc:
                self._broken()
                raise RemoteError(f"心跳失败: {exc}") from exc
            if msg_type != MSG_RESPONSE:
                return False
            try:
                response = decode(body)
            except CodecError:
                return False
            return bool(isinstance(response, dict) and response.get("result") == "pong")

    # -- 内部 -------------------------------------------------------------- #
    def _take_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _broken(self) -> None:
        self.close()
