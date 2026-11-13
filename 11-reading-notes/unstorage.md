# unstorage 2.0.0-beta：一套接口挂 N 个后端

## 第四个对象：unstorage 2.0.0-beta.0（核心 581 行）

前两个是「一次调用」的库，这个是**有状态、有分区**的：同一套接口下挂 N 个后端，按 key 前缀路由。
好处是这次不用手工拼依赖——`destr` 在它自己的 `_chunks/libs/` 里，直接 `import dist/index.mjs` 就能跑。

### 五个设计

**1. mount 用「最长前缀 + 排序」，不是逐段解析。**
`mountpoints` 数组在 `mount()` 时按长度降序 `sort`，`getMount(key)` 顺序找第一个 `startsWith` 命中的。
简单、O(n) 遍历，但要求每次挂载后重排——`unmount` 后不重排也不出错（剩下的仍然有序）。

**2. meta 不另开接口，用 `key + "$"` 存在同一个 driver 里。**
`setMeta("a")` 实际写 `a$`；`getMeta` 读回后把 `atime/mtime` 字符串转 Date。
代价：`getKeys()` 必须过滤掉以 `$` 结尾的 key，否则 meta 会混进业务 key 列表（`filterKeyByBase` 就干这个）。

**3. 批量操作按 mount 分组。**
`getItems/setItems` 先把每个 key 归到它所属的 mount，同一 mount 的攒成一批，一次 driver 调用；
driver 没实现 `getItems` 才退回逐个调用。这是「批量省往返」的通用做法。

**4. raw 值走单独通道。**
`getItemRaw/setItemRaw` 不经过 JSON 序列化，直接拿 Buffer/Blob/Stream；
`getItem(key, {type:"bytes"|"blob"|"stream"})` 也是走这条通道再把原始值转成对应类型。

**5. getKeys 有「遮蔽」规则。**
父 mount 列出的 key 不能盖住子 mount 已经产出的（`maskedMounts` 累积，`fullKey.startsWith(p)` 就跳过）；
`maxDepth` 只在所有 driver 都声明支持时才下推给 driver，否则在客户端 `filterKeyByDepth` 过滤。

### 我砍掉了什么

`watch`/`unwatch`（要 driver 侧 watch 接口，memory driver 没有）、`snapshot`/`restoreSnapshot`、
`bytes`/`blob`/`stream` 三种 raw 类型的完整转换（我只让 `getItemRaw` 直通）。

### 等价性证据

`(本地实验目录)\us-mine\differential.test.mjs`，20 条：基本读写 / 缺失 key / 删除 / key 归一化 /
非法 key 抛错 / getKeys / meta 读写与 `$` 过滤 / clear 前缀 / mount 与最长前缀 / 重复 mount 抛错 /
unmount 回落 / 批量读写 / raw 往返 / prefixStorage 隔离 / getMounts / ttl 过期。
`node --test differential.test.mjs` → **20/20**。

变异验证：去掉 `mountpoints.sort` 与 `$` 过滤 → 挂 3 条（mount、unmount、meta 过滤），恢复 20/20。

### 踩的坑

差分测试里我写 `results.map(async k => k)`，返回的是 Promise 数组，`deepEqual` 去比 Promise 的内部符号 →
报错信息里全是 `Symbol(async_id_symbol)`。**异步函数里返回 Promise 数组前先 await 展开**。

### 能用在哪

1. 做「多后端存储」抽象时：前缀路由 + 分组批量 + raw 旁路，这三件套能省掉很多 if。
2. 给已有接口加附属数据时：`key$` 这种「约定后缀」比加一张表简单，但要记得在枚举处过滤掉。
