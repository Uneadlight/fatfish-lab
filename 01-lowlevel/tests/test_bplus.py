"""B+ 树（内存版）：正确性、边界、与 dict 的随机对照。

被测接口（契约）：
    bplus.memory.BPlusTree(order: int = 64)
        .insert(key, value) -> bool       # True=新增, False=覆盖已有 key
        .search(key) -> Any               # 不存在抛 KeyError（值本身可以是 None）
        .get(key, default=None) -> Any
        .delete(key) -> bool              # True=删掉了, False=本来就没有
        .range_scan(lo=None, hi=None) -> list[tuple[key, value]]   # 闭区间，升序
        .items() / .keys() / .values()    # 升序迭代
        .height -> int                    # 叶子层为 1
        .check_invariants() -> None       # 不满足 B+ 树性质就抛 AssertionError
        .__len__, .__contains__, __getitem__, __setitem__, __delitem__

order 的含义：**最大分支数**（内部节点最多 order 个孩子 / order-1 个分隔键）。
叶子最多 order-1 个键；非根节点最少 (order+1)//2 - 1 个键。
"""

import random

import pytest
from bplus.memory import BPlusTree


def test_empty_tree():
    t = BPlusTree(order=4)
    assert len(t) == 0
    assert t.height == 1
    assert list(t.items()) == []
    assert t.range_scan() == []
    with pytest.raises(KeyError):
        t.search(1)
    assert t.get(1) is None
    assert t.get(1, "缺省") == "缺省"
    assert t.delete(1) is False
    t.check_invariants()


def test_insert_search_update():
    t = BPlusTree(order=4)
    assert t.insert(10, "a") is True
    assert t.insert(20, "b") is True
    assert t.insert(10, "a2") is False  # 覆盖
    assert len(t) == 2
    assert t.search(10) == "a2"
    assert t.search(20) == "b"
    assert 10 in t
    assert 99 not in t
    assert t[10] == "a2"
    t[30] = "c"
    assert t[30] == "c"
    del t[30]
    assert 30 not in t
    t.check_invariants()


def test_value_can_be_none():
    """值可以为 None，所以 search 不能拿 None 当"没找到"的哨兵。"""
    t = BPlusTree(order=4)
    t.insert(1, None)
    assert t.search(1) is None
    assert 1 in t
    assert len(t) == 1


def test_str_keys():
    t = BPlusTree(order=4)
    for k in ["pear", "apple", "zebra", "banana", "中文", "apple2"]:
        t.insert(k, k.upper())
    assert [k for k, _ in t.items()] == sorted(["pear", "apple", "zebra", "banana", "中文", "apple2"])
    t.check_invariants()


def test_split_grows_height():
    t = BPlusTree(order=4)
    for i in range(100):
        t.insert(i, i * 2)
    assert t.height >= 3, f"100 条 order=4 应该有 3 层以上，实际 {t.height}"
    assert len(t) == 100
    t.check_invariants()
    for i in range(100):
        assert t.search(i) == i * 2


def test_ordered_iteration_matches_sorted():
    rng = random.Random(7)
    keys = rng.sample(range(100000), 2000)
    t = BPlusTree(order=8)
    for k in keys:
        t.insert(k, k)
    assert [k for k, _ in t.items()] == sorted(keys)
    assert list(t.keys()) == sorted(keys)
    assert list(t.values()) == sorted(keys)
    t.check_invariants()


def test_range_scan_bounds():
    t = BPlusTree(order=4)
    for i in range(0, 100, 2):  # 偶数 0..98
        t.insert(i, i)
    assert t.range_scan(10, 20) == [(i, i) for i in range(10, 21, 2)]
    assert t.range_scan(None, 4) == [(0, 0), (2, 2), (4, 4)]
    assert t.range_scan(94, None) == [(94, 94), (96, 96), (98, 98)]
    assert t.range_scan(11, 19) == [(12, 12), (14, 14), (16, 16), (18, 18)]
    assert t.range_scan(10, 9) == []
    assert len(t.range_scan()) == 50
    t.check_invariants()


def test_delete_everything_forward_and_backward():
    for order in (4, 5, 64):
        for reverse in (False, True):
            t = BPlusTree(order=order)
            n = 200
            order_keys = list(range(n))
            if reverse:
                order_keys.reverse()
            for k in order_keys:
                t.insert(k, k)
            for k in order_keys:
                assert t.delete(k) is True, f"order={order} 删 {k} 失败"
                t.check_invariants()
            assert len(t) == 0
            assert list(t.items()) == []
            assert t.height == 1


def test_delete_nonexistent_returns_false():
    t = BPlusTree(order=4)
    for i in range(50):
        t.insert(i, i)
    assert t.delete(1000) is False
    assert len(t) == 50
    t.check_invariants()


def test_random_ops_against_dict_oracle():
    """随机 5000 次操作，树的状态必须和 dict 完全一致（覆盖分裂/借位/合并所有路径）。"""
    rng = random.Random(20261029)
    for order in (4, 6, 64):
        t = BPlusTree(order=order)
        oracle: dict[int, int] = {}
        for step in range(5000):
            k = rng.randrange(0, 500)
            op = rng.random()
            if op < 0.55:
                expected_new = k not in oracle
                assert t.insert(k, step) is expected_new, f"order={order} step={step} insert({k}) 返回值不对"
                oracle[k] = step
            elif op < 0.85:
                assert t.delete(k) is (k in oracle), f"order={order} step={step} delete({k}) 返回值不对"
                oracle.pop(k, None)
            else:
                assert t.get(k, "__none__") == oracle.get(k, "__none__")
            if step % 500 == 0:
                t.check_invariants()
                assert len(t) == len(oracle)
        t.check_invariants()
        assert [kv for kv in t.items()] == sorted(oracle.items())
        assert t.range_scan(0, 100) == sorted((k, v) for k, v in oracle.items() if 0 <= k <= 100)


def test_leaf_chain_contiguous():
    """叶子链表必须真正连起来（范围扫描不靠每次从根重下）。"""
    t = BPlusTree(order=4)
    for i in range(1000):
        t.insert(i, i)
    keys = [k for k, _ in t.items()]
    assert keys == list(range(1000))
    t.check_invariants()


def test_reject_bad_order():
    with pytest.raises(ValueError):
        BPlusTree(order=2)
    with pytest.raises(ValueError):
        BPlusTree(order=0)
