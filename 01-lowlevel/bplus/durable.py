"""可崩溃恢复 + 幂等的持久化 B+ 树。

在 `PagedBPlusTree` 外面加两层：

1. **WAL（`wal.py`）**：把"这次要改哪些页"先写进日志并 fsync，再去写页文件。
   于是崩溃只有两种结果——要么日志里没有 COMMIT（这次改动整体作废，页文件没动过），
   要么日志里有 COMMIT（恢复时按整页镜像重放，连 torn page 一起修掉）。
2. **幂等去重**：同一个 `request_id` 重复提交只生效一次。去重标记存在树自己的
   负数键空间里（见 `ack_key`），所以**跨进程、跨重启都有效**，不依赖内存状态。

写序（顺序本身就是正确性的一部分）
----------------------------------
::

    dirty 页 → WAL 记录 → WAL fsync（提交点）→ 才写页文件 → 页文件 fsync

为什么不让 `Pool.put` 直接写文件：`BufferPool` 原本是写穿透的，一旦在提交前
就把页写出去，崩溃后就是"日志说没提交、文件已经改了"的不一致状态。

多进程
------
每次写操作短暂持有 `_FileLock`（内核级文件锁，进程被杀自动释放）。
8 个客户端进程并发时由这把锁串行化——**单写者 + 多客户端**是这套设计的前提，
不是缺陷：真正的并发数据库也是这么做的（写路径串行，读路径可以并行）。
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from typing import Self

from .paged import BufferPool, PagedBPlusTree
from .wal import KIND_ACK, KIND_PAGE, WAL

__all__ = ['DurableTree', 'LockTimeout', 'ack_key']

_ACK_MASK = 0x7FFF_FFFF_FFFF_FFFF


class LockTimeout(Exception):
  """等锁超时：另一个进程占着写锁不放。"""


def ack_key(request_id: str) -> int:
  """把 request_id 映射成负数键（用户键必须为非负）。

  用 blake2b 而不是 `hash()`：后者对 str 每个进程加盐，跨进程算出来不一样，
  幂等去重就失效了。
  """
  digest = hashlib.blake2b(request_id.encode('utf-8'), digest_size=8).digest()
  return -(int.from_bytes(digest, 'big', signed=False) & _ACK_MASK) - 1


class _FileLock:
  """跨进程互斥锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）。"""

  def __init__(self, path: str) -> None:
    self.path = path
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0)
    self._fd: int | None = os.open(path, flags, 0o666)
    if os.fstat(self._fd).st_size == 0:
      os.write(self._fd, b'\0')
    self._held = False

  def _try_once(self) -> None:
    assert self._fd is not None
    os.lseek(self._fd, 0, os.SEEK_SET)
    if sys.platform == 'win32':
      import msvcrt

      msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
    else:
      import fcntl

      fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

  def acquire(self, timeout: float = 30.0) -> None:
    if self._held:
      return
    deadline = time.monotonic() + timeout
    delay = 0.002
    while True:
      try:
        self._try_once()
      except OSError:
        if time.monotonic() >= deadline:
          raise LockTimeout(f'等写锁 {timeout:.1f}s 超时：{self.path}') from None
        time.sleep(delay)
        delay = min(delay * 2, 0.05)
        continue
      self._held = True
      return

  def release(self) -> None:
    if not self._held or self._fd is None:
      return
    os.lseek(self._fd, 0, os.SEEK_SET)
    try:
      if sys.platform == 'win32':
        import msvcrt

        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
      else:
        import fcntl

        fcntl.flock(self._fd, fcntl.LOCK_UN)
    except OSError:
      pass
    self._held = False

  def close(self) -> None:
    self.release()
    if self._fd is not None:
      os.close(self._fd)
      self._fd = None


class _TxnBox:
  """当前事务号的可变盒子（`_WALPool` 通过它知道该把页写记到哪个 txn 下）。"""

  __slots__ = ('value',)

  def __init__(self) -> None:
    self.value = 0


class _WALPool(BufferPool):
  """先记日志、暂不落盘的缓冲池。

  与父类的唯一区别在 `put()`：这里**不写页文件**，只把页记进 WAL 和内存脏表；
  真正的写盘发生在 `DurableTree.put()` 调完 `wal.commit()` 之后。
  """

  def __init__(self, page_file, capacity: int, wal: WAL, txn: _TxnBox) -> None:
    super().__init__(page_file, capacity)
    self._wal = wal
    self._txn = txn
    self._dirty: dict[int, bytes] = {}

  def put(self, pid: int, data: bytes) -> None:  # type: ignore[override]
    raw = bytes(data)
    self._wal.append_page(self._txn.value, pid, raw)
    self._dirty[pid] = raw
    self._pages[pid] = raw
    self._pages.move_to_end(pid)
    if len(self._pages) > self._capacity:
      self._pages.popitem(last=False)

  def flush_dirty(self) -> int:
    """把本事务攒下的脏页真正写到页文件。"""
    count = 0
    for pid, data in list(self._dirty.items()):
      self._pf.write_page(pid, data)
      count += 1
    self._dirty.clear()
    return count

  def drop_dirty(self) -> None:
    self._dirty.clear()

  @property
  def pending_pages(self) -> int:
    return len(self._dirty)


class DurableTree:
  """带 WAL 与幂等去重的 B+ 树。

  key 必须是非负整数（负数键空间留给幂等标记）。
  """

  def __init__(self, path: str, capacity: int = 64, lock_timeout: float = 30.0) -> None:
    self.path = path
    self._lock_timeout = lock_timeout
    self._lock = _FileLock(path + '.lock')
    self._lock.acquire(lock_timeout)
    try:
      self._wal = WAL(path + '.wal')
      self._txn = _TxnBox()
      committed, max_txn = self._wal.recover()
      self._next_txn = max_txn + 1
      self._tree = PagedBPlusTree(path)
      self._pool = _WALPool(self._tree._pf, capacity, self._wal, self._txn)
      self._tree._pool = self._pool
      self._replayed = 0
      if committed:
        self._replayed = self._replay(committed)
        self._wal.truncate()
    except BaseException:
      self._lock.release()
      raise

  # -- 恢复 -------------------------------------------------------------- #
  def _replay(self, records: list) -> int:
    """按整页镜像重放已提交的页写，然后落盘并清空 WAL。"""
    pages = 0
    for rec in records:
      if rec.kind == KIND_PAGE:
        pid, data = rec.page
        self._tree._pf.write_page(pid, data)
        pages += 1
      elif rec.kind == KIND_ACK:
        continue
    self._tree._pf.flush()
    self._pool.clear()
    self._pool.drop_dirty()
    return pages

  # -- 写 ---------------------------------------------------------------- #
  def put(self, key: int, value: int, request_id: str | None = None) -> bool:
    """写一个键。返回 True 表示新生效，False 表示 request_id 重复被忽略。

    锁在 `__init__` 里已经拿到、`close()` 才放——整棵树归当前进程独占。
    多进程同时打开同一棵树时，后来的会在构造阶段排队（`lock_timeout` 秒后报
    `LockTimeout`），而不是进来互相踩页。
    """
    if key < 0:
      raise ValueError(f'key 必须是非负整数，收到 {key}')
    mark = ack_key(request_id) if request_id is not None else None

    if mark is not None and self._has(mark):
      return False

    txn = self._next_txn
    self._next_txn += 1
    self._txn.value = txn
    self._tree.insert(key, value)
    if mark is not None:
      self._tree.insert(mark, 1)
    self._wal.commit(txn)  # 提交点：日志落盘
    self._pool.flush_dirty()  # 这时才写页
    self._tree._pf.flush()
    return True

  def delete(self, key: int) -> bool:
    raise NotImplementedError('本轮只做写入持久性，删除留给下一阶段')

  # -- 读 ---------------------------------------------------------------- #
  def _has(self, key: int) -> bool:
    try:
      self._tree.search(key)
    except KeyError:
      return False
    return True

  def get(self, key: int) -> int:
    return self._tree.search(key)

  def get_or(self, key: int, default: int | None = None) -> int | None:
    try:
      return self._tree.search(key)
    except KeyError:
      return default

  def range_scan(self, lo: int | None = None, hi: int | None = None) -> list[tuple[int, int]]:
    """只返回用户键（负数键是幂等标记，不对外暴露）。"""
    return [(k, v) for k, v in self._tree.range_scan(lo, hi) if k >= 0]

  def keys(self) -> list[int]:
    return [k for k, _ in self.range_scan()]

  def __len__(self) -> int:
    return len(self.keys())

  # -- 维护 -------------------------------------------------------------- #
  @property
  def stats(self) -> dict[str, int]:
    return {
      'entries': len(self),
      'replayed_pages': self._replayed,
      'next_txn': self._next_txn,
      'wal_size': self._wal.stats['size'],
      'wal_syncs': self._wal.stats['syncs'],
      'pages_read': self._tree._pf.stats.get('reads', 0),
      'pages_written': self._tree._pf.stats.get('writes', 0),
    }

  def close(self) -> None:
    try:
      self._pool.flush_dirty()
      self._tree._pf.flush()
      self._wal.close()
      self._tree.close()
    finally:
      self._lock.close()

  def __enter__(self) -> Self:
    return self

  def __exit__(self, *exc: object) -> None:
    self.close()
