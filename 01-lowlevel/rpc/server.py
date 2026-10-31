"""RPC 服务端：每连接一线程 + 方法表分发 + 故障隔离。

协议（应用层载荷用 codec.tlv）
------------------------------
request  = ``{"id": int, "method": str, "params": dict}``
response = ``{"id": int, "ok": True,  "result": Any}``
         | ``{"id": int, "ok": False, "error": {"type": str, "message": str}}``

设计取舍
--------
* **每连接一线程**：50 并发规模下线程成本可忽略，代码比 selectors 少一半，
  也避免"一个慢请求堵住事件循环"的坑。真要上万连接再上 asyncio/selectors。
* **方法表分发**：`methods` 是普通 dict，不做反射/装饰器魔法——调用边界看得见。
* **故障隔离**：任何 handler 抛异常都只变成一条 ``ok=False`` 响应，
  连接继续用；帧层坏掉才断连接。业务异常不许传染给传输层。
* **stats 只做只读快照**：并发下用锁包住计数，避免读到半个状态。
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Callable
from typing import Any

from codec.tlv import CodecError, decode, encode

from .framing import (
    MSG_HEARTBEAT,
    MSG_RESPONSE,
    FrameError,
    pack_frame,
    read_frame,
)

__all__ = ["RPCServer", "RemoteError", "ProtocolError"]


class RemoteError(Exception):
    """远端返回 ``ok=False``，或链路层超时/中断。"""


class ProtocolError(Exception):
    """请求载荷结构不合法（不是 dict、缺 method、params 不是 dict 等）。"""


class RPCServer:
    """最小可用 RPC 服务端。

    >>> srv = RPCServer({"add": lambda p: p["a"] + p["b"]})
    >>> srv.start()
    >>> srv.port  # 随机端口（绑定 port=0 时）
    """

    def __init__(
        self,
        methods: dict[str, Callable[[dict], Any]],
        host: str = "127.0.0.1",
        port: int = 0,
        backlog: int = 128,
        conn_timeout: float = 300.0,
    ) -> None:
        if not isinstance(methods, dict) or not methods:
            raise ValueError("methods 必须是非空 dict[str, callable]")
        for name, fn in methods.items():
            if not isinstance(name, str) or not callable(fn):
                raise ValueError(f"methods 非法条目: {name!r}")
        self._methods = dict(methods)
        self._host = host
        self._requested_port = port
        self._backlog = backlog
        self._conn_timeout = conn_timeout

        self._sock: socket.socket | None = None
        self._port: int | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._conns: set[socket.socket] = set()
        self._conns_lock = threading.Lock()

        self._stats_lock = threading.Lock()
        self._stats = {"connections": 0, "requests": 0, "errors": 0, "active": 0}

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self) -> None:
        """绑定端口并开始 accept（幂等：已启动则直接返回）。"""
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._requested_port))
        sock.listen(self._backlog)
        self._sock = sock
        self._port = sock.getsockname()[1]
        self._stop.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="rpc-accept", daemon=True
        )
        self._accept_thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """停止 accept、断开所有连接、等线程退出。可重复调用。"""
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            # 先 shutdown 再 close：只 close 时阻塞在 accept() 里的线程不会被唤醒，
            # 监听 socket 的端口释放时机就变得不可预期（Linux CI 上实测：shutdown()
            # 之后紧接着 bind 同一端口会拿到 EADDRINUSE；Windows 的 SO_REUSEADDR
            # 语义宽松，所以本地测不出来）。
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                conn.close()
        thread, self._accept_thread = self._accept_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        # 端口已释放，允许 restart 时重新绑定随机端口
        self._port = None

    # -- 只读属性 ---------------------------------------------------------- #
    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("服务端未启动")
        return self._port

    @property
    def address(self) -> tuple[str, int]:
        return self._host, self.port

    @property
    def stats(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def _bump(self, key: str, delta: int = 1) -> None:
        with self._stats_lock:
            self._stats[key] += delta

    # -- 内部 -------------------------------------------------------------- #
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                conn, _addr = sock.accept()
            except OSError:
                return  # 监听 socket 被 shutdown 关掉
            with self._conns_lock:
                self._conns.add(conn)
            self._bump("connections")
            self._bump("active")
            threading.Thread(
                target=self._serve_conn,
                args=(conn,),
                name="rpc-conn",
                daemon=True,
            ).start()

    def _serve_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(self._conn_timeout)
            while not self._stop.is_set():
                try:
                    msg_type, payload = read_frame(conn)
                except FrameError:
                    # 对端关闭 / 半包后断开 / 坏帧：安静结束这条连接
                    break
                except OSError:
                    break
                if msg_type == MSG_HEARTBEAT:
                    response: dict[str, Any] = {"id": 0, "ok": True, "result": "pong"}
                else:
                    response = self._dispatch(payload)
                try:
                    conn.sendall(pack_frame(MSG_RESPONSE, encode(response)))
                except (OSError, CodecError):
                    break
        finally:
            with self._conns_lock:
                self._conns.discard(conn)
            self._bump("active", -1)
            with contextlib.suppress(OSError):
                conn.close()

    def _dispatch(self, payload: bytes) -> dict[str, Any]:
        try:
            request = decode(payload)
        except CodecError as exc:
            self._bump("errors")
            return {"id": 0, "ok": False, "error": {"type": "CodecError", "message": str(exc)}}

        if not isinstance(request, dict):
            self._bump("errors")
            return {
                "id": 0,
                "ok": False,
                "error": {"type": "ProtocolError", "message": "请求载荷必须是 dict"},
            }

        req_id = request.get("id", 0)
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str):
            self._bump("errors")
            return {
                "id": req_id,
                "ok": False,
                "error": {"type": "ProtocolError", "message": "缺少 method 字段"},
            }
        if params is None:
            params = {}
        if not isinstance(params, dict):
            self._bump("errors")
            return {
                "id": req_id,
                "ok": False,
                "error": {"type": "ProtocolError", "message": "params 必须是 dict"},
            }

        fn = self._methods.get(method)
        if fn is None:
            self._bump("errors")
            return {
                "id": req_id,
                "ok": False,
                "error": {"type": "UnknownMethod", "message": f"未知方法: {method}"},
            }

        self._bump("requests")
        try:
            result = fn(params)
        except Exception as exc:  # noqa: BLE001 - 业务异常必须转成响应，不能掀翻连接
            self._bump("errors")
            return {
                "id": req_id,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

        try:
            encode({"id": req_id, "ok": True, "result": result})
        except CodecError as exc:
            self._bump("errors")
            return {
                "id": req_id,
                "ok": False,
                "error": {"type": "CodecError", "message": str(exc)},
            }
        return {"id": req_id, "ok": True, "result": result}
