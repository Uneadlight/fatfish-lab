"""手写 RPC 层（帧协议 + TLV 编解码 + 线程化服务端）。"""

from .framing import (
    MAX_PAYLOAD,
    MSG_HEARTBEAT,
    MSG_REQUEST,
    MSG_RESPONSE,
    FrameError,
    pack_frame,
    read_frame,
    recv_exact,
)

__all__ = [
    "MAX_PAYLOAD",
    "MSG_HEARTBEAT",
    "MSG_REQUEST",
    "MSG_RESPONSE",
    "FrameError",
    "pack_frame",
    "read_frame",
    "recv_exact",
]
