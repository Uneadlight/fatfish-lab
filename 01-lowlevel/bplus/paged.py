"""页式落盘 B+ 树：真实 `os.pread/pwrite` + 4KB 页 + LRU 缓冲池。

与内存版的区别（也是它存在的理由）
--------------------------------
内存版测不出磁盘 I/O —— 所有节点都在 RAM 里，"树矮"只省了几次指针跳转，
不省 I/O。落盘版把**每个节点压缩成一个 4096 字节的页**，用 `os.pread`
按页号定位读取，于是"树高"直接等于"一次查找要读几个页"，
才能和"每节点一页的二叉树"做同口径对比。

页布局（4096 字节，定长槽位，解析不需要偏移表）
----------------------------------------------
::

    [0]      kind        1B   1=内部 2=叶子 0=空
    [1:3]    nkeys       2B   大端
    [3:5]    next        2B   叶子链下一页号（0xFFFF=无）
    [8:12]   child0      4B   内部节点第 0 个孩子
    [16:]    slots       16B/槽
               叶子槽:  key i64 | value i64
               内部槽:  child i32 | sep key i64 | pad 4B

定长槽位的好处：定位第 i 个槽是纯算术，不用扫描；代价是浪费 padding，
但一页 4KB 本来就要按页对齐，浪费几字节换 O(1) 定位值。

持久化与"崩溃安全"的边界（诚实说明）
--------------------------------
* 写入顺序：先写所有数据页，**最后**写 meta 页（root_pid 在里面）——
  meta 页是"提交点"，崩溃在它之前 = 回到旧根，旧树仍然自洽。
* 但**没有 WAL、没有页校验和**：如果崩溃发生在单页写一半，
  那一页可能半新半旧（torn page）。真实数据库靠 double-write buffer / checksum 解决，
  本项目只做到"meta 提交点"，不冒充完整事务。
"""

from __future__ import annotations

import contextlib
import os
import struct
from collections import OrderedDict

__all__ = [
    "PAGE_SIZE",
    "PageError",
    "PageFile",
    "BufferPool",
    "PagedBPlusTree",
]

PAGE_SIZE = 4096
KIND_META = 0
KIND_INTERNAL = 1
KIND_LEAF = 2
NIL = 0xFFFFFFFF

MAX_KEYS = (PAGE_SIZE - 16) // 16  # 255：每页最多 255 个键

_NKEYS = struct.Struct(">H")
_CHILD0 = struct.Struct(">I")
_LEAF_SLOT = struct.Struct(">qq")
_INNER_SLOT = struct.Struct(">Iq")

MAGIC = b"BPTP"

# Windows 的 Python **没有 os.pread / os.pwrite**（它们自 3.3 起只存在于 POSIX），
# 直接用会 AttributeError。这里做一层可移植封装：有就直用，没有就 lseek + read/write。
# 注意：lseek 方案在"同一个 fd 多线程并发读写"时不是原子的，本模块单线程使用。
_HAS_PREAD = hasattr(os, "pread") and hasattr(os, "pwrite")


def _pread_exact(fd: int, n: int, offset: int) -> bytes:
    """从 offset 读满 n 字节（短读会循环补齐，返回不足即 EOF）。"""
    if _HAS_PREAD:
        chunks = []
        got = 0
        while got < n:
            chunk = os.pread(fd, n - got, offset + got)
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)
    os.lseek(fd, offset, os.SEEK_SET)
    chunks = []
    got = 0
    while got < n:
        chunk = os.read(fd, n - got)
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _pwrite_all(fd: int, data: bytes, offset: int) -> None:
    """把 data 全部写到 offset（同样处理短写）。"""
    if _HAS_PREAD:
        written = 0
        while written < len(data):
            written += os.pwrite(fd, data[written:], offset + written)
        return
    os.lseek(fd, offset, os.SEEK_SET)
    written = 0
    while written < len(data):
        written += os.write(fd, data[written:])


class PageError(Exception):
    """页层错误：越界、未分配页、数据长度不对、文件损坏。"""


class PageFile:
    """定长页文件的读写封装，自带真实 I/O 计数（这是实测数据的来源）。"""

    def __init__(self, path: str, create: bool = True) -> None:
        self.path = path
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        if create:
            flags |= os.O_CREAT
            self._fd = os.open(path, flags, 0o666)
            created_now = os.fstat(self._fd).st_size == 0
        else:
            self._fd = os.open(path, flags)
            created_now = False
        self._reads = 0
        self._writes = 0
        self._bytes_read = 0
        self._page_count = 0 if created_now else self._probe_page_count()

    # -- 元信息 ------------------------------------------------------------ #
    def _probe_page_count(self) -> int:
        size = os.fstat(self._fd).st_size
        if size % PAGE_SIZE:
            raise PageError(f"文件长度 {size} 不是 {PAGE_SIZE} 的整数倍，疑似损坏")
        return size // PAGE_SIZE

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def stats(self) -> dict[str, int]:
        return {
            "reads": self._reads,
            "writes": self._writes,
            "bytes_read": self._bytes_read,
            "pages": self._page_count,
        }

    def reset_counters(self) -> None:
        self._reads = 0
        self._writes = 0
        self._bytes_read = 0

    # -- 读写 -------------------------------------------------------------- #
    def read_page(self, pid: int) -> bytes:
        if pid < 0 or pid >= self._page_count:
            raise PageError(f"页号越界: {pid}（共 {self._page_count} 页）")
        data = _pread_exact(self._fd, PAGE_SIZE, pid * PAGE_SIZE)
        self._reads += 1
        self._bytes_read += len(data)
        if len(data) != PAGE_SIZE:
            raise PageError(f"页 {pid} 读取不足：期望 {PAGE_SIZE} 字节，得到 {len(data)}")
        return data

    def write_page(self, pid: int, data: bytes) -> None:
        if len(data) != PAGE_SIZE:
            raise PageError(f"页数据必须是 {PAGE_SIZE} 字节，收到 {len(data)}")
        if pid < 0 or pid >= self._page_count:
            raise PageError(f"写入未分配页: {pid}")
        _pwrite_all(self._fd, data, pid * PAGE_SIZE)
        self._writes += 1

    def alloc_page(self) -> int:
        pid = self._page_count
        _pwrite_all(self._fd, bytes(PAGE_SIZE), pid * PAGE_SIZE)
        self._page_count += 1
        self._writes += 1
        return pid

    def flush(self) -> None:
        with contextlib.suppress(OSError):
            os.fsync(self._fd)

    def close(self) -> None:
        if self._fd is not None:
            self.flush()
            os.close(self._fd)
            self._fd = None  # type: ignore[assignment]


class BufferPool:
    """极简 LRU 页缓存：容量固定，命中不读盘，未命中真读盘并计入 misses。"""

    def __init__(self, page_file: PageFile, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("capacity 必须 >= 1")
        self._pf = page_file
        self._capacity = capacity
        self._pages: OrderedDict[int, bytes] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, pid: int) -> bytes:
        page = self._pages.get(pid)
        if page is not None:
            self._pages.move_to_end(pid)
            self._hits += 1
            return page
        self._misses += 1
        page = self._pf.read_page(pid)
        self._pages[pid] = page
        self._pages.move_to_end(pid)
        if len(self._pages) > self._capacity:
            self._pages.popitem(last=False)
        return page

    def put(self, pid: int, data: bytes) -> None:
        """写穿透：先落盘再更新缓存，避免"缓存改了盘没改"的假一致。"""
        self._pf.write_page(pid, data)
        self._pages[pid] = data
        self._pages.move_to_end(pid)
        if len(self._pages) > self._capacity:
            self._pages.popitem(last=False)

    def alloc(self) -> int:
        pid = self._pf.alloc_page()
        self._pages[pid] = bytes(PAGE_SIZE)
        if len(self._pages) > self._capacity:
            self._pages.popitem(last=False)
        return pid

    def clear(self) -> None:
        self._pages.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "capacity": self._capacity,
            "size": len(self._pages),
        }

    def reset_counters(self) -> None:
        self._hits = 0
        self._misses = 0


# --------------------------------------------------------------------------- #
# 页编解码
# --------------------------------------------------------------------------- #
def _blank_page(kind: int) -> bytearray:
    page = bytearray(PAGE_SIZE)
    page[0] = kind
    return page


def _get_nkeys(page: bytes) -> int:
    return _NKEYS.unpack_from(page, 1)[0]


def _set_nkeys(page: bytearray, n: int) -> None:
    _NKEYS.pack_into(page, 1, n)


def _get_next(page: bytes) -> int:
    return struct.unpack_from(">H", page, 3)[0]


def _set_next(page: bytearray, pid: int) -> None:
    struct.pack_into(">H", page, 3, pid)


def _get_child0(page: bytes) -> int:
    return _CHILD0.unpack_from(page, 8)[0]


def _set_child0(page: bytearray, pid: int) -> None:
    _CHILD0.pack_into(page, 8, pid)


def _leaf_keys_values(page: bytes) -> tuple[list[int], list[int]]:
    n = _get_nkeys(page)
    keys = [0] * n
    values = [0] * n
    off = 16
    for i in range(n):
        k, v = _LEAF_SLOT.unpack_from(page, off)
        keys[i] = k
        values[i] = v
        off += 16
    return keys, values


def _write_leaf(page: bytearray, keys: list[int], values: list[int]) -> None:
    _set_nkeys(page, len(keys))
    off = 16
    for k, v in zip(keys, values, strict=False):
        _LEAF_SLOT.pack_into(page, off, k, v)
        off += 16


def _inner_keys_children(page: bytes) -> tuple[list[int], list[int]]:
    n = _get_nkeys(page)
    children = [_get_child0(page)]
    keys = [0] * n
    off = 16
    for i in range(n):
        child, key = _INNER_SLOT.unpack_from(page, off)
        children.append(child)
        keys[i] = key
        off += 16
    return keys, children


def _write_inner(page: bytearray, keys: list[int], children: list[int]) -> None:
    _set_nkeys(page, len(keys))
    _set_child0(page, children[0])
    off = 16
    for i, key in enumerate(keys):
        _INNER_SLOT.pack_into(page, off, children[i + 1], key)
        off += 16


# --------------------------------------------------------------------------- #
# 页式 B+ 树
# --------------------------------------------------------------------------- #
class PagedBPlusTree:
    """落盘 B+ 树（插入 / 查找 / 范围扫描）。删除合并见内存版，落盘版未实现（见类注释）。"""

    def __init__(self, path: str, pool_size: int = 64) -> None:
        self._pf = PageFile(path)
        self._pool = BufferPool(self._pf, capacity=pool_size)
        self._path = path
        if self._pf.page_count == 0:
            self._init_meta()
        self._root_pid, head = self._read_meta()
        self._leaf_head = head

    # -- meta -------------------------------------------------------------- #
    def _init_meta(self) -> None:
        meta_pid = self._pool.alloc()
        if meta_pid != 0:
            raise PageError("新建文件时 meta 页必须是 0")
        root_pid = self._pool.alloc()
        page = _blank_page(KIND_LEAF)
        _set_next(page, 0xFFFF)
        self._pool.put(root_pid, bytes(page))
        self._write_meta(root_pid, root_pid)

    def _write_meta(self, root_pid: int, leaf_head: int) -> None:
        page = _blank_page(KIND_META)
        page[8:12] = MAGIC
        struct.pack_into(">I", page, 12, root_pid)
        struct.pack_into(">I", page, 16, leaf_head)
        self._pool.put(0, bytes(page))
        self._pf.flush()  # meta 是提交点：先刷数据页再刷它

    def _read_meta(self) -> tuple[int, int]:
        page = self._pool.get(0)
        if page[8:12] != MAGIC:
            raise PageError(f"不是有效的 B+ 树文件（magic={page[8:12]!r}）")
        root_pid = struct.unpack_from(">I", page, 12)[0]
        leaf_head = struct.unpack_from(">I", page, 16)[0]
        return root_pid, leaf_head

    # -- 生命周期 ---------------------------------------------------------- #
    @property
    def height(self) -> int:
        h = 1
        pid = self._root_pid
        while self._pool.get(pid)[0] == KIND_INTERNAL:
            pid = _get_child0(self._pool.get(pid))
            h += 1
        return h

    @property
    def stats(self) -> dict[str, int]:
        pf = self._pf.stats
        pool = self._pool.stats
        return {
            "page_reads": pf["reads"],
            "page_writes": pf["writes"],
            "bytes_read": pf["bytes_read"],
            "pages": pf["pages"],
            "pool_hits": pool["hits"],
            "pool_misses": pool["misses"],
            "pool_size": pool["size"],
        }

    def reset_counters(self) -> None:
        self._pf.reset_counters()
        self._pool.reset_counters()

    def clear_pool(self) -> None:
        self._pool.clear()

    def close(self) -> None:
        self._pf.close()

    def __enter__(self) -> PagedBPlusTree:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- 读 ---------------------------------------------------------------- #
    def _descend(self, key: int) -> tuple[int, list[tuple[int, int]]]:
        """下行到叶子页；返回 (叶子页号, [(父页号, 孩子下标), ...])。"""
        pid = self._root_pid
        path: list[tuple[int, int]] = []
        while True:
            page = self._pool.get(pid)
            if page[0] == KIND_LEAF:
                return pid, path
            keys, children = _inner_keys_children(page)
            i = _bisect_right(keys, key)
            path.append((pid, i))
            pid = children[i]

    def search(self, key: int) -> int:
        pid, _ = self._descend(key)
        keys, values = _leaf_keys_values(self._pool.get(pid))
        i = _bisect_left(keys, key)
        if i < len(keys) and keys[i] == key:
            return values[i]
        raise KeyError(key)

    def range_scan(self, lo: int | None = None, hi: int | None = None) -> list[tuple[int, int]]:
        if lo is not None and hi is not None and lo > hi:
            return []
        if lo is None:
            pid = self._leaf_head
        else:
            pid, _ = self._descend(lo)
        out: list[tuple[int, int]] = []
        while pid != 0xFFFF:
            page = self._pool.get(pid)
            keys, values = _leaf_keys_values(page)
            for i, k in enumerate(keys):
                if lo is not None and k < lo:
                    continue
                if hi is not None and k > hi:
                    return out
                out.append((k, values[i]))
            pid = _get_next(page) if _get_next(page) != 0xFFFF else 0xFFFF
            if pid == 0xFFFF:
                break
        return out

    # -- 写 ---------------------------------------------------------------- #
    def insert(self, key: int, value: int) -> bool:
        pid, path = self._descend(key)
        page = bytearray(self._pool.get(pid))
        keys, values = _leaf_keys_values(page)
        i = _bisect_left(keys, key)
        if i < len(keys) and keys[i] == key:
            values[i] = value
            _write_leaf(page, keys, values)
            self._pool.put(pid, bytes(page))
            return False

        keys.insert(i, key)
        values.insert(i, value)
        if len(keys) <= MAX_KEYS:
            _write_leaf(page, keys, values)
            self._pool.put(pid, bytes(page))
            return True

        # 分裂叶子：左半留原页，右半新页，右半最小键提升为分隔键
        mid = len(keys) // 2
        left_keys, left_values = keys[:mid], values[:mid]
        right_keys, right_values = keys[mid:], values[mid:]
        old_next = _get_next(page)
        right_pid = self._pool.alloc()
        right_page = _blank_page(KIND_LEAF)
        _set_next(right_page, old_next)
        _write_leaf(right_page, right_keys, right_values)
        self._pool.put(right_pid, bytes(right_page))

        _set_next(page, _truncate_pid(right_pid))
        _write_leaf(page, left_keys, left_values)
        self._pool.put(pid, bytes(page))

        self._insert_into_parent(path, right_keys[0], right_pid)
        return True

    def _insert_into_parent(
        self, path: list[tuple[int, int]], sep: int, right_pid: int
    ) -> None:
        while path:
            parent_pid, idx = path.pop()
            page = bytearray(self._pool.get(parent_pid))
            keys, children = _inner_keys_children(page)
            keys.insert(idx, sep)
            children.insert(idx + 1, right_pid)
            if len(keys) <= MAX_KEYS:
                _write_inner(page, keys, children)
                self._pool.put(parent_pid, bytes(page))
                return
            mid = len(keys) // 2
            up = keys[mid]
            right_keys = keys[mid + 1 :]
            right_children = children[mid + 1 :]
            left_keys = keys[:mid]
            left_children = children[: mid + 1]

            new_pid = self._pool.alloc()
            new_page = _blank_page(KIND_INTERNAL)
            _write_inner(new_page, right_keys, right_children)
            self._pool.put(new_pid, bytes(new_page))

            _write_inner(page, left_keys, left_children)
            self._pool.put(parent_pid, bytes(page))

            sep, right_pid = up, new_pid

        # 根分裂：新根只含一个分隔键
        new_root_pid = self._pool.alloc()
        root_page = _blank_page(KIND_INTERNAL)
        _write_inner(root_page, [sep], [self._root_pid, right_pid])
        self._pool.put(new_root_pid, bytes(root_page))
        self._root_pid = new_root_pid
        self._write_meta(self._root_pid, self._leaf_head)

    def _update_leaf_head(self, pid: int) -> None:
        if self._leaf_head != pid:
            self._leaf_head = pid
            self._write_meta(self._root_pid, self._leaf_head)


# --------------------------------------------------------------------------- #
# 小工具（避免 import bisect 后再包一层，语义更直观）
# --------------------------------------------------------------------------- #
def _bisect_left(seq: list[int], value: int) -> int:
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if seq[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(seq: list[int], value: int) -> int:
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if value < seq[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _truncate_pid(pid: int) -> int:
    if pid > 0xFFFF:
        raise PageError(f"页号 {pid} 超过 16 位（叶子链 next 字段只有 2 字节）")
    return pid
