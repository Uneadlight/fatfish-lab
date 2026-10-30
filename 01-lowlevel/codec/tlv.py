"""手写 TLV 序列化（纯标准库，禁用 pickle / json）。

设计（契约）
------------
字节布局::

    | TAG (1B) | PAYLOAD |

TAG 与 PAYLOAD::

    0x00 NULL      payload 空
    0x01 FALSE     payload 空
    0x02 TRUE      payload 空
    0x03 INT       zigzag + LEB128 无符号变长（支持任意精度，含负数/超 64 位）
    0x04 FLOAT     IEEE754 float64，big-endian，固定 8 字节
    0x05 BYTES     UVARINT 字节长度 + 原始字节
    0x06 STR       UVARINT **UTF-8 字节长度** + UTF-8 字节
    0x07 LIST      UVARINT 元素个数 + 逐个元素
    0x08 DICT      UVARINT 键值对数 + (键, 值) 交替

为什么这么设计（不是抄 JSON 而是按"机器对机器"重做）：

* **长度前缀**而不是分隔符 —— 二进制内容里 `\0`、`\n`、引号随便出现，
  只有显式长度才能 O(1) 跳过，也让粘包/半包的 `read_exact` 有确定边界。
* **变长整数（LEB128）** —— 小整数 1 字节，`9999999999` 5 字节，
  比定长 8 字节省，且不会像浮点那样丢精度；zigzag 把负号搬到最低位，
  保证 `-1` 也只占 1 字节（否则补码高位全 1 会膨胀到 10 字节）。
* **STR 记的是字节数不是字符数** —— 这是中文最容易踩的坑：
  "中文" 是 2 个字符、6 个字节，前缀写成 2 就会切出半个 UTF-8 序列。
* **bool 必须在 int 之前判断** —— Python 里 `True` 是 `int` 的子类，
  先判 int 会把 `True` 编成整数 `1`，解码回来布尔语义就丢了。

解码侧是"防御式"的：截断、尾随垃圾、超长长度前缀、未知 TAG、嵌套过深
一律抛 :class:`CodecError`，不返回半成品、不无限循环、不无界分配内存。
"""

from __future__ import annotations

import struct
from typing import Any

__all__ = ["encode", "decode", "CodecError", "TAG_NAMES"]


class CodecError(ValueError):
    """编解码失败（截断 / 非法 TAG / 尾随垃圾 / 超限 / 不可编码类型）。"""


TAG_NULL = 0x00
TAG_FALSE = 0x01
TAG_TRUE = 0x02
TAG_INT = 0x03
TAG_FLOAT = 0x04
TAG_BYTES = 0x05
TAG_STR = 0x06
TAG_LIST = 0x07
TAG_DICT = 0x08

TAG_NAMES = {
    TAG_NULL: "NULL",
    TAG_FALSE: "FALSE",
    TAG_TRUE: "TRUE",
    TAG_INT: "INT",
    TAG_FLOAT: "FLOAT",
    TAG_BYTES: "BYTES",
    TAG_STR: "STR",
    TAG_LIST: "LIST",
    TAG_DICT: "DICT",
}

#: 单个 item（字符串/字节串/容器总长）的硬上限，防"长度前缀撒谎"导致无界分配。
MAX_ITEM_BYTES = 64 * 1024 * 1024

#: 嵌套深度上限，防恶意构造的深层嵌套把递归栈打爆。
MAX_DEPTH = 64

_FLOAT = struct.Struct(">d")


# --------------------------------------------------------------------------- #
# 变长整数
# --------------------------------------------------------------------------- #
def _write_uvarint(buf: bytearray, value: int) -> None:
    if value < 0:
        raise CodecError("uvarint 不接受负数（负号应先 zigzag 变换）")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            buf.append(byte | 0x80)
        else:
            buf.append(byte)
            return


def _read_uvarint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    end = len(data)
    while True:
        if pos >= end:
            raise CodecError("uvarint 被截断")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 4096:
            # Python 的 int 是任意精度，理论上不设上限；但 4096 位（约 1233 位十进制）已经
            # 远超任何正常业务数字，超过它更像是"流错位"而不是真数据，直接判坏帧。
            raise CodecError("uvarint 过长（超过 4096 位）")


def _zigzag(value: int) -> int:
    """0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3 ...（负数只占最小字节数）。"""
    return value << 1 if value >= 0 else ((-value) << 1) - 1


def _unzigzag(value: int) -> int:
    return value >> 1 if not value & 1 else -((value + 1) >> 1)


# --------------------------------------------------------------------------- #
# 编码
# --------------------------------------------------------------------------- #
def encode(obj: Any) -> bytes:
    """把 Python 对象编码成 TLV 字节串。不支持的类型抛 :class:`CodecError`。"""
    buf = bytearray()
    _encode_into(obj, buf, 0)
    return bytes(buf)


def _encode_into(obj: Any, buf: bytearray, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise CodecError(f"嵌套超过 {MAX_DEPTH} 层")

    # bool 必须先于 int：bool 是 int 的子类
    if obj is None:
        buf.append(TAG_NULL)
    elif obj is True:
        buf.append(TAG_TRUE)
    elif obj is False:
        buf.append(TAG_FALSE)
    elif isinstance(obj, bool):  # numpy.bool_ 之类，保持语义正确
        buf.append(TAG_TRUE if obj else TAG_FALSE)
    elif isinstance(obj, int):
        buf.append(TAG_INT)
        _write_uvarint(buf, _zigzag(int(obj)))
    elif isinstance(obj, float):
        buf.append(TAG_FLOAT)
        buf += _FLOAT.pack(obj)
    elif isinstance(obj, (bytes, bytearray, memoryview)):
        raw = bytes(obj)
        buf.append(TAG_BYTES)
        _write_uvarint(buf, len(raw))
        buf += raw
    elif isinstance(obj, str):
        raw = obj.encode("utf-8")
        buf.append(TAG_STR)
        _write_uvarint(buf, len(raw))
        buf += raw
    elif isinstance(obj, (list, tuple)):
        buf.append(TAG_LIST)
        _write_uvarint(buf, len(obj))
        for item in obj:
            _encode_into(item, buf, depth + 1)
    elif isinstance(obj, dict):
        buf.append(TAG_DICT)
        _write_uvarint(buf, len(obj))
        for key, value in obj.items():
            _encode_into(key, buf, depth + 1)
            _encode_into(value, buf, depth + 1)
    else:
        raise CodecError(f"不支持的类型: {type(obj).__name__}")


# --------------------------------------------------------------------------- #
# 解码
# --------------------------------------------------------------------------- #
def decode(data: bytes) -> Any:
    """把 TLV 字节串解回 Python 对象；必须恰好消费完所有字节。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise CodecError(f"decode 需要 bytes，收到 {type(data).__name__}")
    view = bytes(data)
    obj, pos = _decode_at(view, 0, 0)
    if pos != len(view):
        raise CodecError(f"尾随 {len(view) - pos} 字节垃圾数据")
    return obj


def _decode_at(data: bytes, pos: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise CodecError(f"嵌套超过 {MAX_DEPTH} 层")
    if pos >= len(data):
        raise CodecError("数据被截断（缺少 TAG）")

    tag = data[pos]
    pos += 1

    if tag == TAG_NULL:
        return None, pos
    if tag == TAG_FALSE:
        return False, pos
    if tag == TAG_TRUE:
        return True, pos
    if tag == TAG_INT:
        raw, pos = _read_uvarint(data, pos)
        return _unzigzag(raw), pos
    if tag == TAG_FLOAT:
        if pos + 8 > len(data):
            raise CodecError("FLOAT 被截断（需要 8 字节）")
        (value,) = _FLOAT.unpack_from(data, pos)
        return value, pos + 8
    if tag in (TAG_BYTES, TAG_STR):
        length, pos = _read_uvarint(data, pos)
        if length > MAX_ITEM_BYTES:
            raise CodecError(f"声明长度 {length} 超过上限 {MAX_ITEM_BYTES}")
        if pos + length > len(data):
            raise CodecError(f"声明长度 {length} 但只剩 {len(data) - pos} 字节")
        raw = data[pos : pos + length]
        pos += length
        if tag == TAG_BYTES:
            return bytes(raw), pos
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError as exc:
            raise CodecError(f"字符串不是合法 UTF-8: {exc}") from exc
    if tag == TAG_LIST:
        count, pos = _read_uvarint(data, pos)
        if count > MAX_ITEM_BYTES:
            raise CodecError(f"列表声明 {count} 个元素，超过上限")
        items = []
        for _ in range(count):
            item, pos = _decode_at(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if tag == TAG_DICT:
        count, pos = _read_uvarint(data, pos)
        if count > MAX_ITEM_BYTES:
            raise CodecError(f"字典声明 {count} 个条目，超过上限")
        mapping: dict[Any, Any] = {}
        for _ in range(count):
            key, pos = _decode_at(data, pos, depth + 1)
            try:
                hash(key)
            except TypeError as exc:
                raise CodecError(f"字典键不可哈希: {type(key).__name__}") from exc
            value, pos = _decode_at(data, pos, depth + 1)
            mapping[key] = value
        return mapping, pos

    raise CodecError(f"未知 TAG 0x{tag:02x}（位置 {pos - 1}）")
