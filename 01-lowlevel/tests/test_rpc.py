"""RPC 服务端/客户端：方法分发、并发、大包、半包断开。

被测接口（契约）：
    rpc.server.RPCServer(methods: dict[str, Callable[[dict], Any]])
        .start() -> None            # 绑定 127.0.0.1 随机端口并开始 accept
        .port -> int
        .address -> tuple[str, int]
        .stats -> dict             # 至少含 connections / requests / errors
        .shutdown(timeout: float = 5.0) -> None
    rpc.server.RemoteError          # 远端业务异常（ok=False）
    rpc.client.RPCClient(host, port, timeout: float = 5.0)
        .call(method: str, params: dict | None = None) -> Any
        .ping() -> bool
        .close() -> None
        .connect() -> None

payload 用 codec.tlv 编解码：
    request  = {"id": int, "method": str, "params": dict}
    response = {"id": int, "ok": True,  "result": Any}
             | {"id": int, "ok": False, "error": {"type": str, "message": str}}
"""

import socket
import threading
import time

import pytest
from rpc.client import RPCClient
from rpc.server import RemoteError, RPCServer


def _make_server():
    methods = {
        "add": lambda p: p["a"] + p["b"],
        "echo": lambda p: p,
        "boom": lambda p: (_ for _ in ()).throw(ValueError("故意炸给你看")),
        "sleep": lambda p: time.sleep(p.get("t", 0.01)) or "done",
        "big": lambda p: b"z" * (10 * 1024 * 1024),
        "slow_count": lambda p: len(p["items"]),
    }
    srv = RPCServer(methods)
    srv.start()
    return srv


@pytest.fixture()
def server():
    srv = _make_server()
    try:
        yield srv
    finally:
        srv.shutdown()


def test_rpc_call_roundtrip(server):
    c = RPCClient("127.0.0.1", server.port)
    try:
        assert c.call("add", {"a": 2, "b": 3}) == 5
        assert c.call("echo", {"x": [1, 2, {"中文": "值"}]}) == {"x": [1, 2, {"中文": "值"}]}
    finally:
        c.close()


def test_rpc_unknown_method_raises_remote_error(server):
    c = RPCClient("127.0.0.1", server.port)
    try:
        with pytest.raises(RemoteError):
            c.call("no_such_method", {})
    finally:
        c.close()


def test_rpc_handler_exception_becomes_remote_error(server):
    c = RPCClient("127.0.0.1", server.port)
    try:
        with pytest.raises(RemoteError) as ei:
            c.call("boom", {})
        assert "故意炸给你看" in str(ei.value)
    finally:
        c.close()


def test_rpc_server_survives_handler_exception(server):
    """一个方法炸了不能把服务端带走，后续请求照常。"""
    c = RPCClient("127.0.0.1", server.port)
    try:
        with pytest.raises(RemoteError):
            c.call("boom", {})
        assert c.call("add", {"a": 1, "b": 1}) == 2
    finally:
        c.close()


def test_rpc_big_payload_10mb(server):
    c = RPCClient("127.0.0.1", server.port, timeout=30.0)
    try:
        data = c.call("big", {})
        assert isinstance(data, (bytes, bytearray)), f"期望 bytes，收到 {type(data).__name__}"
        assert len(data) == 10 * 1024 * 1024
    finally:
        c.close()


def test_rpc_ping(server):
    c = RPCClient("127.0.0.1", server.port)
    try:
        assert c.ping() is True
    finally:
        c.close()


def test_rpc_concurrent_50_connections(server):
    """50 个连接并发各发 5 次请求，全部必须成功且结果正确。"""
    errors = []
    results = []
    lock = threading.Lock()

    def worker(idx):
        try:
            c = RPCClient("127.0.0.1", server.port, timeout=20.0)
            try:
                local = []
                for j in range(5):
                    local.append(c.call("add", {"a": idx, "b": j}))
                with lock:
                    results.append((idx, local))
            finally:
                c.close()
        except Exception as exc:  # noqa: BLE001 - 测试要看到任何异常
            with lock:
                errors.append(f"{idx}: {exc!r}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"并发请求出错: {errors[:5]}（共 {len(errors)} 个）"
    assert len(results) == 50
    for idx, local in results:
        assert local == [idx + j for j in range(5)]

    stats = server.stats
    assert stats["requests"] >= 250
    assert stats["connections"] >= 50


def test_rpc_half_close_does_not_kill_server(server):
    """客户端发半帧就断开：服务端必须丢弃该连接、不空转、不影响其他人。"""
    s = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    s.sendall(b"\x00\x00\x00\x64" + bytes([1]) + b"only-a-few")
    s.close()
    time.sleep(0.2)

    c = RPCClient("127.0.0.1", server.port)
    try:
        assert c.call("add", {"a": 7, "b": 8}) == 15
    finally:
        c.close()


def test_rpc_client_reuses_connection(server):
    c = RPCClient("127.0.0.1", server.port)
    try:
        before = server.stats["connections"]
        for i in range(5):
            assert c.call("add", {"a": i, "b": 0}) == i
        after = server.stats["connections"]
        assert after - before <= 1, "同一 client 多次调用不应反复建连"
    finally:
        c.close()


def test_rpc_shutdown_releases_port(server):
    port = server.port
    server.shutdown()
    # 端口应可重新绑定
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.close()
    # 重新 start 以便 fixture 的 shutdown 不报错
    server.start()
