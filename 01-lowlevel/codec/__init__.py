"""手写 TLV 编解码包（零第三方依赖）。"""

from .tlv import TAG_NAMES, CodecError, decode, encode

__all__ = ["encode", "decode", "CodecError", "TAG_NAMES"]
