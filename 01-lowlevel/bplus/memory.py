"""B+ 树（纯内存版）：为什么磁盘数据库选它、内存里它长什么样。

一句话概括差异
--------------
* **B+ 树**：多路平衡树，一个节点装几十上百个 key（扇出大、树矮），
  数据只放叶子，叶子用链表串起来。磁盘上一次页读 = 一个节点，
  所以树高就是 I/O 次数：10 万条 key、order=64 时树高 3 → 3 次页读。
* **红黑树**：二叉、扇出 2、每个节点只放 1 个 key，10 万条约 17 层 →
  每层一个节点 = 17 次页读，而且每次旋转都可能写回不同页（写放大）。

内存里两者都是 O(log n)；差别只在**每次比较要不要付一次 I/O**。
详见 `reports/Task2-B+树与RPC.md` 的实测数字。

内存版实现要点（也是后面页式版的地基）
------------------------------------
* 内部节点只存**分隔键**（等于右子树最小键），叶子存真数据；
* 插入满则**分裂并提升**分隔键；删除欠载则先**借位**、不行再**合并**；
* 根是唯一允许不满足最小键数限制的节点；根空了就降一层；
* 叶子 `next` 链表让范围扫描变成"定位起点 + 顺着链走"，不必每次回根。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from typing import Any

__all__ = ["BPlusTree"]


class _Leaf:
    __slots__ = ("keys", "values", "next")
    is_leaf = True

    def __init__(self, keys: list, values: list, next_leaf: _Leaf | None = None) -> None:
        self.keys = keys
        self.values = values
        self.next = next_leaf


class _Internal:
    __slots__ = ("keys", "children")
    is_leaf = False

    def __init__(self, keys: list, children: list) -> None:
        self.keys = keys
        self.children = children


class BPlusTree:
    """内存版 B+ 树。order = 最大分支数（内部节点最多 order 个孩子）。"""

    def __init__(self, order: int = 64) -> None:
        if not isinstance(order, int) or isinstance(order, bool):
            raise ValueError("order 必须是整数")
        if order < 3:
            raise ValueError("order 必须 >= 3（否则最小键数退化为 0，树会失衡）")
        self.order = order
        self.max_keys = order - 1
        # 非根节点最少键数 = ceil(order/2) - 1
        self.min_keys = (order + 1) // 2 - 1
        self._root: _Leaf | _Internal = _Leaf([], [])
        self._size = 0

    # -- 容器协议 ---------------------------------------------------------- #
    def __len__(self) -> int:
        return self._size

    def __contains__(self, key: object) -> bool:
        try:
            self.search(key)  # type: ignore[arg-type]
        except KeyError:
            return False
        return True

    def __getitem__(self, key: Any) -> Any:
        return self.search(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self.insert(key, value)

    def __delitem__(self, key: Any) -> None:
        if not self.delete(key):
            raise KeyError(key)

    def __repr__(self) -> str:
        return f"BPlusTree(order={self.order}, size={self._size}, height={self.height})"

    # -- 读 ----------------------------------------------------------------- #
    def _find_leaf(self, key: Any) -> tuple[_Leaf, list[tuple[_Internal, int]]]:
        """下行到叶子，同时记录路径（path 用于分裂/合并时回填父节点）。"""
        node = self._root
        path: list[tuple[_Internal, int]] = []
        while not node.is_leaf:
            i = bisect_right(node.keys, key)
            path.append((node, i))
            node = node.children[i]
        return node, path  # type: ignore[return-value]

    def search(self, key: Any) -> Any:
        leaf, _ = self._find_leaf(key)
        i = bisect_left(leaf.keys, key)
        if i < len(leaf.keys) and leaf.keys[i] == key:
            return leaf.values[i]
        raise KeyError(key)

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self.search(key)
        except KeyError:
            return default

    @property
    def height(self) -> int:
        h = 1
        node = self._root
        while not node.is_leaf:
            h += 1
            node = node.children[0]
        return h

    def _leftmost_leaf(self) -> _Leaf:
        node = self._root
        while not node.is_leaf:
            node = node.children[0]
        return node  # type: ignore[return-value]

    def items(self) -> Iterator[tuple[Any, Any]]:
        leaf = self._leftmost_leaf()
        while leaf is not None:
            for i in range(len(leaf.keys)):
                yield leaf.keys[i], leaf.values[i]
            leaf = leaf.next

    def keys(self) -> Iterator[Any]:
        for k, _ in self.items():
            yield k

    def values(self) -> Iterator[Any]:
        for _, v in self.items():
            yield v

    def range_scan(self, lo: Any = None, hi: Any = None) -> list[tuple[Any, Any]]:
        """闭区间 [lo, hi] 升序扫描；任一端为 None 表示不限。"""
        if lo is not None and hi is not None and lo > hi:
            return []
        if self._size == 0:
            return []
        leaf = self._find_leaf(lo)[0] if lo is not None else self._leftmost_leaf()
        out: list[tuple[Any, Any]] = []
        while leaf is not None:
            for i, k in enumerate(leaf.keys):
                if lo is not None and k < lo:
                    continue
                if hi is not None and k > hi:
                    return out
                out.append((k, leaf.values[i]))
            leaf = leaf.next
        return out

    # -- 写 ----------------------------------------------------------------- #
    def insert(self, key: Any, value: Any) -> bool:
        """插入或覆盖；返回 True 表示新增，False 表示覆盖已有 key。"""
        leaf, path = self._find_leaf(key)
        i = bisect_left(leaf.keys, key)
        if i < len(leaf.keys) and leaf.keys[i] == key:
            leaf.values[i] = value
            return False
        leaf.keys.insert(i, key)
        leaf.values.insert(i, value)
        self._size += 1
        if len(leaf.keys) > self.max_keys:
            self._split_leaf(leaf, path)
        return True

    def _split_leaf(self, leaf: _Leaf, path: list[tuple[_Internal, int]]) -> None:
        mid = len(leaf.keys) // 2
        right = _Leaf(leaf.keys[mid:], leaf.values[mid:], leaf.next)
        leaf.keys = leaf.keys[:mid]
        leaf.values = leaf.values[:mid]
        leaf.next = right
        self._propagate_split(path, right, right.keys[0])

    def _propagate_split(
        self, path: list[tuple[_Internal, int]], right: Any, sep: Any
    ) -> None:
        child = right
        while path:
            parent, idx = path.pop()
            parent.keys.insert(idx, sep)
            parent.children.insert(idx + 1, child)
            if len(parent.keys) <= self.max_keys:
                return
            mid = len(parent.keys) // 2
            up = parent.keys[mid]
            new_right = _Internal(parent.keys[mid + 1 :], parent.children[mid + 1 :])
            parent.keys = parent.keys[:mid]
            parent.children = parent.children[: mid + 1]
            child = new_right
            sep = up
        self._root = _Internal([sep], [self._root, child])

    def delete(self, key: Any) -> bool:
        leaf, path = self._find_leaf(key)
        i = bisect_left(leaf.keys, key)
        if i >= len(leaf.keys) or leaf.keys[i] != key:
            return False
        del leaf.keys[i]
        del leaf.values[i]
        self._size -= 1
        self._rebalance(leaf, path)
        return True

    def _rebalance(self, node: Any, path: list[tuple[_Internal, int]]) -> None:
        while path:
            parent, idx = path[-1]
            if len(node.keys) >= self.min_keys:
                return
            left = parent.children[idx - 1] if idx > 0 else None
            right = (
                parent.children[idx + 1] if idx + 1 < len(parent.children) else None
            )

            if node.is_leaf:
                if left is not None and len(left.keys) > self.min_keys:
                    node.keys.insert(0, left.keys.pop())
                    node.values.insert(0, left.values.pop())
                    parent.keys[idx - 1] = node.keys[0]
                    return
                if right is not None and len(right.keys) > self.min_keys:
                    node.keys.append(right.keys.pop(0))
                    node.values.append(right.values.pop(0))
                    parent.keys[idx] = right.keys[0]
                    return
                if left is not None:
                    left.keys.extend(node.keys)
                    left.values.extend(node.values)
                    left.next = node.next
                    del parent.keys[idx - 1]
                    del parent.children[idx]
                else:
                    node.keys.extend(right.keys)  # type: ignore[union-attr]
                    node.values.extend(right.values)  # type: ignore[union-attr]
                    node.next = right.next  # type: ignore[union-attr]
                    del parent.keys[idx]
                    del parent.children[idx + 1]
            else:
                if left is not None and len(left.keys) > self.min_keys:
                    # 父分隔键下移，左兄弟最大键上移
                    node.keys.insert(0, parent.keys[idx - 1])
                    node.children.insert(0, left.children.pop())
                    parent.keys[idx - 1] = left.keys.pop()
                    return
                if right is not None and len(right.keys) > self.min_keys:
                    node.keys.append(parent.keys[idx])
                    node.children.append(right.children.pop(0))
                    parent.keys[idx] = right.keys.pop(0)
                    return
                if left is not None:
                    left.keys.append(parent.keys[idx - 1])
                    left.keys.extend(node.keys)
                    left.children.extend(node.children)
                    del parent.keys[idx - 1]
                    del parent.children[idx]
                else:
                    node.keys.append(parent.keys[idx])
                    node.keys.extend(right.keys)  # type: ignore[union-attr]
                    node.children.extend(right.children)  # type: ignore[union-attr]
                    del parent.keys[idx]
                    del parent.children[idx + 1]

            node = parent
            path.pop()

        # 根塌陷：根是内部节点但已没有分隔键 → 唯一孩子上位
        while not self._root.is_leaf and len(self._root.keys) == 0:
            self._root = self._root.children[0]  # type: ignore[assignment]

    # -- 自检（测试与调试用，生产路径不调用） ------------------------------ #
    def check_invariants(self) -> None:
        """校验 B+ 树全部性质；违反则 AssertionError。O(n)。"""
        root = self._root
        leaf_depths: list[int] = []
        leaf_nodes: list[_Leaf] = []

        def walk(node: Any, depth: int, low: Any, high: Any, is_root: bool) -> None:
            keys = node.keys
            assert keys == sorted(keys), f"keys 未排序: {keys[:8]}"
            assert len(set(keys)) == len(keys), f"key 重复: {keys[:8]}"
            if not is_root:
                assert len(keys) >= self.min_keys, f"欠载: {len(keys)} < {self.min_keys}"
            else:
                assert len(keys) <= self.max_keys, "根超载"
            for k in keys:
                if low is not None:
                    assert k >= low, f"下界违约: {k} < {low}"
                if high is not None:
                    assert k < high, f"上界违约: {k} >= {high}"

            if node.is_leaf:
                assert len(node.keys) == len(node.values), "叶子 keys/values 长度不一致"
                leaf_depths.append(depth)
                leaf_nodes.append(node)
                return

            assert len(node.children) == len(keys) + 1, (
                f"内部节点 children 数 {len(node.children)} != keys+1 {len(keys) + 1}"
            )
            for i, child in enumerate(node.children):
                child_low = keys[i - 1] if i > 0 else low
                child_high = keys[i] if i < len(keys) else high
                walk(child, depth + 1, child_low, child_high, False)

        walk(root, 0, None, None, True)

        assert len(set(leaf_depths)) == 1, f"叶子不同高: {set(leaf_depths)}"
        assert sum(len(ln.keys) for ln in leaf_nodes) == self._size, "size 与叶子总键数不符"

        # 叶子链表必须与中序遍历顺序一致
        chain: list[Any] = []
        leaf = self._leftmost_leaf()
        guard = 0
        while leaf is not None:
            chain.extend(leaf.keys)
            leaf = leaf.next
            guard += 1
            assert guard <= len(leaf_nodes) + 1, "叶子链表出现环"
        assert chain == [k for ln in leaf_nodes for k in ln.keys], "叶子链表顺序错乱"
        assert len(chain) == self._size
