/**
 * dsh-chat-background 客户端测试
 * ----------------------------------------------------------------------------
 * 用桩环境把浏览器半侧真跑一遍：
 *   ModuleLoader → factory → apply(ctx) → 设置页组件挂载渲染，
 * 并验证 0.3.0 新增的壁纸库卡片 / 弹窗交互（打开、搜索、选中、随机、重新生成、
 * 进度轮询、库缺失与接口不可用兜底）。
 *
 * 为了让交互可断言，这里手写了一个极简 React hook 运行时替身：
 *   - createElement 把元素变成普通对象 { type, props, children }
 *   - useState 有真实状态，setState 同步触发重渲染
 *   - useEffect 在每次渲染后按依赖数组触发/清理
 * 只覆盖本插件用到的 useState / useEffect，不模拟其他 React 特性。
 *
 * 运行：node test/client.test.mjs
 */
import assert from 'node:assert/strict'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const entry = join(here, '..', 'lib', 'client.js')

const STORE_KEY = 'dsh-chat-background:config'
const RUNTIME_STYLE_ID = 'dsh-chat-background/runtime.css'
const PANEL_STYLE_ID = 'dsh-chat-background/panel.css'
const API_WALLPAPERS = '/dsh-chat-bg/wallpapers'
const API_SELECT = '/dsh-chat-bg/wallpapers/select'
const API_REFRESH = '/dsh-chat-bg/wallpapers/refresh'

/* ── 桩：window / document / localStorage ─────────────────────────────── */

const store = new Map()
const styled = []
let captured = null

function matchesStyle(el, selector) {
  const m = /^style\[data-plugin-css="(.+)"\]$/.exec(selector)
  return m !== null && el.tag === 'style' && el.dataset.pluginCss === m[1]
}

globalThis.window = {
  localStorage: {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key)
  },
  __ModuleLoader__: {
    load: (definition) => { captured = definition }
  }
}

globalThis.document = {
  head: {
    appendChild: (el) => {
      el.parentNode = globalThis.document.head
      styled.push(el)
    },
    removeChild: (el) => {
      const index = styled.indexOf(el)
      if (index >= 0) styled.splice(index, 1)
      el.parentNode = null
    }
  },
  createElement: (tag) => ({ tag, dataset: {}, textContent: '', parentNode: null }),
  querySelector: (selector) => styled.find((el) => matchesStyle(el, selector)) ?? null
}

/* ── 桩：fetch（按 URL 返回 fixture）────────────────────────────────────── */

const LIBRARY_ITEMS = [
  {
    id: '1197607981',
    title: 'With the Fairies - Shadowverse (Fanart)',
    type: 'scene',
    playlistIndex: 1,
    current: false,
    tags: ['Anime'],
    filesize: 21453743,
    subscriptiondate: 1734943775,
    width: 3840,
    height: 2160,
    source: 'embedded',
    thumb: '/dsh-chat-bg/wallpaper?id=1197607981&kind=thumb',
    still: '/dsh-chat-bg/wallpaper?id=1197607981&kind=still'
  },
  {
    id: '2233445566',
    title: 'Neon City Rain',
    type: 'video',
    playlistIndex: null,
    current: false,
    tags: ['Cyberpunk'],
    filesize: 100,
    subscriptiondate: 1735000000,
    width: 1920,
    height: 1080,
    source: 'video',
    palette: { light: '#e7d9ef', dark: '#241a2e' },
    thumb: '/dsh-chat-bg/wallpaper?id=2233445566&kind=thumb',
    still: '/dsh-chat-bg/wallpaper?id=2233445566&kind=still'
  },
  {
    id: '3456595246',
    title: 'Ocean Calm',
    type: 'web',
    playlistIndex: 5,
    current: false,
    tags: ['Nature'],
    filesize: 200,
    subscriptiondate: 1700000000,
    width: 2560,
    height: 1440,
    source: 'web',
    thumb: '/dsh-chat-bg/wallpaper?id=3456595246&kind=thumb',
    still: '/dsh-chat-bg/wallpaper?id=3456595246&kind=still'
  },
  {
    id: '4455667788',
    title: 'Forest Walk',
    type: 'scene',
    playlistIndex: 12,
    current: false,
    tags: ['Nature'],
    filesize: 300,
    subscriptiondate: 1736000000,
    width: 1280,
    height: 720,
    source: 'preview',
    thumb: '/dsh-chat-bg/wallpaper?id=4455667788&kind=thumb',
    still: '/dsh-chat-bg/wallpaper?id=4455667788&kind=still'
  }
]

const HOST_CONFIG = {
  ok: true,
  imageVersion: '1024-1700000000000',
  config: {
    enabled: false,
    mode: 'color',
    colorLight: '#f3efe6',
    colorDark: '#15171b',
    imagePath: '',
    imageUrl: '',
    surfaceAlpha: 0.72,
    scrim: 0.18,
    sidebar: true
  }
}

const IMAGE_CFG = {
  enabled: true,
  mode: 'image',
  colorLight: '#f3efe6',
  colorDark: '#15171b',
  imagePath: '',
  imageUrl: '',
  surfaceAlpha: 0.72,
  scrim: 0.18,
  sidebar: true
}

/** 壁纸库接口返回体（每次调用给新对象，模拟真实 JSON 解析结果）。 */
function wallpapersPayload() {
  return {
    ok: true,
    version: '0.3.0',
    counts: { total: LIBRARY_ITEMS.length, scene: 2, video: 1, web: 1, other: 0, built: LIBRARY_ITEMS.length },
    build: {
      state: 'done',
      mode: 'missing',
      startedAt: 1792600000000,
      updatedAt: 1792600001000,
      finishedAt: 1792600002000,
      done: LIBRARY_ITEMS.length,
      total: LIBRARY_ITEMS.length,
      current: '',
      message: '',
      errors: []
    },
    selectedId: '1197607981',
    selectedCustom: false,
    items: LIBRARY_ITEMS
  }
}

const requests = []
let wallpapersMode = 'ok' // ok | missing | throw（接口不可达）
let selectedConfig = null

function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data)
  })
}

function selectResponse(body) {
  const item = LIBRARY_ITEMS.find((candidate) => candidate.id === body.id)
  if (item === undefined) return jsonResponse({ ok: false, error: 'wallpaper-not-found' })
  const config = Object.assign({}, IMAGE_CFG, {
    enabled: true,
    mode: 'image',
    imagePath: 'C:\\cache\\stills\\' + item.id + '.jpg',
    imageUrl: ''
  })
  selectedConfig = config
  return jsonResponse({
    ok: true,
    config,
    imageVersion: '4096-1700000000002',
    item: { id: item.id, title: item.title }
  })
}

globalThis.fetch = (url, options = {}) => {
  const method = (options.method || 'GET').toUpperCase()
  const route = String(url)
  requests.push({ url: route, method, body: options.body, headers: options.headers || {} })

  if (route === '/dsh-chat-bg/config') {
    if (method === 'POST') {
      const config = options.body ? JSON.parse(options.body) : {}
      return jsonResponse({ ok: true, config, imageVersion: '2048-1700000000001' })
    }
    return jsonResponse(HOST_CONFIG)
  }
  if (route === API_WALLPAPERS) {
    if (wallpapersMode === 'throw') return Promise.reject(new Error('wallpapers endpoint down'))
    if (wallpapersMode === 'missing') {
      return jsonResponse({
        ok: false,
        error: 'library-missing',
        message: '壁纸库还没生成（测试桩）',
        build: { state: 'idle', done: 0, total: 0, message: '' }
      })
    }
    return jsonResponse(wallpapersPayload())
  }
  if (route === API_SELECT) {
    return selectResponse(options.body ? JSON.parse(options.body) : {})
  }
  if (route === API_REFRESH) {
    const body = options.body ? JSON.parse(options.body) : {}
    return jsonResponse({
      ok: true,
      accepted: true,
      build: {
        state: 'running',
        mode: body.mode || 'missing',
        startedAt: 1792600003000,
        updatedAt: 1792600003000,
        finishedAt: 0,
        done: 0,
        total: LIBRARY_ITEMS.length,
        current: 'With the Fairies',
        message: '',
        errors: []
      }
    })
  }
  return Promise.reject(new Error('unexpected fetch: ' + route))
}

/* ── 极简 React hook 运行时（仅 useState / useEffect / createElement）───── */

let activeRuntime = null

function liveRuntime() {
  if (activeRuntime === null) throw new Error('hook 只能在渲染期间调用')
  return activeRuntime
}

const fakeReact = {
  createElement(type, props, ...children) {
    return { type, props: props || {}, children: children.flat(Infinity) }
  },
  useState(initial) {
    const runtime = liveRuntime()
    const index = runtime.cursor++
    let slot = runtime.slots[index]
    if (slot === undefined) {
      slot = runtime.slots[index] = {
        kind: 'state',
        state: typeof initial === 'function' ? initial() : initial,
        setter: null
      }
    } else if (slot.kind !== 'state') {
      throw new Error('hook 顺序在索引 ' + index + ' 处发生变化')
    }
    if (slot.setter === null) {
      slot.setter = (next) => {
        slot.state = typeof next === 'function' ? next(slot.state) : next
        runtime.dirty = true
        if (!runtime.running) runtime.rerender()
      }
    }
    return [slot.state, slot.setter]
  },
  useEffect(callback, deps) {
    const runtime = liveRuntime()
    const index = runtime.cursor++
    let slot = runtime.slots[index]
    if (slot === undefined) {
      slot = runtime.slots[index] = { kind: 'effect', deps: undefined, cleanup: null }
    } else if (slot.kind !== 'effect') {
      throw new Error('hook 顺序在索引 ' + index + ' 处发生变化')
    }
    runtime.pendingEffects.push({
      index,
      callback,
      deps: Array.isArray(deps) ? deps.slice() : undefined
    })
  }
}

/** 挂载组件：同步渲染 + 同步执行 effect，setState 同步重渲染。 */
function mount(component, props) {
  const runtime = {
    component,
    props,
    slots: [],
    cursor: 0,
    dirty: false,
    running: false,
    disposed: false,
    pendingEffects: [],
    tree: null,
    rerender: null
  }

  function renderOnce() {
    runtime.cursor = 0
    runtime.pendingEffects = []
    activeRuntime = runtime
    try {
      runtime.tree = runtime.component(runtime.props)
    } finally {
      activeRuntime = null
    }
    const effects = runtime.pendingEffects.slice()
    runtime.pendingEffects = []
    for (const effect of effects) {
      const slot = runtime.slots[effect.index]
      const sameDeps = effect.deps !== undefined && slot.deps !== undefined &&
        effect.deps.length === slot.deps.length &&
        effect.deps.every((dep, i) => Object.is(dep, slot.deps[i]))
      if (sameDeps) continue
      if (typeof slot.cleanup === 'function') {
        try { slot.cleanup() } catch (err) { /* 清理异常不影响断言 */ }
      }
      slot.deps = effect.deps
      const cleanup = effect.callback()
      slot.cleanup = typeof cleanup === 'function' ? cleanup : null
    }
  }

  function rerender() {
    if (runtime.disposed) return
    if (runtime.running) { runtime.dirty = true; return }
    runtime.running = true
    try {
      let guard = 0
      do {
        runtime.dirty = false
        renderOnce()
      } while (runtime.dirty && ++guard < 50)
    } finally {
      runtime.running = false
    }
  }

  runtime.rerender = rerender
  rerender()

  return {
    get tree() { return runtime.tree },
    rerender,
    dispose() {
      runtime.disposed = true
      for (const slot of runtime.slots) {
        if (slot && typeof slot.cleanup === 'function') {
          try { slot.cleanup() } catch (err) { /* 忽略 */ }
          slot.cleanup = null
        }
      }
      activeRuntime = null
    }
  }
}

/* ── 元素树工具（把 createElement 结果当普通对象遍历）──────────────────── */

function textOf(node) {
  const parts = []
  ;(function walk(current) {
    if (current === null || current === undefined || typeof current === 'boolean') return
    if (typeof current === 'string' || typeof current === 'number') {
      parts.push(String(current))
      return
    }
    if (Array.isArray(current)) {
      for (const child of current) walk(child)
      return
    }
    if (Array.isArray(current.children)) {
      for (const child of current.children) walk(child)
    }
  })(node)
  return parts.join(' ')
}

function findNode(node, predicate) {
  if (node === null || node === undefined || typeof node !== 'object') return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const hit = findNode(child, predicate)
      if (hit !== null) return hit
    }
    return null
  }
  if (predicate(node)) return node
  for (const child of node.children || []) {
    const hit = findNode(child, predicate)
    if (hit !== null) return hit
  }
  return null
}

function findAll(node, predicate, out = []) {
  if (node === null || node === undefined || typeof node !== 'object') return out
  if (Array.isArray(node)) {
    for (const child of node) findAll(child, predicate, out)
    return out
  }
  if (predicate(node)) out.push(node)
  for (const child of node.children || []) findAll(child, predicate, out)
  return out
}

function classNameOf(node) {
  return node && node.props && typeof node.props.className === 'string' ? node.props.className : ''
}

function findByClass(node, className) {
  return findAll(node, (current) => classNameOf(current).split(/\s+/).indexOf(className) >= 0)
}

function findButton(node, label) {
  return findNode(node, (current) => current.type === 'button' && textOf(current) === label)
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

/* ── 载入 client bundle ────────────────────────────────────────────────── */

await import(pathToFileURL(entry).href)

assert.ok(captured !== null, 'ModuleLoader.load 没被调用')
assert.equal(captured.id, 'dsh-chat-background', 'ModuleLoader id 必须是 loader entry 名')

const mod = captured.factory((name) => {
  if (name === 'react') return fakeReact
  throw new Error('client.js 只能 require("react")，却请求了：' + name)
})

assert.equal(typeof mod.apply, 'function', '缺少 apply')
assert.deepEqual(mod.inject, ['slots', 'theme'], 'inject 应声明 slots 与 theme')
const t = mod.__test
assert.ok(t !== null && typeof t === 'object', '缺少 __test 导出')
for (const name of ['sanitize', 'tokensFor', 'cssFor', 'hexToRgba', 'setImageVersion', 'galleryCss']) {
  assert.equal(typeof t[name], 'function', '__test 缺少 ' + name)
}

/* ── 桩：ctx 与 apply ──────────────────────────────────────────────────── */

const calls = { tokens: [], registered: [], injected: [], effects: [], disposed: 0 }

const ctx = {
  theme: {
    overrideTokens: (source, tokens) => {
      calls.tokens.push({ source, tokens })
      return () => { calls.disposed += 1 }
    }
  },
  slots: {
    inject: (name, run) => { calls.injected.push(name); run() },
    register: (options, component) => { calls.registered.push({ options, component }); return () => {} }
  },
  effect: (body) => { calls.effects.push(body()) }
}

mod.apply(ctx)
await tick()

assert.deepEqual(calls.injected, ['settings.section'], '应注入 settings.section')
assert.equal(calls.registered.length, 1, '应注册一个设置页')
assert.deepEqual(calls.registered[0].options, {
  name: 'settings.section',
  id: 'chat-background',
  order: 27,
  label: '对话背景'
})
assert.equal(typeof calls.registered[0].component, 'function', '设置页应给组件')
assert.equal(typeof t.Panel, 'function', 'Panel 组件应可单独渲染（测试用导出）')
assert.equal(calls.registered[0].component({}).type, t.Panel, 'settings.section 注册的组件应渲染 Panel')
assert.equal(calls.tokens.length, 0, '默认关闭时不应覆盖任何主题令牌')
assert.equal(styled.length, 2, '应注入两段 style：面板 CSS + 运行时 CSS')
const runtimeTag = () => styled.find((el) => el.dataset.pluginCss === RUNTIME_STYLE_ID)
assert.equal(runtimeTag().textContent, '', '关闭时运行时 CSS 应为空')
const panelTag = styled.find((el) => el.dataset.pluginCss === PANEL_STYLE_ID)
assert.match(panelTag.textContent, /__cbgw_overlay/, '面板 CSS 应包含壁纸库弹窗样式')
assert.match(panelTag.textContent, /__cbgw_grid/, '面板 CSS 应包含 16:9 网格样式')

/* ── 1. 壁纸库纯函数 ────────────────────────────────────────────────────── */

assert.equal(t.countsText({ total: 369, scene: 311, video: 52, web: 5, other: 1 }),
  '369 张 · 场景 311 / 视频 52 / 网页 5', '计数徽标文案按契约拼装')
assert.equal(t.countsText(null), '', '没有 counts 时徽标为空串')
assert.equal(t.countsText({ total: 0 }), '0 张', '空库也给出总数')
assert.equal(t.typeLabel('scene'), '场景')
assert.equal(t.typeLabel('video'), '视频')
assert.equal(t.typeLabel('web'), '网页')
assert.equal(t.typeLabel('other'), '其他')
assert.equal(t.typeLabel('mystery'), '其他', '未知类型兜底到其他')
assert.equal(t.playlistLabel({ playlistIndex: 5 }), '#5')
assert.equal(t.playlistLabel({ playlistIndex: null }), '', '不在播放列表里没有序号')
assert.equal(t.playlistLabel({}), '')
assert.equal(t.progressText({ done: 5, total: 10 }), '正在生成静态封面 5/10')
assert.equal(t.progressText({ done: 0, total: 0 }), '正在生成静态封面 0/?', 'total 未知时不抛错')
assert.equal(t.progressPercent({ done: 5, total: 10 }), 50)
assert.equal(t.progressPercent({ done: 99, total: 10 }), 100, '百分比夹到 100')
assert.equal(t.progressPercent({ done: 0, total: 0 }), 0)
assert.equal(t.pollMs, 2500, '构建进度每 2.5s 轮询一次')
assert.equal(t.constants.API_WALLPAPERS, API_WALLPAPERS)
assert.equal(t.constants.API_SELECT, API_SELECT)
assert.equal(t.constants.API_REFRESH, API_REFRESH)

const galleryCss = t.galleryCss()
assert.match(galleryCss, /\.__cbgw_overlay\{position:fixed;/, '弹窗必须是 fixed 覆盖层')
assert.match(galleryCss, /min\(1100px,92vw\)/, '弹窗宽度按契约 min(1100px, 92vw)')
assert.match(galleryCss, /min\(760px,88vh\)/, '弹窗高度按契约 min(760px, 88vh)')
assert.match(galleryCss, /repeat\(auto-fill,minmax\(150px,1fr\)\)/, '网格列宽按契约 auto-fill minmax(150px,1fr)')
assert.match(galleryCss, /aspect-ratio:16\/9/, '每格 16:9')
assert.match(galleryCss, /var\(--dsw-alias-bg-module-platform\)/, '弹窗背景用主题变量')
assert.match(galleryCss, /var\(--dsw-alias-label-primary\)/, '弹窗文字用主题变量')
assert.match(galleryCss, /max-width:100%/, '面板列窄 / 祖先 transform 时的防御性宽度')
assert.match(galleryCss, /overflow:auto/, '内容区可滚动兜底')
assert.doesNotMatch(galleryCss, /\.__cbg_/, '新增样式只能使用 __cbgw_ 前缀')

/* 排序 / 筛选 / 搜索都走客户端纯函数 */
const ids = (list) => list.map((item) => item.id)
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { sort: 'playlist' })),
  ['1197607981', '3456595246', '4455667788', '2233445566'],
  '播放列表顺序：有序号的按升序在前，没有的按标题在后')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { sort: 'name' })),
  ['4455667788', '2233445566', '3456595246', '1197607981'], '按名称排序')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { sort: 'recent' })),
  ['4455667788', '2233445566', '1197607981', '3456595246'], '按最近订阅排序')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { sort: 'resolution' })),
  ['1197607981', '3456595246', '2233445566', '4455667788'], '按分辨率排序')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { query: 'SHADOWVERSE' })),
  ['1197607981'], '搜索标题忽略大小写')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { query: '4455667788' })),
  ['4455667788'], '搜索 id 也生效')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { type: 'video' })),
  ['2233445566'], '类型筛选')
assert.deepEqual(ids(t.filterSortItems(LIBRARY_ITEMS, { type: 'scene' })),
  ['1197607981', '4455667788'], '场景筛选保留播放列表顺序')
assert.deepEqual(ids(t.filterSortItems(null, {})), [], '坏数据不抛错')

/* ── 2. 图片模式：壁纸库卡片 + 弹窗交互 ────────────────────────────────── */

store.set(STORE_KEY, JSON.stringify(IMAGE_CFG))
const requestsBeforeMount = requests.length
const mounted = mount(t.Panel, {})
await tick()

assert.ok(requests.slice(requestsBeforeMount).some((req) => req.url === API_WALLPAPERS && req.method === 'GET'),
  '打开设置面板时应 GET /dsh-chat-bg/wallpapers')

let treeText = textOf(mounted.tree)
assert.ok(treeText.includes('Wallpaper Engine 壁纸库'), '图片模式下应出现「壁纸库」卡片')
assert.ok(treeText.includes('4 张 · 场景 2 / 视频 1 / 网页 1'), '卡片显示计数徽标')
assert.ok(treeText.includes('With the Fairies - Shadowverse (Fanart)'), '卡片显示当前壁纸标题')
assert.ok(treeText.includes('#1'), '卡片显示播放列表序号')
assert.ok(findButton(mounted.tree, '打开壁纸库') !== null, '缺少「打开壁纸库」按钮')
assert.ok(findButton(mounted.tree, '随机一张') !== null, '缺少「随机一张」按钮')
assert.ok(findButton(mounted.tree, '重新扫描/生成') !== null, '缺少「重新扫描/生成」按钮')

/* 打开弹窗 */
findButton(mounted.tree, '打开壁纸库').props.onClick()
assert.equal(findByClass(mounted.tree, '__cbgw_overlay').length, 1, '应出现 fixed 覆盖层弹窗')
assert.equal(findByClass(mounted.tree, '__cbgw_item').length, LIBRARY_ITEMS.length, '369 库全量渲染（fixture 4 条）')
assert.equal(findByClass(mounted.tree, '__cbgw_grid').length, 1, '缺少 16:9 网格')
const thumbs = findAll(mounted.tree, (node) => node.type === 'img' && classNameOf(node).includes('__cbgw_thumb'))
assert.equal(thumbs.length, LIBRARY_ITEMS.length, '每个格子一张缩略图')
const thumbUrls = LIBRARY_ITEMS.map((item) => item.thumb)
for (const thumb of thumbs) {
  assert.equal(thumb.props.loading, 'lazy', '缩略图必须 loading="lazy"')
  assert.ok(thumbUrls.includes(thumb.props.src), '缩略图 src 应直接用接口返回的 thumb URL')
}
assert.ok(findNode(mounted.tree, (node) => classNameOf(node).split(/\s+/).includes('__cbgw_itemIdx')) !== null, '缺少 #播放列表序号徽标')
assert.ok(findNode(mounted.tree, (node) => classNameOf(node).split(/\s+/).includes('__cbgw_itemType')) !== null, '缺少类型徽标')
assert.ok(findByClass(mounted.tree, '__cbgw_search').length === 1, '缺少搜索框')
assert.ok(findAll(mounted.tree, (node) => classNameOf(node).split(/\s+/).includes('__cbgw_sel')).length === 2,
  '应有类型筛选与排序两个下拉')
assert.ok(findButton(mounted.tree, '完成') !== null, '缺少完成按钮')
assert.ok(findButton(mounted.tree, '关闭') !== null, '缺少关闭按钮')

/* 弹窗内搜索：客户端过滤 */
const searchInput = findByClass(mounted.tree, '__cbgw_search')[0]
searchInput.props.onChange({ target: { value: 'neon' } })
assert.equal(findByClass(mounted.tree, '__cbgw_item').length, 1, '搜索 "neon" 后只剩一条')
assert.ok(textOf(mounted.tree).includes('Neon City Rain'))
searchInput.props.onChange({ target: { value: '' } })
assert.equal(findByClass(mounted.tree, '__cbgw_item').length, LIBRARY_ITEMS.length, '清空搜索恢复全部')

/* 点击格子：POST /wallpapers/select → saveCache + applyConfig + setCfg */
const selectRequestsBefore = requests.filter((req) => req.url === API_SELECT).length
const neonCell = findByClass(mounted.tree, '__cbgw_item').find((cell) => textOf(cell).includes('Neon City Rain'))
assert.ok(neonCell !== undefined, '找不到「Neon City Rain」格子')
neonCell.props.onClick()
await tick()

const selectRequests = requests.filter((req) => req.url === API_SELECT)
assert.equal(selectRequests.length, selectRequestsBefore + 1, '点击格子应 POST /wallpapers/select')
assert.equal(selectRequests[selectRequests.length - 1].method, 'POST')
assert.deepEqual(JSON.parse(selectRequests[selectRequests.length - 1].body), { id: '2233445566' }, 'POST body 应为 {id}')

const cached = JSON.parse(store.get(STORE_KEY))
assert.equal(cached.enabled, true, '选中后配置应 enabled')
assert.equal(cached.mode, 'image', '选中后配置应 image 模式')
assert.equal(cached.imagePath, selectedConfig.imagePath, '选中后 imagePath 应写成 Host 返回的 still 路径')
/* 底色跟随壁纸：item.palette 应自动覆盖两档底色，并回写 Host 配置 */
assert.equal(cached.colorLight, '#e7d9ef', '从壁纸库选图应自动套用壁纸浅色底色')
assert.equal(cached.colorDark, '#241a2e', '从壁纸库选图应自动套用壁纸深色底色')
const palettePosts = requests.filter((req) => req.url === '/dsh-chat-bg/config' && req.method === 'POST')
assert.ok(palettePosts.length > 0, '自动取色后应把底色写回 Host 配置')
assert.equal(JSON.parse(palettePosts[palettePosts.length - 1].body).colorLight, '#e7d9ef',
  '回写 Host 的配置应包含自动取色的浅色底色')
assert.match(runtimeTag().textContent, /url\("\/dsh-chat-bg\/image\?v=4096-1700000000002"\)/,
  '选中后运行时 CSS 应立即指向新壁纸（带 imageVersion）')
assert.equal(findByClass(mounted.tree, '__cbgw_overlay').length, 1, '选择成功后弹窗不应自动关闭')
assert.ok((findByClass(mounted.tree, '__cbgw_itemOn').length) === 1, '选中项应高亮')
const onCell = findByClass(mounted.tree, '__cbgw_itemOn')[0]
assert.ok(textOf(onCell).includes('Neon City Rain'), '高亮的应是刚选中的壁纸')
assert.ok(textOf(mounted.tree).includes('已切换：Neon City Rain'), '状态行应显示「已切换：标题」')
treeText = textOf(mounted.tree)
assert.ok(treeText.includes('Neon City Rain'), '卡片当前壁纸应更新为新标题')
const lastTokens = calls.tokens[calls.tokens.length - 1].tokens
assert.deepEqual(lastTokens['--dsw-alias-bg-base'], { light: 'transparent', dark: 'transparent' },
  '图片模式令牌：bg-base 透明')
assert.equal(lastTokens['--dsw-alias-bg-layer-1'].light, 'rgba(231,217,239,0.720)',
  '图片模式令牌：自动取色后的浅色底 + surfaceAlpha 生效')

/* 随机一张：两处按钮都接同一个动作 */
const originalRandom = Math.random
Math.random = () => 0.4
const randomButtons = findAll(mounted.tree, (node) => node.type === 'button' && textOf(node) === '随机一张')
assert.equal(randomButtons.length, 2, '卡片与弹窗各一个「随机一张」')
randomButtons[0].props.onClick()
await tick()
assert.equal(requests.filter((req) => req.url === API_SELECT).length, selectRequestsBefore + 2, '随机一张也应 POST select')
Math.random = originalRandom

/* 重新生成：POST refresh → build running → 进度文案 + 2.5s 轮询 */
const refreshRequestsBefore = requests.filter((req) => req.url === API_REFRESH).length
findButton(mounted.tree, '重新扫描/生成').props.onClick()
await tick()
const refreshRequests = requests.filter((req) => req.url === API_REFRESH)
assert.equal(refreshRequests.length, refreshRequestsBefore + 1, '「重新扫描/生成」应 POST /wallpapers/refresh')
assert.deepEqual(JSON.parse(refreshRequests[refreshRequests.length - 1].body), { mode: 'missing' })
assert.ok(textOf(mounted.tree).includes('正在生成静态封面 0/4'), '构建中应显示进度文案 done/total')
mounted.dispose() // 清掉轮询定时器

/* ── 3. 兜底：library-missing 与 Host 不可达 ───────────────────────────── */

wallpapersMode = 'missing'
const missing = mount(t.Panel, {})
await tick()
assert.ok(textOf(missing.tree).includes('壁纸库还没生成（测试桩）'), 'library-missing 时应显示 Host 给的 message')
assert.ok(findButton(missing.tree, '生成壁纸库') !== null, 'library-missing 时应显示「生成壁纸库」按钮')
const refreshBeforeMissing = requests.filter((req) => req.url === API_REFRESH).length
findButton(missing.tree, '生成壁纸库').props.onClick()
await tick()
assert.equal(requests.filter((req) => req.url === API_REFRESH).length, refreshBeforeMissing + 1,
  '「生成壁纸库」应 POST /wallpapers/refresh')
assert.ok(textOf(missing.tree).includes('正在生成静态封面 0/4'), '库缺失时也能显示构建进度')
missing.dispose()

wallpapersMode = 'throw'
const broken = mount(t.Panel, {})
await tick()
assert.ok(textOf(broken.tree).includes('壁纸库接口不可用（需 0.3.0 Host 生效）'),
  '接口不可达时卡片应给 0.3.0 Host 提示，且不阻塞原功能')
assert.ok(findButton(broken.tree, '恢复默认') !== null, '壁纸库不可用时原设置项仍可用')
broken.dispose()
wallpapersMode = 'ok'

/* ── 4. v0.2.0 行为回归：令牌 / 运行时 CSS / 取图 / 兜底 ───────────────── */

const colorCfg = t.sanitize({ enabled: true, mode: 'color', colorLight: '#112233', colorDark: '#000000', sidebar: true })
const colorLayer = t.tokensFor(colorCfg)
for (const name of [
  '--dsw-alias-bg-base',
  '--dsw-alias-bg-layer-1',
  '--dsw-alias-bg-layer-2',
  '--dsw-alias-bg-overlay',
  '--dsw-alias-bg-module-platform',
  '--dsw-specific-sidebar-fill'
]) {
  assert.deepEqual(colorLayer[name], { light: '#112233', dark: '#000000' }, name + ' 应成对覆盖')
}
const colorCss = t.cssFor(colorCfg)
assert.match(colorCss, /body\{background-color:#112233 !important\}/)
assert.match(colorCss, /body\[data-ds-dark-theme\]\{background-color:#000000 !important\}/)
assert.doesNotMatch(colorCss, /background-image/, '纯色模式不应有背景图')

t.setImageVersion('1024-1700000000000')
const imageCfg = t.sanitize({
  enabled: true,
  mode: 'image',
  imagePath: 'C:\\Users\\Administrator\\.dsh\\wallpapers\\deepseek-station.jpg',
  surfaceAlpha: 0.6,
  scrim: 0.2,
  colorLight: '#ffffff',
  colorDark: '#101010'
})
const imageTokens = t.tokensFor(imageCfg)
assert.deepEqual(imageTokens['--dsw-alias-bg-base'], { light: 'transparent', dark: 'transparent' })
assert.equal(imageTokens['--dsw-alias-bg-layer-1'].light, 'rgba(255,255,255,0.600)')
assert.equal(imageTokens['--dsw-alias-bg-layer-1'].dark, 'rgba(16,16,16,0.600)')

const imageCss = t.cssFor(imageCfg)
assert.match(imageCss, /url\("\/dsh-chat-bg\/image\?v=1024-1700000000000"\)/, '本地图片应走 Host 路由并带版本号')
assert.match(imageCss, /background-image:linear-gradient\(rgba\(255,255,255,0\.200\)/)
assert.match(imageCss, /background-attachment:fixed/)
assert.match(imageCss, /background-size:cover/)

const bothCfg = t.sanitize(Object.assign({}, imageCfg, { imageUrl: 'https://example.com/x.jpg' }))
assert.match(t.cssFor(bothCfg), /\/dsh-chat-bg\/image/, '本地路径应优先')
const urlOnly = t.sanitize(Object.assign({}, imageCfg, { imagePath: '', imageUrl: 'https://example.com/a b.jpg' }))
assert.match(t.cssFor(urlOnly), /url\("https:\/\/example\.com\/a b\.jpg"\)/)
assert.doesNotMatch(t.cssFor(t.sanitize({ enabled: true, mode: 'image', imagePath: '', imageUrl: '' })), /background-image/,
  '图片模式但没图时应退回纯色')

assert.equal(t.hexToRgba('#ABC', 0.5), 'rgba(0,0,0,0.500)', '非法色值退回黑色而不是抛错')
assert.equal(t.hexToRgba('#ff0000', 2), 'rgba(255,0,0,1.000)', 'alpha 夹到 1')
assert.equal(t.sanitize({ surfaceAlpha: 9 }).surfaceAlpha, 1, 'surfaceAlpha 上限 1')
assert.equal(t.sanitize({ scrim: -5 }).scrim, 0, 'scrim 下限 0')
assert.equal(t.sanitize({ mode: 'weird' }).mode, 'color', '未知模式退回纯色')
assert.equal(t.tokensFor({ enabled: false }), null, '关闭时 tokensFor 返回 null')

/* ── 5. 卸载：令牌层与运行时 CSS 都要收回 ─────────────────────────────── */

assert.equal(calls.disposed > 0, true, '切换背景后旧令牌层应被释放')
const dispose = calls.effects[calls.effects.length - 1]
assert.equal(typeof dispose, 'function', 'ctx.effect 应返回卸载函数')
dispose()
assert.equal(t.cssFor(colorCfg) !== '', true, 'cssFor 是纯函数，卸载不应改它')
assert.equal(document.querySelector('style[data-plugin-css="' + RUNTIME_STYLE_ID + '"]'), null, '卸载应移除运行时 CSS')
assert.notEqual(document.querySelector('style[data-plugin-css="' + PANEL_STYLE_ID + '"]'), null, '面板 CSS 不随运行时 CSS 移除')

console.log('client.test ok — 壁纸库卡片/弹窗/搜索/选中/随机/重生成/轮询/兜底 + v0.2.0 回归 全部通过')
console.log('  请求统计：' + requests.length + ' 次 fetch，其中 ' +
  requests.filter((req) => req.url === API_WALLPAPERS).length + ' 次 GET /wallpapers，' +
  requests.filter((req) => req.url === API_SELECT).length + ' 次 select，' +
  requests.filter((req) => req.url === API_REFRESH).length + ' 次 refresh')
