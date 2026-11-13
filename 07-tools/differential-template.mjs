// 差分测试模板 —— 复制到目标项目旁边，改 3 处就能跑
//
//   1) IMPORT：把「原版」和「你的重写」都 import 进来
//   2) capture：决定比什么（返回值 / 抛出的错误 / 副作用序列）——只比可观察行为，不比内部结构
//   3) scenarios：一条 test 一个场景；**边界与守卫要多于正常路径**
//
// 跑法：node --test 本文件
// 依赖：node:test + node:assert/strict，零安装

import { test } from "node:test";
import assert from "node:assert/strict";

// ↓ 1) 改这两行
import * as upstream from "./UPSTREAM.mjs";
import * as mine from "./MINE.mjs";

// ↓ 2) 改这一处：目标库怎么构造实例
function make(ctxModule) {
  return ctxModule.createSomething?.() ?? ctxModule;
}

// 关键：每边都重新构造一次场景。
// 副作用数组、闭包、计数器不能放在共享对象上——否则上游跑完的副作用会串进你的实现，
// 表现成「我这边一次都没被调用」，让人误以为是自己的 bug（2026-11-13 实测踩过）。
async function capture(mod, scenario) {
  const ctx = make(mod);
  const events = []; // 每次新建
  try {
    return { ok: true, value: await scenario(ctx, mod, events), events };
  } catch (error) {
    return { ok: false, name: error.name, message: error.message, events };
  } finally {
    await ctx?.dispose?.();
  }
}

async function diff(name, scenario) {
  const [a, b] = await Promise.all([capture(upstream, scenario), capture(mine, scenario)]);
  assert.deepEqual(b, a, name);
}

// ↓ 3) 场景：正常路径
test("基本往返", () =>
  diff("basic", async (ctx) => {
    await ctx.set?.("k", 1);
    return await ctx.get?.("k");
  }),
);

// 场景：边界与守卫（这一类比正常路径更值钱）
test("非法输入抛同样的错", () =>
  diff("guard", async (ctx) => {
    await ctx.set?.("a:..:b", 1); // 期望两边抛同样的 message
  }),
);

test("不存在的 key 返回同样的空值", () =>
  diff("missing", async (ctx) => [await ctx.get?.("nope"), await ctx.has?.("nope")]),
);

// ---- 写完之后必做：变异验证 ----
// 故意把实现改坏一处（删一行判断、改一个默认值），跑一遍应当**精准挂掉对应那条**，再改回来。
// 全绿不算数，改坏了还不挂才说明这组用例是摆设。
//
// 三个高频坑：
//   ① 场景对象必须每边新建（见上）；
//   ② deepEqual 比 Blob / Stream / Promise 实例会挂 —— 先归约成 "[Blob]"、`await` 展开再比；
//   ③ 异步函数里 return 一个 Promise 数组会把 Promise 的内部符号带进比较结果。
