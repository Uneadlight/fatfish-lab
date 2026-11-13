# hookable 6.1.2：257 行的可等待钩子系统

## 一、它解决什么问题

一个对象上挂一堆回调，调用时**按顺序执行、能等异步、能撤销、能改名**。听着简单，难在三点：

1. 全同步的路径不能平白返回 Promise（否则调用方 `if (r) r.then()` 全得改）；
2. 中间夹一个 async，后面的必须等它；错误要能中断后续；
3. 撤销要幂等（撤销两次不能把别人的也撤了）。

---

## 二、组件关系

| 部件 | 干什么 | 备注 |
|---|---|---|
| `Hookable` | 完整版：hook / once / before / after / deprecate | 主类 |
| `HookableCore` | 阉割版：只有 hook + callHook，无 before/after | 热路径用 |
| `flatHooks` | 嵌套配置拍平成 `parent:child` | `addHooks` 靠它 |
| `mergeHooks` | 多份配置合并，同名变串行组合 | 多插件聚合 |
| `serialTaskCaller` / `parallelTaskCaller` | 两种执行器 | 差别只在串行还是并行 |
| `createDebugger` | 用 before/after 记录耗时 | 示范「外用」而非内建 |

---

## 三、三个我认为最值钱的设计

### 1. 同步优先、遇 thenable 才转异步

```js
function callHooks(hooks, args, startIndex, task) {
  for (let i = startIndex; i < hooks.length; i += 1) try {
    const result = hooks[i](...args);
    if (result && typeof result.then === "function")
      return Promise.resolve(result).then(() => callHooks(hooks, args, i + 1, task));
  } catch (error) { return Promise.reject(error); }
}
```

**为什么值钱**：绝大多数 hook 是同步的，这条路径上**一个 Promise 都不造**；只有真遇到 async 才切异步，并且用递归把「剩下那截」挂到 promise 链上。

**代价**：同步抛错被 `catch` 转成 `Promise.reject`——调用方如果忘了 `.catch()`，得到的是 unhandledRejection 而不是当场崩。**这是一个有意的取舍：统一返回类型，换取调用方不用区分。** 而 `callHookParallel` 里没有这层 try/catch，同步错误就是当场抛——两种执行器的错误语义**不一致**，读的时候要留意。

### 2. 撤销靠闭包里的「活着」标志，不靠数组里的引用

```js
return () => {
  if (function_) { this.removeHook(name, function_); function_ = void 0; }
};
```

撤销两次是空操作；而 `removeHook` 用 `indexOf` 找位置、找不到就什么都不做——**不会误伤同名函数的另一个注册**（除非是同一个函数引用，那本来就该一起撤）。

### 3. 废弃改名是「重定向 + 迁移」

`deprecateHook(old, new)` 做两件事：记下 `old → new`；把 `old` 上已注册的回调**搬到 `new`** 上。之后任何 `hook("old", …)` 都会被顺链改名到 `new`，只在第一次打警告。

**为什么值钱**：插件 API 改名时，老代码不用动，也不会出现「两个名字各存一份」的分裂。

---

## 四、我重写时踩的坑

写 `hook()` 里的改名链，我第一版是：

```js
let hop;
while ((hop = this.#deprecated.get(name))) name = hop.to;   // ✗
```

循环**退出条件**会把 `hop` 赋成 `undefined`，所以后面 `if (hop && !allowDeprecated)` 永远不成立——**警告一次都不打**。差分测试当场抓到（13 条里挂了 `deprecated` 这一条）。

改成把「最后一次真实改名」留住：

```js
for (;;) { const next = this.#deprecated.get(name); if (!next) break; hop = next; name = next.to; }
```

**教训**：`while ((x = f()))` 这种写法，`x` 在退出时是被判假的那个值，不是最后一个真值。**「循环结束后的变量值」要和「循环体最后一次用的值」分开想。**

---

## 五、等价性证据

13 条差分用例，同一套用例分别跑原版与我的重写版，比较**可观察行为**（副作用顺序 / 返回值是同步还是 Promise / fulfilled 还是 rejected / 错误消息 / 警告文案与次数），全部 deepEqual：

```
cd (本地实验目录)\mine && node --test differential.test.mjs
# tests 13 / pass 13 / fail 0
```

覆盖：同步顺序、空 hook、同步夹异步、同步抛错、异步 reject、撤销幂等、once、before/after（同步与异步）、并行、并行同步抛错、废弃改名、嵌套 addHooks 与撤销。

**这比"我读懂了"硬**：读懂是自述，13 条对上才是证据。

---

## 六、我能用在哪（具体三条）

1. **插件内部的多回调**：我现在的 `dsh-papers-panel/lib/client.js` 里没有统一的事件层，加功能就得改渲染函数。下次要加「刷新后通知别的模块」时，照第 1 条写个 20 行的 hook 表即可，**不要引依赖**。
2. **改插件 API 时的平滑迁移**：给自研插件改配置项名字时，用「废弃重定向」而不是直接删旧键——旧配置仍生效、只在控制台提示一次。
3. **我自己脚本里的流水线**：`build_body.py` 那种「按顺序跑若干净、错就停」的结构，可以借它的**同步段 + 异步尾巴**写法，避免整条链被 `async` 污染。

---

## 七、复核

```bash
ls E:/DS公作区/.tmp/study/hookable/package/dist/index.mjs     # 257 行
cd E:/DS公作区/.tmp/study/mine && node --test differential.test.mjs
```

## 第二轮：拿上游的测试当尺子（2026-11-13 晚）

npm 包里没有 tests；从 GitHub 取 `test/hookable.test.ts`（493 行，走 `ghfast.top` 镜像，`api.github.com` 那个镜像走不通，raw 可以）。

官方测试的重心和我第一版不一样：我 13 条大多在测**正常路径**，它有一半在测**清理语义与守卫**——
同函数注册三次 `remove()` 只能删掉自己那一个；hook 执行中把自己注销、后续 hook 仍要跑；
空名字/非函数一律忽略；`allowDeprecated` 能压掉告警；废弃链 a→b→c 只告警一次且文案用**最终**名字；
先注册后声明废弃，已注册的回调要迁到新名字（并且**要告警**）。

6 条补成差分用例后，**挂 1 条**：先注册后废弃时我这边不告警。
根因：迁移已有回调时我顺手加了 `{ allowDeprecated: true }` 想让迁移静默，结果破坏了「废弃必须做一次告警」的契约。去掉这个参数就好了。

**这条比 bug 本身值钱**：同一批用例我先用自己实现跑 `edge.test.mjs`，6/6 全绿；改写成差分（同时跑原版）就挂了。
自测通过只证明「我自洽」，差分才证明「和原版一致」——这两个标准差着整整一层。
