# ofetch 1.5.1：一个请求是怎么发出去的

## 第三个对象：ofetch 1.5.1（349 行核心）

选它是因为它比 hookable 更接近「我每天在用的东西」——发请求、拼参数、处理错误、重试。
npm 包只有 `dist/`（`shared/ofetch.CWycOUEr.mjs` 349 行），跑起来还要 `destr` 和 `ufo`：
我把两个依赖也下下来手工拼了个 `node_modules`，这样能 `import` 原版、跑差分。

### 四个值得抄的设计

**1. 一个可变 ctx 贯穿全程。** `{ request, options, response, error }` 从进函数到返回都是同一个对象，
钩子拿到的就是它、改的也是它——`onRequest` 里改 `ctx.options.headers`，后面的代码直接生效。不用回调返回值层层传递。

**2. 错误对象用 defineProperty 惰性挂载。** `err.data` / `err.status` / `err.response` 都是 getter，
取值时才去 `ctx.response` 上拿。好处是抛出时不用复制响应对象，也不会因为 `catch` 里没读就白算一遍。

**3. 重试写在错误处理里，不写在外层循环。**
`onError(ctx)` 判断 `retry > 0 && 状态码在重试集合里` → `return raw(ctx.request, {...ctx.options, retry: retry - 1})`。
好处：钩子能在 `onRequestError` / `onResponseError` 里介入，重试对钩子是可见的；
坏处：**重试会重新跑一遍 `onRequest`**，钩子里有非幂等副作用就会重复执行。这是真取舍，不是纯优点。

**4. 两处「顺序约束」值得记。**
- `onRequest` 跑完之后**必须**把 headers 重新包成 `Headers` 实例——因为钩子可能把它换成普通对象；
- `query` 拼进 URL 之后**必须** `delete options.query`，否则下次复用同一份 options 会重复拼参数。

### 我砍掉了什么（写清楚，免得「等价」说大话）

stream body（`pipeTo`/`pipe` 与 `duplex: "half"`）、旧版 fetch 的 `_bodyInit` 兼容、
`$fetch.create` 里 globalOptions 的合并细节。这三块没复刻，也不在差分覆盖面内。

### 等价性证据

20 条差分用例：`(本地实验目录)\work\differential.test.mjs`，同一组场景跑上游与我的实现，比
「发出去的请求（url/method/headers/body）+ 返回值 + 抛出的错误（name/message/status/data）+ 钩子调用序列」。
`node --test differential.test.mjs` → **20/20**。

然后是变异验证（这一步比全绿重要）：故意改坏两处——忽略 `parseResponse`、去掉 HEAD 判断——**精准挂掉对应的两条**，
改回来 20/20。证明这 20 条不是摆设。

### 踩的坑

- `assert.deepEqual` 比两个 `Blob` 实例会挂：改成只记录 `"[Blob]"`，比类型不比内容。
- 差分测试里两边的场景对象**必须是工厂函数每次新建**：我第一次把 `seq` 数组放在共享对象上，
  上游跑完的副作用串到了我的实现里，表现为「我这边的钩子一次都没调用」。

### 能用在哪

1. 自己写请求封装时：ctx + 钩子 + 惰性错误属性这一套，比「传一堆回调参数」好维护。
2. 判断「这个库为什么这么设计」时：先找它的顺序约束（什么必须在什么之后），再看它砍了什么。
