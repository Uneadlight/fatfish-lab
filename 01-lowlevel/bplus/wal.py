"""预写日志（WAL）：让"已经被确认的写"在崩溃后仍然存在。

为什么需要它
------------
`PagedBPlusTree` 自己只做到「meta 页是提交点」——普通插入只改缓冲池里的页，
既不写 meta 也不 fsync。进程被强杀时，`BufferPool` 里那批脏页直接蒸发，
而调用方早就收到了"写成功"。WAL 补的就是这一段：**先把意图落盘，再改树**。

记录格式（每条独立，坏掉的尾部可以安全丢弃）
--------------------------------------------
::

    [magic 4B b'WAL1'] [crc32 4B] [payload_len 4B] [payload]

    payload = struct.pack('>QB', txn, kind) + extra

    kind 1 = PUT     extra = struct.pack('>qq', key, value)
    kind 2 = ACK     extra = request_id 的 UTF-8 字节（幂等去重表）
    kind 3 = COMMIT  extra = b''（该 txn 已提交，整组可以重放）

恢复语义
--------
按 `txn` 分组：**有 COMMIT 的整组保留，没有的整组丢弃**。
被丢弃的记录正是"写了日志但没来得及提交"，对应树的改动本来就不该生效。

边界（诚实说明）
----------------
* 每条记录独立校验 CRC，尾部写一半的记录会被识别并丢弃，不会读出错数据；
* 但**整文件不做校验和**，中段位翻转只能靠 CRC 定位到具体记录；
* 不做 checkpoint/压缩：重放完由调用方决定是否 `truncate()`（见 `durable.py`）。
"""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import Iterator
from typing import NamedTuple, Self

__all__ = [
  'KIND_ACK',
  'KIND_COMMIT',
  'KIND_PUT',
  'MAGIC',
  'WAL',
  'Record',
  'WALError',
]

MAGIC = b'WAL1'
_HDR = struct.Struct('>4sII')  # magic, crc32, payload_len
_META = struct.Struct('>QB')  # txn, kind

KIND_PUT = 1
KIND_ACK = 2
KIND_COMMIT = 3
KIND_PAGE = 4  # 整页镜像：恢复时直接覆盖，天然修掉 torn page

_HDR_SIZE = _HDR.size


class WALError(Exception):
  """日志损坏到无法继续（不是"尾部不完整"那种可以截断的情况）。"""


class Record(NamedTuple):
  txn: int
  kind: int
  extra: bytes

  @property
  def key_value(self) -> tuple[int, int]:
    return struct.unpack('>qq', self.extra)

  @property
  def request_id(self) -> str:
    return self.extra.decode('utf-8')

  @property
  def page(self) -> tuple[int, bytes]:
    """(页号, 页镜像字节)。"""
    return struct.unpack('>I', self.extra[:4])[0], self.extra[4:]

  @property
  def page_id(self) -> int:
    return struct.unpack('>I', self.extra[:4])[0]


def _pack(kind: int, txn: int, extra: bytes = b'') -> bytes:
  payload = _META.pack(txn, kind) + extra
  crc = zlib.crc32(payload) & 0xFFFFFFFF
  return _HDR.pack(MAGIC, crc, len(payload)) + payload


def _iter_raw(data: bytes) -> Iterator[Record]:
  """按记录遍历；遇到坏记录或半截记录就停（尾部丢弃是设计允许的）。"""
  pos = 0
  total = len(data)
  while pos + _HDR_SIZE <= total:
    magic, crc, plen = _HDR.unpack_from(data, pos)
    if magic != MAGIC:
      return
    end = pos + _HDR_SIZE + plen
    if end > total:
      return
    payload = data[pos + _HDR_SIZE : end]
    if zlib.crc32(payload) & 0xFFFFFFFF != crc:
      return
    if len(payload) < _META.size:
      return
    txn, kind = _META.unpack_from(payload, 0)
    yield Record(txn, kind, payload[_META.size :])
    pos = end


class WAL:
  """追加写 + 全程 fsync 的日志文件。

  追加的记录先攒在内存缓冲里，`commit()` 时一次性落盘并 fsync——
  这样"提交"和"落盘"是同一个动作，不会出现"记录半截落地"的中间态。
  """

  def __init__(self, path: str) -> None:
    self.path = path
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0)
    self._fd = os.open(path, flags, 0o666)
    self._buf = bytearray()
    self._appends = 0
    self._syncs = 0

  # -- 写 ---------------------------------------------------------------- #
  def append(self, kind: int, txn: int, extra: bytes = b'') -> None:
    self._buf += _pack(kind, txn, extra)
    self._appends += 1

  def append_put(self, txn: int, key: int, value: int) -> None:
    self.append(KIND_PUT, txn, struct.pack('>qq', key, value))

  def append_ack(self, txn: int, request_id: str) -> None:
    self.append(KIND_ACK, txn, request_id.encode('utf-8'))

  def append_page(self, txn: int, pid: int, data: bytes) -> None:
    """整页镜像：恢复时直接覆盖，天然修掉 torn page。"""
    self.append(KIND_PAGE, txn, struct.pack('>I', pid) + bytes(data))

  def commit(self, txn: int) -> None:
    """写 COMMIT 记录并立刻落盘——这是"这笔写已经成立"的唯一判据。"""
    self.append(KIND_COMMIT, txn)
    self.sync()

  def sync(self) -> None:
    if not self._buf:
      return
    data = bytes(self._buf)
    os.lseek(self._fd, 0, os.SEEK_END)
    written = 0
    while written < len(data):
      written += os.write(self._fd, data[written:])
    os.fsync(self._fd)
    self._buf.clear()
    self._syncs += 1

  # -- 读 ---------------------------------------------------------------- #
  def _read_all(self) -> bytes:
    os.lseek(self._fd, 0, os.SEEK_SET)
    size = os.fstat(self._fd).st_size
    chunks: list[bytes] = []
    got = 0
    while got < size:
      chunk = os.read(self._fd, min(1 << 20, size - got))
      if not chunk:
        break
      chunks.append(chunk)
      got += len(chunk)
    return b''.join(chunks)

  def records(self) -> list[Record]:
    return list(_iter_raw(self._read_all()))

  def recover(self) -> tuple[list[Record], int]:
    """返回 (已提交的记录, 最大的 txn 号)。

    已提交 = 该 txn 出现过 COMMIT；COMMIT 记录本身不返回，
    因为调用方只需要重放 PUT/ACK。
    """
    pending: dict[int, list[Record]] = {}
    committed: list[Record] = []
    max_txn = 0
    for rec in self.records():
      max_txn = max(max_txn, rec.txn)
      if rec.kind == KIND_COMMIT:
        committed.extend(pending.pop(rec.txn, ()))
      else:
        pending.setdefault(rec.txn, []).append(rec)
    return committed, max_txn

  def valid_size(self) -> int:
    """有效前缀长度：坏尾部之前的部分（供排障用）。"""
    data = self._read_all()
    pos = 0
    total = len(data)
    while pos + _HDR_SIZE <= total:
      magic, crc, plen = _HDR.unpack_from(data, pos)
      if magic != MAGIC:
        break
      end = pos + _HDR_SIZE + plen
      if end > total:
        break
      payload = data[pos + _HDR_SIZE : end]
      if zlib.crc32(payload) & 0xFFFFFFFF != crc:
        break
      pos = end
    return pos

  # -- 维护 -------------------------------------------------------------- #
  def truncate(self) -> None:
    """清空日志（调用方必须已经把状态持久化到别处，否则会丢数据）。"""
    self._buf.clear()
    os.ftruncate(self._fd, 0)
    os.fsync(self._fd)

  @property
  def stats(self) -> dict[str, int]:
    return {
      'size': os.fstat(self._fd).st_size,
      'appends': self._appends,
      'syncs': self._syncs,
      'buffered': len(self._buf),
    }

  def close(self) -> None:
    if self._fd is not None:
      self.sync()
      os.close(self._fd)
      self._fd = None  # type: ignore[assignment]

  def __enter__(self) -> Self:
    return self

  def __exit__(self, *exc: object) -> None:
    self.close()
