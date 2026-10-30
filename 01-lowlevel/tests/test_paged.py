"""页式落盘 B+ 树 + 朴素页式 BST：正确性 + 页读次数（磁盘 I/O 对比的实证基础）。

被测接口（契约）：
    bplus.paged.PageFile(path, pool=None)
        .read_page(pid) -> bytes  # 恰好 4096 字节，读不到抛 PageError
        .write_page(pid, data)    # data 必须 4096 字节
        .alloc_page() -> int
        .stats -> {"reads", "writes"}
    bplus.paged.BufferPool(page_file, capacity=64)
        .get(pid) -> bytes        # LRU；命中计 hits，未命中计 misses 并真读盘
        .put(pid, data)
        .clear()
        .stats -> {"hits", "misses", "capacity", "size"}
    bplus.paged.PagedBPlusTree(path, pool_size=64)
        .insert(key:int, value:int) -> bool
        .search(key:int) -> int        # 不存在抛 KeyError
        .range_scan(lo, hi) -> list[tuple[int,int]]
        .height -> int
        .stats -> dict 含 page_reads / page_writes / pool_hits / pool_misses
        .clear_pool()
        .close()
    bplus.naive_bst.PagedBST(path)
        .insert(key:int, value:int)
        .search(key:int) -> int
        .height -> int
        .stats / .close()

为什么必须有"朴素页式 BST"这个对照组
------------------------------------
光说"B+ 树 I/O 少"是空话。对照组把**同一个 key 集、同一种 4KB 页、同一套 pread 计数**
用在"每个节点占一页"的二叉树上，直接量出两者每次查找的页读次数差多少倍。
"""


import pytest
from bplus.naive_bst import PagedBST
from bplus.paged import BufferPool, PagedBPlusTree, PageError, PageFile

PAGE = 4096


# --------------------------------------------------------------------------- #
# 页文件 / 缓冲池
# --------------------------------------------------------------------------- #
def test_page_file_roundtrip_and_stats(tmp_path):
    path = tmp_path / "pages.dat"
    pf = PageFile(str(path))
    try:
        p0 = pf.alloc_page()
        pf.write_page(p0, b"a" * PAGE)
        assert pf.read_page(p0) == b"a" * PAGE
        stats = pf.stats
        assert stats["reads"] == 1
        assert stats["writes"] >= 1
        with pytest.raises(PageError):
            pf.write_page(p0, b"too short")
        with pytest.raises(PageError):
            pf.read_page(999)  # 未分配页
    finally:
        pf.close()


def test_buffer_pool_lru_hits(tmp_path):
    path = tmp_path / "pool.dat"
    pf = PageFile(str(path))
    try:
        pid = pf.alloc_page()
        pf.write_page(pid, b"x" * PAGE)
        pool = BufferPool(pf, capacity=2)
        pool.get(pid)
        pool.get(pid)
        assert pool.stats["hits"] == 1
        assert pool.stats["misses"] == 1
        pool.clear()
        assert pool.stats["size"] == 0
        assert pool.get(pid)[:1] == b"x"
        assert pool.stats["misses"] == 2
    finally:
        pf.close()


# --------------------------------------------------------------------------- #
# 页式 B+ 树
# --------------------------------------------------------------------------- #
@pytest.fixture()
def tree(tmp_path):
    t = PagedBPlusTree(str(tmp_path / "bpt.idx"), pool_size=16)
    try:
        yield t
    finally:
        t.close()


def test_paged_tree_empty(tree):
    assert tree.height == 1
    with pytest.raises(KeyError):
        tree.search(1)
    assert tree.range_scan(0, 100) == []


def test_paged_tree_insert_search(tree):
    for i in range(1000):
        tree.insert(i, i * 3)
    for i in range(1000):
        assert tree.search(i) == i * 3
    with pytest.raises(KeyError):
        tree.search(5000)
    assert tree.height >= 2


def test_paged_tree_ordered_scan_and_many_pages(tree):
    keys = list(range(0, 5000, 2))
    for k in keys:
        tree.insert(k, -k)
    assert tree.range_scan(None, None) == [(k, -k) for k in keys]
    assert tree.range_scan(100, 110) == [(k, -k) for k in range(100, 111, 2)]
    # 5000 条 × 每页最多 255 键 → 至少 20 个叶子页
    assert tree.stats["page_writes"] >= 20


def test_paged_tree_search_costs_height_page_reads(tree):
    """清空缓冲池后，一次查找的页读次数必须 <= 树高 + 1（这是 B+ 树的全部意义）。"""
    for i in range(20000):
        tree.insert(i, i)
    tree.clear_pool()
    before = tree.stats["page_reads"]
    tree.search(12345)
    reads = tree.stats["page_reads"] - before
    assert reads <= tree.height + 1, f"读到 {reads} 页，树高只有 {tree.height}"


def test_paged_tree_persistence(tmp_path):
    path = str(tmp_path / "persist.idx")
    t = PagedBPlusTree(path, pool_size=8)
    for i in range(2000):
        t.insert(i, i * 7)
    t.close()

    t2 = PagedBPlusTree(path, pool_size=8)
    try:
        for i in range(2000):
            assert t2.search(i) == i * 7
        assert t2.range_scan(1990, 1999) == [(i, i * 7) for i in range(1990, 2000)]
    finally:
        t2.close()


def test_paged_tree_pigeonhole_holes(tmp_path):
    """稀疏 key（大间隔）也要能正确分裂。"""
    t = PagedBPlusTree(str(tmp_path / "sparse.idx"))
    try:
        ks = [i * 1000003 for i in range(3000)]
        for k in ks:
            t.insert(k, 1)
        for k in ks:
            assert t.search(k) == 1
        assert t.range_scan(ks[10], ks[20]) == [(k, 1) for k in ks[10:21]]
    finally:
        t.close()


# --------------------------------------------------------------------------- #
# 朴素页式 BST（对照组）
# --------------------------------------------------------------------------- #
def test_naive_bst_basic(tmp_path):
    b = PagedBST(str(tmp_path / "bst.idx"))
    try:
        for k in [50, 30, 70, 20, 40, 60, 80]:
            b.insert(k, k * 2)
        for k in [20, 30, 40, 50, 60, 70, 80]:
            assert b.search(k) == k * 2
        with pytest.raises(KeyError):
            b.search(1)
        assert b.height >= 3
    finally:
        b.close()


def test_naive_bst_uses_more_page_reads_than_bplus(tmp_path):
    """同 8000 个 key：BST 每次查找的页读次数必须明显多于 B+ 树。"""
    import random

    keys = list(range(8000))
    insert_order = keys[:]
    random.Random(1).shuffle(insert_order)  # 顺序插有序 key 会退化成链表，那是另一个话题

    bst = PagedBST(str(tmp_path / "cmp_bst.idx"))
    btree = PagedBPlusTree(str(tmp_path / "cmp_bpt.idx"), pool_size=8)
    try:
        for k in insert_order:
            bst.insert(k, k)
        for k in keys:
            btree.insert(k, k)

        bst.clear_pool()
        before = bst.stats["page_reads"]
        for k in keys[:200]:
            bst.search(k)
        bst_reads = (bst.stats["page_reads"] - before) / 200

        btree.clear_pool()
        before = btree.stats["page_reads"]
        for k in keys[:200]:
            btree.search(k)
        bpt_reads = (btree.stats["page_reads"] - before) / 200

        assert bst_reads > bpt_reads * 3, f"BST {bst_reads:.1f} 页/查 vs B+ {bpt_reads:.1f} 页/查，差距不够"
    finally:
        bst.close()
        btree.close()
