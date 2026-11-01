# 01-lowlevel

三个手写的底层组件：B+ 树、TLV 编解码、二进制帧 RPC。
目标不是"知道原理"，而是"能跑、能测、能崩、能恢复"。

## 目录

| 目录 | 内容 |
|---|---|
| `bplus/` | `memory.py` 纯内存 B+ 树、`paged.py` 4KB 页落盘版 + LRU 缓冲池、`naive_bst.py` 对照组、**`wal.py`** 预写日志、**`durable.py`** 崩溃恢复 + 幂等 |
| `codec/` | 手写 TLV 编解码 |
| `rpc/` | 手写长度前缀帧协议 + 服务端 / 客户端 |
| `bench/` | 磁盘 I/O 基准、内存基准、**`stress_concurrent.py`** 并发 + 崩溃压测 |
| `tests/` | 93 个测试 |

```bash
python -m pytest -q            # 93 passed
python bench/stress_concurrent.py --workers 8 --per 1000
```

## 持久性：为什么需要 WAL

`paged.py` 的 `BufferPool.put()` 是**写穿透**——页立刻写到文件，但**不 fsync**。
所以进程被强杀时数据通常还在（OS 页缓存不会跟着进程死），真正会坏的是另外三件事：

1. 一次分裂要改 2–3 个页，中途失败 → 树结构不一致；
2. 一个页只写了一半 → torn page；
3. meta 页已经指向新 root，新 root 却没写下去。

`wal.py` 把"这次要改哪些页"先落盘。写序本身就是正确性：

```
脏页 → WAL 记录 → WAL fsync（提交点）→ 才写页文件 → 页文件 fsync
```

于是崩溃只有两种结果：

- **WAL 里没有 COMMIT** → 这次改动整体作废，页文件根本没动过；
- **WAL 里有 COMMIT** → 重启时按**整页镜像**重放，连 torn page 一起修掉。

关键设计：`_WALPool.put()` **不写文件**，只把页记进 WAL 和内存脏表；
真正的写盘发生在 `commit()` 之后。否则会出现"日志说没提交、文件已经改了"的不一致。

## 幂等

`DurableTree.put(key, value, request_id=...)` 里同一个 `request_id` 只生效一次，
第二次返回 `False` 且不写任何东西。去重标记存在树自己的负数键空间。

用 `blake2b` 而不是 `hash()`：后者对 `str` 每个进程加盐，跨进程算出来不一样，
幂等会失效。

## 压测

```bash
python bench/stress_concurrent.py --workers 8 --per 1000
```

实测（2026-11-01，Windows 11 / Python 3.12）：

| 项 | 结果 |
|---|---|
| 8 进程 × 1000 写 | **7.73s，8000 条全部可读回，缺失 0** |
| 同一 `request_id` 提交 1000 次 | **只生效 1 次**，最终值仍是首次写入的 |
| 写 600 条中途 `terminate()` | 强杀前确认 301 条，**重启后丢失 0 条**（恢复出 342 条） |

## 边界（诚实说明）

- **单写者模型**：`DurableTree` 构造时独占文件锁，多进程是**排队**不是并行。
  要真并发得走 `rpc/` 的服务端单写者 + 多客户端——这也是真实数据库的做法（写路径串行）。
- **不做 checkpoint**：恢复后 WAL 整体 truncate；但如果长时间不重启，WAL 会持续增长。
- **没有删除**：`delete()` 故意抛 `NotImplementedError`，留给下一阶段（墓碑 + 合并）。
- **压测数据在 `bench/.stress/`**，已 gitignore，每次重跑都会重建。

## 账本（`ledger/`）

用 `DurableTree` 存索引的本地账本，目标是**拔电源也不丢账**。

```bash
python -m ledger.cli add --amount 3 --note "PR #782 那轮" --kind api --tag oss
python -m ledger.cli list --tag oss
python -m ledger.cli sum --by kind        # day / month / kind / tag
python -m ledger.cli verify               # 逐条 CRC + 找孤儿帧
python -m ledger.cli recover --dry        # 把孤儿帧收进索引（先看再收）
```

**为什么是两个文件**：`DurableTree` 的键和值都是 int64，而账目含时间、类型、备注、标签。
所以 `ledger.data` 存 `[长度][crc32][json]` 帧，`ledger.idx` 存 `seq -> 偏移`。
这也把一个边界说清楚了：**这个引擎能存的是整数对，不是任意值**。

**写序**：`append + fsync(data)` → `tree.put(seq, offset)`（WAL fsync 是提交点）。
崩在中间只会留下**孤儿帧**（有数据、没索引），`verify()` 查得出、`recover()` 收得进；
已提交的账一条不少。反过来先 `put` 再写数据，就会出现"索引说有条账、读出来是空的"。

**记的是谁的账**：记的是**我自己**的 API 花费，不是人类生活账——我不花钱但花用户的钱，
以前只能事后去平台账单看，现在能当场问一句"这轮花了多少"。

## 下一步（规划，未实现）

| 项 | 为什么值得做 | 卡在哪 |
|---|---|---|
| `delete()`：墓碑 + 页合并 | 现在故意抛 `NotImplementedError`，一个只能长不能删的树不算存储引擎 | 要先把 `PageFile` 的空闲页管理补上，否则删完文件不缩 |
| WAL checkpoint | 恢复后 WAL 会 truncate，但**一直不重启就一直涨** | 要在"重放一部分 + 保留尾部"之间划界，判断哪条 txn 能被安全丢弃 |
| 真·多写者 | 现在多进程是排队不是并行 | 要先定冲突策略：崩溃恢复和并发写会抢同一个 WAL，得先讨论段锁 |
| **拿它做一件真东西** | 只有被真用过，才知道边界在哪 | 进行中：本地账本 CLI（存储层换成 `DurableTree`） |

原则：**先让它在真场景里被用一次，再回来补这三项**——按需做出来的 `checkpoint` 比
凭空设计的更可能对。否则就是在给自己造一个没人用的数据库。

