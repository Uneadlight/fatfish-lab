"""朴素页式 BST：**对照组**，用来把"B+ 树省 I/O"从口号变成数字。

刻意做成最傻的样子：每个节点独占一个 4096 字节页，节点里只放
`key / left / right / value` 四个字段，剩下的 4KB 全浪费。
插入按给定顺序（不平衡），查找就是一层层往下爬。

这样一页只装 1 个 key → 树高 = O(log2 n) → 每次查找要爬树高那么多页。
100 万 key 时树高约 20+，B+ 树同样数据只要 3～4 页。这就是实测对比的分母。

页布局::

    [0:8]    key    i64
    [8:12]   left   i32   (0xFFFFFFFF = 空)
    [12:16]  right  i32
    [16:24]  value  i64
"""

from __future__ import annotations

import struct

from .paged import NIL, PAGE_SIZE, PageFile

__all__ = ["PagedBST"]

_KEY = struct.Struct(">q")
_LR = struct.Struct(">II")
_VALUE = struct.Struct(">q")


class PagedBST:
    """每节点一页的不平衡二叉搜索树（对照组，不追求性能）。"""

    def __init__(self, path: str) -> None:
        self._pf = PageFile(path)
        self._root = NIL
        if self._pf.page_count == 0:
            # 第 0 页存根页号，方便重开文件后续用
            self._pf.alloc_page()
            self._write_root(NIL)
        else:
            self._root = struct.unpack(">I", self._pf.read_page(0)[0:4])[0]

    # -- 内部 -------------------------------------------------------------- #
    def _write_root(self, pid: int) -> None:
        page = bytearray(PAGE_SIZE)
        struct.pack_into(">I", page, 0, pid)
        self._pf.write_page(0, bytes(page))

    @staticmethod
    def _parse(page: bytes) -> tuple[int, int, int, int]:
        key = _KEY.unpack_from(page, 0)[0]
        left, right = _LR.unpack_from(page, 8)
        value = _VALUE.unpack_from(page, 16)[0]
        return key, left, right, value

    def _new_node(self, key: int, value: int) -> int:
        pid = self._pf.alloc_page()
        self._store(pid, key, NIL, NIL, value)
        return pid

    def _store(self, pid: int, key: int, left: int, right: int, value: int) -> None:
        page = bytearray(PAGE_SIZE)
        _KEY.pack_into(page, 0, key)
        _LR.pack_into(page, 8, left, right)
        _VALUE.pack_into(page, 16, value)
        self._pf.write_page(pid, bytes(page))

    # -- 对外接口 ---------------------------------------------------------- #
    def insert(self, key: int, value: int) -> bool:
        if self._root == NIL:
            self._root = self._new_node(key, value)
            self._write_root(self._root)
            return True
        pid = self._root
        while True:
            k, left, right, _v = self._parse(self._pf.read_page(pid))
            if key == k:
                self._store(pid, k, left, right, value)
                return False
            if key < k:
                if left == NIL:
                    new_pid = self._new_node(key, value)
                    self._store(pid, k, new_pid, right, _v)
                    return True
                pid = left
            else:
                if right == NIL:
                    new_pid = self._new_node(key, value)
                    self._store(pid, k, left, new_pid, _v)
                    return True
                pid = right

    def search(self, key: int) -> int:
        pid = self._root
        while pid != NIL:
            k, left, right, value = self._parse(self._pf.read_page(pid))
            if key == k:
                return value
            pid = left if key < k else right
        raise KeyError(key)

    @property
    def height(self) -> int:
        # 用 BFS 量真实高度（不平衡树不能只看一条路径）
        if self._root == NIL:
            return 0
        depth = 0
        frontier = [self._root]
        while frontier:
            depth += 1
            nxt = []
            for pid in frontier:
                _k, left, right, _v = self._parse(self._pf.read_page(pid))
                if left != NIL:
                    nxt.append(left)
                if right != NIL:
                    nxt.append(right)
            frontier = nxt
        return depth

    @property
    def stats(self) -> dict[str, int]:
        s = self._pf.stats
        return {
            "page_reads": s["reads"],
            "page_writes": s["writes"],
            "bytes_read": s["bytes_read"],
            "pages": s["pages"],
        }

    def clear_pool(self) -> None:
        """对照组没有缓冲池（每层都必须真读盘），保留接口让 bench 代码同形。"""

    def reset_counters(self) -> None:
        self._pf.reset_counters()

    def close(self) -> None:
        self._pf.close()

    def __enter__(self) -> PagedBST:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
