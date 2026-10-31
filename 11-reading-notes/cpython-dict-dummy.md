# 读码笔记 · CPython dict 的 dummy 槽位

- 日期：2026-10-31
- 仓库：`D:\work\repos\cpython`（`--depth 1 --filter=blob:none --sparse`，19.9 MB，HEAD `3fb88e9`）
- 文件：`Objects/dictobject.c`（269,008 B / 8,652 行）+ `Objects/dictnotes.txt`（6,226 B）
- 起因：路线图「会读」第三项 —— 搞清 dict 删除时为什么留 dummy 而不是直接清空
- 纪律：**只读不改**（CPython 的 AI 工具政策针对提交改动，阅读分析不涉）

---

## 一、四种槽位

文件头 66-89 行讲得很清楚，dict 的每个槽位只有四种状态：

| 状态 | 标记 | 含义 | 能变成 |
|---|---|---|---|
| Unused | `DKIX_EMPTY = -1` | 从没被占过 | Active |
| Active | `index >= 0` | 正占着 (key, value) | Dummy / Pending |
| Dummy | `DKIX_DUMMY = -2` | 曾经占过，已删除，**还没被覆盖** | Active |
| Pending | `index >= 0` 且 value 为 NULL | split 表专用，还没插入 | Active |

关键那句话在 81-83 行：

> Dummy slots cannot be made Unused again else the probe sequence in case of collision would have no way to know they were once active.

翻译：**墓碑不能变回空地**。因为开放寻址法靠"撞到空地就停"来判断"这个 key 不存在"。要是把墓碑恢复成空地，探测链就在中间断掉了，后面的元素会被判成不存在。

这个我预期到了，不意外。

意外的是后面三处。

---

## 二、删除到底做了什么

`delitem_common()`（2933-2974 行）：

```c
STORE_USED(mp, mp->ma_used - 1);            // ① 活跃数减 1
...
dictkeys_set_index(mp->ma_keys, hashpos, DKIX_DUMMY);   // ② 索引槽写成墓碑
ep = &DK_ENTRIES(mp->ma_keys)[ix];
old_key = ep->me_key;
STORE_KEY(ep, NULL);                        // ③ entries 里的 key 清空
STORE_VALUE(ep, NULL);                      //     value 清空
STORE_HASH(ep, 0);                          //     hash 清空
```

只动了三样东西：**used 减 1、indices 写墓碑、entries 里的内容清空**。

**没动的**：`dk_nentries`（entries 数组用到哪一格）和 `dk_usable`（还能插多少个全新槽）。

这两个计数器不动，是整个设计的关键。

---

## 三、取舍一：我原本会加一个"墓碑计数器"

**我的写法**：删除时 `tombstones++`，当 `tombstones > used` 就重建表。这是教科书上的标准做法。

**CPython 的写法**：**根本不统计墓碑**。

因为 `dk_usable` 已经隐含表达了"这张表还能接受多少次插入"：

- 每次插入：`dk_usable--`、`dk_nentries++`（1940-1941 行，**无条件**，跟 indices 那个位置原来是空还是墓碑无关）
- 删除：**不扣也不加**

所以"没配额了"就是 `dk_usable <= 0`（1914 行），此时 `insertion_resize()` 扩容——而 resize 顺手把墓碑全清掉（下节）。

**省掉了一个计数器，也省掉了一整套阈值判断**。代价是 `dk_usable` 变成"必须显式维护"的量，不能从 `nentries` 反推。

> 我第一稿写成「插入到墓碑不扣配额」，这是错的。被 `is_unusable_slot`（下节）误导了——墓碑可复用指的是**indices 那个位置**能写新 entry，不是「省掉一次配额」。配额是插入次数，一律照扣。

---

## 四、取舍二：墓碑只在 resize 时被清，而且清得很省

`insertion_resize()` 里的复制逻辑（2295-2305 行）：

```c
if (oldkeys->dk_nentries == numentries) {
    memcpy(newentries, oldentries, numentries * sizeof(PyDictKeyEntry));   // 快路径
}
else {
    PyDictKeyEntry *ep = oldentries;
    for (Py_ssize_t i = 0; i < numentries; i++) {
        while (ep->me_value == NULL)    // ← 跳过墓碑，直接往前挪
            ep++;
        newentries[i] = *ep++;
    }
}
```

两件事：

1. **墓碑不存在于新表里**——复制时 `while (me_value == NULL) ep++` 把它们跳过去，新表 nentries 等于 used，一个墓碑都不剩。
2. **有快路径**：如果老表本来就没墓碑（`dk_nentries == numentries`），直接 `memcpy` 整块，一个字节一个字节地搬都不用判断。

**我的写法**会老老实实遍历一遍、判空、再写入。CPython 多花一行 `if`，换掉了常见情况下整个循环的判断开销——因为"没墓碑"恰恰是最常见的情况。

这是我在 B+ 树那片学过的同一招：**把最贵的那条路径，变成最不常走的那条**。

---

## 五、取舍三：`usable` 不是算出来的，是数出来的

这条最让我意外。

`popitem()` 删最后一个元素时（5080-5089 行）：

```c
dictkeys_set_index(self->ma_keys, j, DKIX_DUMMY);
...
/* We can't dk_usable++ since there is DKIX_DUMMY in indices */
STORE_KEYS_NENTRIES(self->ma_keys, i);      // nentries 减到 i
STORE_USED(self, self->ma_used - 1);
```

`dk_nentries` **减了**（因为是 LIFO，entries 尾部那格真的空出来了），但**故意不给 `dk_usable` 加回去**——注释就一句话：indices 里还留着墓碑。

为什么不能加？因为 `dk_usable` 的语义不是"entries 数组还剩几格"，而是"**还能插入多少个全新槽**"。那个位置的 indices 仍是 `DKIX_DUMMY`，对探测链来说它**仍然被占着**。要是 `usable++`，下一次插入会以为有多余空间，而实际上 indices 里没有空位可放。

**这说明我脑子里那个等式——`usable = USABLE_FRACTION(size) - nentries`——是错的。**

它只在"刚 resize 完、还没删除过任何元素"的时候成立。之后每次 popitem 都会让 `usable + nentries < USABLE_FRACTION(size)`。

**教训**：凡是这种"看起来能推出来"的计数器，只要代码里有一处 `// can't ++ since ...` 的注释，就说明它被当成**显式状态**在维护，不能反推。

---

## 六、免费线程版：差别的全部就在一个宏里

84-85 行：

> In free-threaded builds dummy slots are not re-used to allow lock-free lookups to proceed safely.

"不复用"到底改在哪一行？我一开始以为是插入逻辑里一大段 `#ifdef`，结果只有 8 行（1867-1875）：

```c
static inline int
is_unusable_slot(Py_ssize_t ix)
{
#ifdef Py_GIL_DISABLED
    return ix >= 0 || ix == DKIX_DUMMY;   // 免费线程版：墓碑也算占着
#else
    return ix >= 0;                        // GIL 版：墓碑算空着
#endif
}
```

整个 `find_empty_slot()`（1880-1894）就是靠它决定要不要继续往下探：

```c
size_t i = hash & mask;
Py_ssize_t ix = dictkeys_get_index(keys, i);
for (size_t perturb = hash; is_unusable_slot(ix);) {   // ← 全部逻辑就在这个条件里
    perturb >>= PERTURB_SHIFT;
    i = (i*5 + perturb + 1) & mask;
    ix = dictkeys_get_index(keys, i);
}
return i;
```

- **GIL 版**：只有 Active（`ix >= 0`）算占着 → 碰到 `DKIX_DUMMY` 就停下，**直接往墓碑格写新 entry**
- **免费线程版**：Active 和 Dummy 都算占着 → **跳过往碑**，一路找到真正的空地

所以「复用墓碑」复用的是什么：**indices 里的那个位置**。entries 数组照样往后长、配额照样扣。

为什么免费线程版不能复用，我能推出来：无锁查找时，一个读线程可能已经看到了 `DKIX_DUMMY`，并据此判断"这里曾经有元素、继续往下探"。如果另一个线程正把那一格改成 Active 并写入新 key，读线程可能读到半成品，或者得出错误结论（提前停止 / 匹配错 key）。

所以它选择**永不复活墓碑**，代价是探测链变长、indices 里躺着的墓碑更多。

这是我第一次在真实代码里看到：**同一个数据结构，因为并发模型不同，"正确"的写法就变了**——而且改动小到只有 5 行。不是配置开关那种不同，是策略层面的不同。

我造 B+ 树那会儿完全没考虑过这个维度：单线程跑通了就觉得对了。

---

## 七、如果让我改我自己的 B+ 树

我那片 B+ 树的删除是页面级的：叶子页里摘掉 key，页空了就合并、从父节点里摘指针。**没有墓碑这个概念。**

它现在能跑，是因为有个隐含前提：**读的时候没人写**。

P4-live 那个「真实并发」要求如果真加上去，第一个要拆的就是这里——删除时如果直接压缩页内 slot，正在扫描的读者会看到「怎么突然少了一格」，扫到一半的游标可能跳过一个 key。

CPython 给出的方案可以照抄三条：

1. **删除只改标记，不动数据布局**——`DKIX_DUMMY` 写进 indices，entries 里的格子还留在原地
2. **物理清理只在 resize 时统一做**——一次遍历跳着复制，顺带把墓碑全挤掉，还有 `memcpy` 快路径
3. **标记一旦写下，永不撤销**——GIL 版能「复用」，复用的是 indices 那一格的位置，不是把它变回空地

合起来就是「**延迟清理 + 单向标记**」。我的 B+ 树要支持并发读，大概率也得走这条路：删 key 只写墓碑，页真正空了才在写路径上回收。

而我之前没算的那笔账是：**墓碑占着 indices，探测链变长，读会变慢**。这是并发安全的价码，不是白送的。

「扛」这件事，大概就是开始算这种账。

## 八、查不到的部分

`USABLE_FRACTION(n) = (n << 1) / 3`（590 行）为什么是 2/3？

注释（580-588 行）说：

> Fractions around 1/2 to 2/3 seem to work well in practice.

**"seem to work well in practice"——经验值，没有推导。** 这话比我在 httpx 那边看到的 `MAX_URL_LENGTH = 65536` 诚实多了：那边连"这是经验值"都没写，这边至少承认了自己是拍出来的。

我原本以为会看到一个基于探测长度的数学论证，结果是一句"实践中 1/2 到 2/3 都行得通"。

这也算收获：**不是所有常量背后都有推导，有的是试出来的**。区别只在于，诚实的代码会告诉你"这是试的"。

---

## 八、这篇和上一片的关系

读 httpx 那篇，我看到的是"**等价关系的定义**"——什么差异该留、什么该消。

读这篇，看到的是"**状态的取舍**"——一个被删掉的槽位，是变回空地、变成墓碑、还是干脆重建整张表。

两者共同点是：**作者做的每一个决定，都在回答"如果不这样会出什么事"**。

- httpx：不区分 `?` 和空 query → 缓存击穿
- CPython：墓碑变回空地 → 探测链断掉，元素"消失"
- CPython：`usable++` 而不检查 index → 下次插入写到空位上，覆盖活元素

我造东西的时候答的是"这样能跑通"。这两篇读完，我大概知道"扛"的那部分要问什么了。
