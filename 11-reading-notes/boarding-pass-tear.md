# boarding-pass：一个「撕票」组件，教了我四件和我以为不一样的事

> 仓库：<https://github.com/jal-co/boarding-pass>（MIT，59 stars，13 个源文件 / 484 行）
> 本地 clone：`D:\work\repos\boarding-pass`（`--depth 1`）
> 读于 2026-11-09。用户说它「好像是关于建模方面的」——**它不是建模工具**，先把这个说清楚。

---

## 一、它到底是什么（先纠正一个前提）

`api.github.com` 的 description 原话：**"An interactive tear-off boarding pass built with React, Motion, and DialKit."**

它是**一张登机牌，可以拖着把右边的票根「撕」下来**：纸质纤维一条条断开、断开后票根会歪在一边、可以按键盘撕、可以重置回去。用 React + Motion（framer-motion）+ DialKit（实时调参面板）做，跑在浏览器里。

**不是 3D 建模**。撕纸的「立体感」是 DOM 的 `clip-path` 多边形 + `transform` 倾斜做出来的，全程 2D。抖音上怎么介绍它我不知道，但**仓库本身没有一个 3D 库、没有 mesh、没有建模文件**（`src/` 下全是 `.tsx`/`.ts`/`.css`，另有两个 woff2 字体和三个 svg 占位 logo）。

先说这个，是因为**「它是什么」决定了「它能不能变成我的能力」**——如果是 3D 建模那我只用学工具；如果不是，我要学的是它做交互的那套做法。

---

## 二、四条真正的技术点（带行号）

### 1. 所有视觉状态都是 `progress` 的纯函数——这是「可测试」的根

`src/boarding-pass/BoardingPass.tsx:66-69`：

```ts
const torn = progress >= 1
const release = detach
const angle = Math.min(swing, 4) * progress * (1 - release) + restOffset.angle * release
const lift = progress * .2 + release * .3
```

`progress`（撕开量 0~1）和 `detach`（释放量 0~1）是**受控 props**，组件自己不藏任何「撕到哪了」的内部状态。断了几座桥、倾斜多少度、抬多高——全是这两个数的算式。

`src/boarding-pass/tear.ts:114-116`：

```ts
export function brokenBridges(progress: number) {
  return Math.min(bridges.length, Math.floor(progress * bridges.length + 1e-6))
}
```

**26 座纸桥**（`tear.ts:109-112` 生成），撕到 50% 就断 13 座。没有状态机、没有动画中间态记录。

> **我原本会怎么做**：用 `useEffect` + `setState` 维护「第几座桥断了」，再配 `AnimatePresence` 让桥逐个消失。
> **它为什么更好**：状态只有一个真源，任何时刻的界面都能由 `progress` 复原；测试不用等动画结束，读一个数就行。

### 2. 用 `data-*` 属性当测试钩子，而不是 window 上的对象

`BoardingPass.tsx:140`：

```tsx
<div className="boarding-pass"
     data-broken-bridges={brokenBridges(progress)}
     data-tear-progress={progress.toFixed(2)}
     data-detached={detach >= 1}
     data-reduced-motion={reducedMotion}>
```

`tests/boarding-pass.spec.ts:17-20` 直接读属性：

```ts
const partial = Number(await pass.getAttribute('data-tear-progress'))
expect(partial).toBeGreaterThan(0)
expect(partial).toBeLessThan(1)
```

**这是我最近才在做的事，但它做得更干净**——我的雨夜便利店是 `window.__RAINY__ = { ready, progress(), stats() }` 挂全局对象；它是把状态**写在它所在的那个 DOM 节点上**。差别很实际：

- 全局对象要自己管生命周期（页面重载、React 重渲染时会不会丢？）
- DOM 属性天然跟着元素走，Playwright 一句 `getAttribute` 就能读，CDP 也能读
- 属性名本身就是文档，看 DOM 就知道这个组件暴露了什么

### 3. 物理感是「算好的曲线」，不是物理引擎

`tear.ts:52-60`：

```ts
function edgePoints(profile, progress, amplitude, edge, from, to) {
  const front = progress * passHeight
  return profile.flatMap((offset, index) => {
    const y = index * tearStep
    if (y < Math.max(notchRadius, from) || y > Math.min(passHeight - notchRadius, to)) return []
    const x = y <= front ? edge + offset * amplitude : edge   // ← 只在已撕开的部分偏移
    return [`${x.toFixed(2)}px ${y}px`]
  })
}
```

撕开的边缘不规则，未撕开的部分是直线——**一个三元表达式就区分了**。`bridgePath()`（`tear.ts:118-126`）把还没断的桥用 `Math.cos/sin` 按 `angle` 翻转，看起来像被拉弯了。

**全程没有物理引擎、没有 spring 求解器**。手的位置是 `motion.div` 的 `animate={{ x: hand.x, y: hand.y }}`，桥的角度是一个乘法。

> **我原本会怎么做**：想「要逼真得有物理引擎吧」，然后去装 rapier / cannon。
> **它证明了什么**：**「看起来有物理感」= 参数曲线选得好 + 确定性**。物理引擎解决的是「碰撞和约束我算不准」，不是「看起来真不真」。

### 4. 确定性伪随机：同一个 seed 永远同一个结果

`tear.ts:13-22`：

```ts
function seededRandom(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
function hash(seed: string) { /* FNV-1a，字符串 → seed */ }
```

撕边要「不规则」，但**不规则必须每次都一样**——不然 React 重渲染时撕边会抖动。所以用 `seededRandom(7)` 生成 281 个偏移量，存进 `tearProfile()`（`tear.ts:34-46`），用的时候直接查。

> **我的场景里有同样的问题**：货物摆放、雨滴初始位置、撕边——我都用 `Math.random()`，**每帧/每次重建都不一样**。这条可以直接搬。

---

## 三、我吸收了哪几条，哪些明确不要

| # | 吸收什么 | 用在哪 | 判据 |
|---|---|---|---|
| 1 | **状态收成一个纯函数** `stateFromProgress(p)` | 雨夜便利店的组装动画（现在灯光/雨/元素各自 `if (t > delay)` 散着） | 验证器能只读一个数就知道整场状态 |
| 2 | **`data-*` 属性当契约钩子** | `verify.mjs` 现在读 `window.__RAINY__`，可以改成读 DOM 属性 | 一个 `getAttribute` 能读到，就不用管全局对象 |
| 3 | **确定性随机（seededRandom）** | 货物摆放 / 雨滴初始 / 任何「看起来随机但要稳定」的地方 | 重建页面后布局不变 |
| 4 | **物理感靠曲线不靠引擎** | 判断「要不要引物理引擎」时 | 先问「我是不是只需要一条参数曲线」 |

**明确不要的**：
- **DOM 撕纸的 CSS `clip-path` 写法**——我做的是 Three.js/3D，这条用不上（除非以后做卡片类交付）
- **DialKit**——它是「实时调参面板」，我调 3D 参数用 CDP eval 就够，不需要引入一个 UI 框架
- **整个组件**——它是 React 组件，我不做 React 应用，装它没有意义

---

## 四、最重要的一条（比上面四条都值钱）

**「可测试」不是测试写得好，是状态设计得好。**

它 94 行测试能覆盖「拖 95px → progress 在 0~1 之间」「回拉到 20px → progress 不变（不可逆）」「Enter 键 → 同样的终态」「reduced-motion + 390px 窄屏」——**因为组件把状态全暴露成 `progress` 和 `detach`**。测试不用模拟鼠标轨迹的物理结果，只需读两个数。

我这两天在雨夜便利店上栽的坑正好是这个的反面：验证器要验「入场动画」，样本是 `setTimeout` 采样 + 事后插值补洞——**因为我的状态不是一个数，是一堆 `if (t > delay)` 的派生物**。

> **判据（可以推广到任何交付物）：如果一个交付物的状态不能被压缩成「一两个 0~1 的数」，那它就没法被自动验证，只能靠人看图。**

---

## 五、诚实边界

1. **没跑过它**。只读了代码和测试文件，没 `npm install` / `npm run dev` —— 所以「撕起来手感如何」我不知道，只读了实现。
2. **没做 A/B**。「用 data-* 属性比 window 对象好」是我读代码推的，**没有在我自己的 verify.mjs 上实测过**——在我的语境里可能反而不便（Three.js 页面 `window.__X__` 一次给一堆数据，DOM 属性要挂几个节点上）。
3. **`swing` / `amplitude` / `radius` 这些参数的最优值我没动**——它默认值为什么是 4、0.2、0.3，我没查。
4. **它 2026-09-08 之后没更新过**（`pushed_at` 同 `created_at`），所以它不是一个在演进的库，是一个**展示型作品**——学它的做法，别指望它持续维护。

---

## 六、一句话

**它不是建模工具，是一个「把连续交互做成可测试组件」的样板；它教我的最重要一件事不是撕纸，是「状态收成一个数」。**
