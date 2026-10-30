"""帧协议：解决 TCP「粘包 / 半包」的最小实现。

为什么需要它
------------
TCP 是**字节流**，不是消息流：发送方 `sendall` 两次，接收方可能一次 `recv`
拿到两帧拼在一起（粘包），也可能一次只拿到半帧（半包）。任何"recv 一次 = 一条消息"
的写法都会在生产环境随机丢消息/串消息——本地 loopback 小包时几乎不触发，
所以必须**故意**在测试里制造这两种情况。

解决方式就是给消息加**长度前缀**（framing）：读端先读固定 5 字节头，
知道 payload 多长，再循环读到够为止。这就是所有字节流协议
（HTTP/2、Kafka、gRPC、Redis RESP）都长这样的原因。

frame 布局::

    | 4B 大端 payload 长度 | 1B 消息类型 | payload |

长度字段只数 payload，不含类型字节：单帧总长 = 4 + 1 + LEN。
这样类型字节永远在固定偏移 4，解析时不必先猜 payload 里有没有类型。
"""

from __future__ import annotations

import struct
from typing import Protocol

__all__ = [
    "MSG_REQUEST",
    "MSG_RESPONSE",
    "MSG_HEARTBEAT",
    "MAX_PAYLOAD",
    "FrameError",
    "pack_frame",
    "recv_exact",
    "read_frame",
    "MSG_TYPES",
]

MSG_REQUEST = 1
MSG_RESPONSE = 2
MSG_HEARTBEAT = 3

MSG_TYPES = frozenset({MSG_REQUEST, MSG_RESPONSE, MSG_HEARTBEAT})

#: payload 上限 64MB。超了直接判坏帧——否则一个坏长度前缀就能让读端
#: `recv(4GB)` 预分配把内存吃掉，这是最经典的自伤式 DoS。
MAX_PAYLOAD = 64 * 1024 * 1024

_HEADER = struct.Struct(">IB")  # 4B 长度 + 1B 类型 = 5 字节
HEADER_SIZE = _HEADER.size


class FrameError(Exception):
    """帧层错误：长度非法、类型未知、对端提前关闭、帧被截断。"""


class _Reader(Protocol):
    """任何提供 recv(n) -> bytes 的对象（socket / 测试假实现）。"""

    def recv(self, n: int) -> bytes:  # pragma: no cover - 协议声明
        ...


def pack_frame(msg_type: int, payload: bytes) -> bytes:
    """把 (类型, payload) 打包成可写入字节流的完整帧。"""
    if msg_type not in MSG_TYPES:
        raise FrameError(f"未知消息类型: {msg_type!r}")
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise FrameError(f"payload 必须是 bytes，收到 {type(payload).__name__}")
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise FrameError(f"payload {len(payload)} 字节超过上限 {MAX_PAYLOAD}")
    return _HEADER.pack(len(payload), msg_type) + payload


def recv_exact(reader: _Reader, n: int) -> bytes:
    """从 reader 精确读 n 字节；读不满就对端已关闭，抛 FrameError。

    `recv` 返回的可能是 1 字节也可能是 n 字节，**不能假设一次读满**。
    """
    if n < 0:
        raise FrameError(f"要读的字节数不能为负: {n}")
    if n == 0:
        return b""
    chunks = []
    remaining = n
    while remaining:
        chunk = reader.recv(remaining)
        if not chunk:
            raise FrameError(f"对端提前关闭：还差 {remaining}/{n} 字节")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(reader: _Reader) -> tuple[int, bytes]:
    """读一帧，返回 (msg_type, payload)。对端正常关闭时抛 FrameError。"""
    header = recv_exact(reader, HEADER_SIZE)
    length, msg_type = _HEADER.unpack(header)
    if msg_type not in MSG_TYPES:
        raise FrameError(f"未知消息类型: {msg_type!r}")
    if length > MAX_PAYLOAD:
        raise FrameError(f"声明 payload {length} 字节，超过上限 {MAX_PAYLOAD}")
    payload = recv_exact(reader, length)
    return msg_type, payload
