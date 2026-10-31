"""帧协议（长度前缀 + 类型字节）的粘包/半包测试。

被测接口（契约）：
    rpc.framing.MSG_REQUEST / MSG_RESPONSE / MSG_HEARTBEAT
    rpc.framing.MAX_PAYLOAD
    rpc.framing.pack_frame(msg_type: int, payload: bytes) -> bytes
    rpc.framing.recv_exact(reader, n: int) -> bytes
    rpc.framing.read_frame(reader) -> tuple[int, bytes]
    rpc.framing.FrameError

frame 布局::

    | 4B 大端 payload 长度 | 1B 消息类型 | payload |

注意：长度字段只数 payload，不含 1 字节类型——所以单帧总长 = 4 + 1 + LEN。
"""

import socket
import threading

import pytest
from rpc.framing import (
    MAX_PAYLOAD,
    MSG_HEARTBEAT,
    MSG_REQUEST,
    MSG_RESPONSE,
    FrameError,
    pack_frame,
    read_frame,
    recv_exact,
)


def _pair():
    return socket.socketpair()


def test_framing_roundtrip_basic():
    a, b = _pair()
    try:
        payload = b"hello \xe4\xb8\xad\xe6\x96\x87"
        a.sendall(pack_frame(MSG_REQUEST, payload))
        msg_type, body = read_frame(b)
        assert msg_type == MSG_REQUEST
        assert body == payload
    finally:
        a.close()
        b.close()


def test_framing_empty_payload():
    a, b = _pair()
    try:
        a.sendall(pack_frame(MSG_HEARTBEAT, b""))
        msg_type, body = read_frame(b)
        assert msg_type == MSG_HEARTBEAT
        assert body == b""
    finally:
        a.close()
        b.close()


def test_framing_byte_by_byte():
    """最坏分片：1 字节一次 send，读端必须靠 read_exact 循环拼回来。

    发送必须放在独立线程里：本测试的要点是"读端一直在读、发送端一次一个字节"，
    如果在同一个线程里先发完再读，一旦 socket 缓冲撑满就会自己把自己锁死
    （Linux CI 上就踩到了：sendall 阻塞 60s 被 pytest-timeout 抓出来）。
    """
    a, b = _pair()
    try:
        payload = bytes(range(256)) * 2
        frame = pack_frame(MSG_RESPONSE, payload)

        def drip() -> None:
            try:
                for i in range(len(frame)):
                    a.sendall(frame[i : i + 1])
            except OSError:
                pass  # 主线程断言失败时会先关 socket，这里不掩盖主线程的结论

        writer = threading.Thread(target=drip, daemon=True)
        writer.start()
        msg_type, body = read_frame(b)
        writer.join(timeout=5)
        assert (msg_type, body) == (MSG_RESPONSE, payload)
    finally:
        a.close()
        b.close()


def test_framing_coalesced_100_frames():
    """粘包：一次 sendall 塞 100 帧，读端必须按长度边界逐帧切开，不能多吞也不能少读。"""
    a, b = _pair()
    try:
        frames = [pack_frame(MSG_REQUEST, f"payload-{i}".encode()) for i in range(100)]
        a.sendall(b"".join(frames))
        got = [read_frame(b) for _ in range(100)]
        assert [p for _, p in got] == [f"payload-{i}".encode() for i in range(100)]
        assert all(t == MSG_REQUEST for t, _ in got)
    finally:
        a.close()
        b.close()


def test_frame_length_prefix_lie_is_rejected():
    """头里声明 1GB，实际没数据：必须早失败，不能阻塞等、不能预分配 1GB。"""
    a, b = _pair()
    try:
        a.sendall(b"\x40\x00\x00\x00" + bytes([MSG_REQUEST]))
        with pytest.raises(FrameError):
            read_frame(b)
    finally:
        a.close()
        b.close()


def test_frame_declared_length_equal_max_is_allowed_but_not_over():
    a, b = _pair()
    try:
        a.sendall(b"\x00\x00\x00\x00" + bytes([MSG_REQUEST]) + b"")
        assert read_frame(b) == (MSG_REQUEST, b"")
    finally:
        a.close()
        b.close()

    # 超限：MAX_PAYLOAD + 1
    over = (MAX_PAYLOAD + 1).to_bytes(4, "big") + bytes([MSG_REQUEST])
    with pytest.raises(FrameError):
        read_frame(_FakeReader(over))


def test_frame_rejects_unknown_type():
    # 手工构造：pack_frame 侧本来就拒绝非法类型，读侧也要独立拒绝（对端可能是别的实现）
    a, b = _pair()
    try:
        a.sendall(b"\x00\x00\x00\x01" + b"\x09" + b"x")
        with pytest.raises(FrameError):
            read_frame(b)
    finally:
        a.close()
        b.close()


def test_frame_eof_mid_header_raises_instead_of_hanging():
    a, b = _pair()
    try:
        a.sendall(b"\x00\x00")
        a.close()
        with pytest.raises(FrameError):
            read_frame(b)
    finally:
        b.close()


def test_frame_eof_mid_payload_raises():
    a, b = _pair()
    try:
        a.sendall(b"\x00\x00\x00\x0a" + bytes([MSG_REQUEST]) + b"12345")
        a.close()
        with pytest.raises(FrameError):
            read_frame(b)
    finally:
        b.close()


class _FakeReader:
    """按 1 字节一读的假 socket，验证 recv_exact 不假设"一次读满"。"""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def recv(self, n: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + 1]
        self._pos += 1
        return chunk


def test_recv_exact_handles_short_reads():
    reader = _FakeReader(b"abcdefghij")
    assert recv_exact(reader, 4) == b"abcd"
    assert recv_exact(reader, 6) == b"efghij"


def test_recv_exact_zero_reads_nothing():
    assert recv_exact(_FakeReader(b""), 0) == b""


def test_pack_frame_rejects_bad_input():
    with pytest.raises(FrameError):
        pack_frame(0, b"x")
    with pytest.raises(FrameError):
        pack_frame(MSG_REQUEST, b"x" * (MAX_PAYLOAD + 1))


def test_frame_read_via_fake_reader_byte_stream():
    """同一条字节流里连读 3 帧（假 reader 逐字节喂），验证状态不会串。"""
    stream = (
        pack_frame(MSG_REQUEST, b"a")
        + pack_frame(MSG_RESPONSE, b"" )
        + pack_frame(MSG_HEARTBEAT, b"zz")
    )
    reader = _FakeReader(stream)
    assert read_frame(reader) == (MSG_REQUEST, b"a")
    assert read_frame(reader) == (MSG_RESPONSE, b"")
    assert read_frame(reader) == (MSG_HEARTBEAT, b"zz")
