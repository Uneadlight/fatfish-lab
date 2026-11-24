/**
 * dsh-chat-background — Host 半侧测试
 * ----------------------------------------------------------------------------
 * 不连真实 DSH：用 stub ctx（webServer.register 收集路由、connection.requestRejection
 * 放行、ctx.effect 收集清理器）动态 import lib/index.js，再用 mock req/res 直接调
 * 路由处理器，覆盖配置读写、壁纸库清单、图片流（200/304/400/404/穿越）、
 * select 写回配置、refresh 受理/拒绝。
 *
 * 全程在 mkdtemp 出来的临时目录里跑，不碰真实 ~/.dsh；refresh 用
 * DSH_CHAT_BG_SPAWN=off 只走受理分支，不会真的启动构建。
 *
 * 运行：node test/host.test.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { Readable } from 'node:stream'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(here, '..')
// 版本断言跟着 package.json 走（2026-11-24 修）：写死 '0.3.0' 时每次升版本都要改测试，
// 上次升到 0.3.1 忘了改，两条用例就一直红着，掩盖了真正的问题。
const PKG_VERSION = JSON.parse(fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf8')).version

/* ============================================================================
 * 临时环境：DSH_HOME / DSH_CHAT_BG_CACHE 必须在 import 插件之前设好
 * ========================================================================== */

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-chat-bg-host-'))
const dshHome = path.join(sandbox, 'dsh-home')
const cacheRoot = path.join(sandbox, 'wallpapers')
const configFile = path.join(dshHome, 'dsh-chat-background.json')
const libraryFile = path.join(cacheRoot, 'library.json')
const buildStatusFile = path.join(cacheRoot, 'build-status.json')
const stillsDir = path.join(cacheRoot, 'stills')
const thumbsDir = path.join(cacheRoot, 'thumbs')

process.env.DSH_HOME = dshHome
process.env.DSH_CHAT_BG_CACHE = cacheRoot
delete process.env.DSH_CHAT_BG_SPAWN

fs.mkdirSync(stillsDir, { recursive: true })
fs.mkdirSync(thumbsDir, { recursive: true })

const ID_A = '1197607981'
const ID_B = '3456595246'

/** 假 JPEG 字节：只要内容可比较即可，路由不解析图片。 */
const STILL_A = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0xff, 0xd9])
const STILL_B = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x02, 0x03, 0xff, 0xd9])
const THUMB_A = Buffer.from([0xff, 0xd8, 0xff, 0xdb, 0x00, 0x04, 0x00, 0x01, 0xff, 0xd9])
const THUMB_B = Buffer.from([0xff, 0xd8, 0xff, 0xdb, 0x00, 0x04, 0x00, 0x02, 0xff, 0xd9])

const stillFile = (id) => path.join(stillsDir, id + '.jpg')
const thumbFile = (id) => path.join(thumbsDir, id + '.jpg')

fs.writeFileSync(stillFile(ID_A), STILL_A)
fs.writeFileSync(stillFile(ID_B), STILL_B)
fs.writeFileSync(thumbFile(ID_A), THUMB_A)
fs.writeFileSync(thumbFile(ID_B), THUMB_B)

/** library.json fixture：两条，一条 scene 在播放列表里，一条 video。 */
function makeLibrary() {
  return {
    schema: 1,
    generatedAt: 1792600000000,
    weDir: 'D:/SteamLibrary/steamapps/common/wallpaper_engine',
    workshopRoot: 'D:/SteamLibrary/steamapps/workshop/content/431960',
    counts: { total: 2, scene: 1, video: 1, web: 0, other: 0, built: 2 },
    items: [
      {
        id: ID_A,
        title: 'With the Fairies - Shadowverse (Fanart)',
        type: 'scene',
        playlistIndex: 3,
        current: true,
        tags: ['Anime'],
        filesize: 21453743,
        subscriptiondate: 1734943775,
        width: 3840,
        height: 2160,
        bytes: 4096,
        source: 'embedded',
        palette: { light: '#f2e4e8', dark: '#221a1e' },
        still: 'stills/' + ID_A + '.jpg',
        thumb: 'thumbs/' + ID_A + '.jpg'
      },
      {
        id: ID_B,
        title: 'Neon City',
        type: 'video',
        playlistIndex: 1,
        current: false,
        tags: ['Sci-Fi', 'City'],
        filesize: 12345678,
        subscriptiondate: 1700000000,
        width: 2560,
        height: 1440,
        bytes: 2048,
        source: 'video',
        still: 'stills/' + ID_B + '.jpg',
        thumb: 'thumbs/' + ID_B + '.jpg'
      }
    ]
  }
}

function writeLibrary(library) {
  fs.writeFileSync(libraryFile, JSON.stringify(library || makeLibrary(), null, 2), 'utf8')
}

function writeBuildStatus(patch) {
  const status = Object.assign({
    state: 'idle',
    mode: 'missing',
    startedAt: 0,
    updatedAt: 0,
    finishedAt: 0,
    done: 0,
    total: 2,
    current: '',
    message: '',
    errors: []
  }, patch || {})
  fs.writeFileSync(buildStatusFile, JSON.stringify(status, null, 2), 'utf8')
}

/* ============================================================================
 * mock req / res 与 stub ctx
 * ========================================================================== */

class MockRequest extends Readable {
  constructor(method, url, body, headers) {
    super()
    this.method = method
    this.url = url
    this.headers = Object.assign({}, headers)
    if (body !== undefined && body !== null) this.push(Buffer.from(String(body), 'utf8'))
    this.push(null)
  }
}

class MockResponse {
  constructor() {
    this.statusCode = 200
    this.headers = {}
    this.chunks = []
    this.body = Buffer.alloc(0)
    this.ended = false
  }

  writeHead(code, headers) {
    this.statusCode = code
    if (headers) {
      for (const [key, value] of Object.entries(headers)) this.headers[key.toLowerCase()] = value
    }
    return this
  }

  setHeader(name, value) {
    this.headers[String(name).toLowerCase()] = value
  }

  getHeader(name) {
    return this.headers[String(name).toLowerCase()]
  }

  end(chunk) {
    if (chunk !== undefined && chunk !== null) {
      this.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8'))
    }
    this.body = Buffer.concat(this.chunks)
    this.ended = true
  }

  json() {
    return JSON.parse(this.body.toString('utf8'))
  }
}

const routes = []
const effects = []
let rejectNext = null

const fakeServer = {
  register(route) {
    routes.push(route)
    return () => {
      const index = routes.indexOf(route)
      if (index >= 0) routes.splice(index, 1)
    }
  },
  tapIndex() {
    return 0
  }
}

const connection = {
  requestRejection() {
    if (rejectNext === null) return undefined
    const code = rejectNext
    rejectNext = null
    return code
  }
}

const ctx = {
  get(service) {
    if (service === 'webServer') return fakeServer
    if (service === 'connection') return connection
    return undefined
  },
  webServer: fakeServer,
  effect(callback) {
    effects.push(callback)
    return () => {}
  },
  logger: { warn() {}, info() {}, error() {} }
}

function routeFor(pathname) {
  const route = routes.find((entry) => entry.path === pathname)
  assert.ok(route, '未注册路由：' + pathname)
  return route
}

async function request(method, url, options) {
  const opts = options || {}
  const pathname = new URL(url, 'http://localhost').pathname
  const req = new MockRequest(method, url, opts.body, opts.headers)
  const res = new MockResponse()
  await routeFor(pathname).handler(req, res)
  return res
}

const get = (url, options) => request('GET', url, options)
const post = (url, body, options) => request('POST', url, Object.assign({ body }, options || {}))

/* ============================================================================
 * 极简用例跑分器
 * ========================================================================== */

let passed = 0
const failures = []

async function test(name, fn) {
  try {
    await fn()
    passed += 1
    console.log('  ✓ ' + name)
  } catch (err) {
    failures.push({ name, err })
    console.log('  ✗ ' + name)
    console.log('    ' + String((err && err.stack) || err).split('\n').slice(0, 6).join('\n    '))
  }
}

/* ============================================================================
 * 开始：加载插件并 apply
 * ========================================================================== */

console.log('dsh-chat-background Host 测试')
console.log('环境目录：' + sandbox + '\n')

const host = await import(pathToFileURL(path.join(projectRoot, 'lib', 'index.js')).href)
host.apply(ctx)

/* ── 导出与路由注册 ─────────────────────────────────────────────────────── */

await test('导出形状保持 v0.2.0（apply/inject/name）并带 __test', () => {
  assert.equal(typeof host.apply, 'function')
  assert.deepEqual(host.inject, ['webServer', 'connection'])
  assert.equal(host.name, 'dsh-chat-background')
  assert.equal(typeof host.__test.readLibrary, 'function')
  assert.equal(typeof host.__test.resolveWallpaperFile, 'function')
  assert.equal(host.__test.WALLPAPER_CACHE, path.resolve(cacheRoot))
  assert.equal(host.__test.getBuilderScript(), path.resolve(projectRoot, 'tools', 'build-library.mjs'))
})

await test('注册 6 条 exact 路由（2 条旧 + 4 条新）', () => {
  assert.deepEqual(routes.map((route) => route.path).sort(), [
    '/dsh-chat-bg/config',
    '/dsh-chat-bg/image',
    '/dsh-chat-bg/wallpaper',
    '/dsh-chat-bg/wallpapers',
    '/dsh-chat-bg/wallpapers/refresh',
    '/dsh-chat-bg/wallpapers/select'
  ])
  assert.ok(routes.every((route) => route.kind === 'exact'))
})

/* ── config 老功能回归 ──────────────────────────────────────────────────── */

await test('config GET 返回默认配置', async () => {
  const res = await get('/dsh-chat-bg/config')
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.ok, true)
  assert.equal(body.version, PKG_VERSION)
  assert.deepEqual(body.config, {
    enabled: false,
    mode: 'color',
    colorLight: '#f3efe6',
    colorDark: '#15171b',
    imagePath: '',
    imageUrl: '',
    surfaceAlpha: 0.72,
    scrim: 0.18,
    sidebar: true
  })
  assert.equal(body.imageVersion, '')
})

await test('config POST 落盘、sanitize 后回显，GET 能读回', async () => {
  const res = await post('/dsh-chat-bg/config', JSON.stringify({
    enabled: true,
    mode: 'image',
    colorLight: '#ABCDEF',
    colorDark: '#00ff00',
    surfaceAlpha: 9,
    scrim: -1,
    sidebar: false,
    imageUrl: 'https://example.com/x.png'
  }))
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.config.enabled, true)
  assert.equal(body.config.mode, 'image')
  assert.equal(body.config.colorLight, '#abcdef')
  assert.deepEqual(Object.keys(body.config).sort(), [
    'colorDark', 'colorLight', 'enabled', 'imagePath', 'imageUrl',
    'mode', 'scrim', 'sidebar', 'surfaceAlpha'
  ])
  assert.equal(body.config.colorDark, '#00ff00')
  assert.equal(body.config.surfaceAlpha, 1)
  assert.equal(body.config.scrim, 0)
  assert.equal(body.config.sidebar, false)
  assert.deepEqual(JSON.parse(fs.readFileSync(configFile, 'utf8')), body.config)
  const back = (await get('/dsh-chat-bg/config')).json()
  assert.deepEqual(back.config, body.config)
})

await test('config POST 空 body / 非法 JSON → 400，非法方法 → 405', async () => {
  assert.equal((await post('/dsh-chat-bg/config', '')).statusCode, 400)
  assert.equal((await post('/dsh-chat-bg/config', '{oops')).statusCode, 400)
  assert.equal((await request('PUT', '/dsh-chat-bg/config')).statusCode, 405)
})

/* ── 壁纸库清单 ─────────────────────────────────────────────────────────── */

await test('wallpapers 在 library 缺失时 HTTP 200 + library-missing', async () => {
  fs.rmSync(libraryFile, { force: true })
  host.__test.resetLibraryCache()
  writeBuildStatus({ state: 'idle', message: '还没开始' })
  const res = await get('/dsh-chat-bg/wallpapers')
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.ok, false)
  assert.equal(body.error, 'library-missing')
  assert.equal(body.build.state, 'idle')
  assert.equal(body.build.message, '还没开始')
  assert.equal(typeof body.message, 'string')
})

await test('wallpapers 返回 counts/build/items/图片 URL', async () => {
  writeLibrary()
  host.__test.resetLibraryCache()
  writeBuildStatus({ state: 'done', done: 2, total: 2, message: '构建完成' })
  const res = await get('/dsh-chat-bg/wallpapers')
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.ok, true)
  assert.equal(body.version, PKG_VERSION)
  assert.deepEqual(body.counts, { total: 2, scene: 1, video: 1, web: 0, other: 0, built: 2 })
  assert.equal(body.build.state, 'done')
  assert.equal(body.build.message, '构建完成')
  assert.equal(body.items.length, 2)
  const first = body.items[0]
  assert.equal(first.id, ID_A)
  assert.equal(first.title, 'With the Fairies - Shadowverse (Fanart)')
  assert.equal(first.type, 'scene')
  assert.equal(first.playlistIndex, 3)
  assert.equal(first.current, true)
  assert.deepEqual(first.tags, ['Anime'])
  assert.equal(first.width, 3840)
  assert.equal(first.height, 2160)
  assert.equal(first.source, 'embedded')
  assert.deepEqual(first.palette, { light: '#f2e4e8', dark: '#221a1e' })
  assert.equal(body.items[1].palette, null)
  assert.equal(first.thumb, '/dsh-chat-bg/wallpaper?id=' + ID_A + '&kind=thumb')
  assert.equal(first.still, '/dsh-chat-bg/wallpaper?id=' + ID_A + '&kind=still')
  assert.equal(Object.prototype.hasOwnProperty.call(first, 'bytes'), false)
  assert.equal(JSON.stringify(body).includes('stills/'), false)
  assert.equal(body.selectedId, null)
  assert.equal(body.selectedCustom, false)
})

await test('wallpapers 用 imagePath 反查 selectedId（Windows 大小写不敏感）', async () => {
  const original = stillFile(ID_B)
  const spelled = process.platform === 'win32' ? original.toUpperCase() : original
  await post('/dsh-chat-bg/config', JSON.stringify({ enabled: true, mode: 'image', imagePath: spelled }))
  const body = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(body.selectedId, ID_B)
  assert.equal(body.selectedCustom, false)
})

await test('wallpapers 在 imagePath 不是库内图片时 selectedCustom=true', async () => {
  const custom = path.join(sandbox, 'custom.png')
  await post('/dsh-chat-bg/config', JSON.stringify({ enabled: true, mode: 'image', imagePath: custom }))
  const body = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(body.selectedId, null)
  assert.equal(body.selectedCustom, true)
})

await test('library.json 走 mtime+size 缓存，文件变化后自动重载', async () => {
  host.__test.resetLibraryCache()
  const first = host.__test.readLibrary()
  assert.ok(first)
  assert.equal(host.__test.readLibrary(), first, '文件未变时应命中内存缓存（同一对象）')

  const updated = JSON.parse(JSON.stringify(makeLibrary()))
  updated.items.push({
    id: '123456789',
    title: 'Third Wallpaper',
    type: 'web',
    playlistIndex: null,
    current: false,
    tags: [],
    filesize: 1,
    subscriptiondate: 0,
    width: 1920,
    height: 1080,
    source: 'web',
    still: 'stills/123456789.jpg',
    thumb: 'thumbs/123456789.jpg'
  })
  updated.counts = { total: 3, scene: 1, video: 1, web: 1, other: 0, built: 3 }
  writeLibrary(updated)

  const second = host.__test.readLibrary()
  assert.notEqual(second, first, 'mtime/size 变化后应重新解析')
  assert.equal(second.items.length, 3)
  const body = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(body.items.length, 3)
  assert.equal(body.counts.built, 3)

  writeLibrary()
  host.__test.resetLibraryCache()
})

await test('build-status.json 每次请求都现读（不缓存）', async () => {
  writeBuildStatus({ state: 'running', done: 1, total: 2, current: 'Neon City', message: '正在生成' })
  let body = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(body.build.state, 'running')
  assert.equal(body.build.current, 'Neon City')
  writeBuildStatus({ state: 'error', message: 'ffmpeg 缺失' })
  body = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(body.build.state, 'error')
  assert.equal(body.build.message, 'ffmpeg 缺失')
  writeBuildStatus({ state: 'idle', message: '' })
})

/* ── 壁纸图片 ───────────────────────────────────────────────────────────── */

const wallpaperUrl = (id, kind) => '/dsh-chat-bg/wallpaper?id=' + id + '&kind=' + kind

await test('wallpaper 200：JPEG 字节 + ETag/Cache-Control/Content-Length', async () => {
  const res = await get(wallpaperUrl(ID_A, 'still'))
  assert.equal(res.statusCode, 200)
  assert.equal(res.headers['content-type'], 'image/jpeg')
  assert.equal(res.headers['cache-control'], 'private, max-age=604800')
  assert.equal(res.headers['content-length'], String(STILL_A.length))
  assert.deepEqual(res.body, STILL_A)
  const stat = fs.statSync(stillFile(ID_A))
  assert.equal(res.headers.etag, '"' + stat.size + '-' + Math.round(stat.mtimeMs) + '"')
  const thumb = await get(wallpaperUrl(ID_A, 'thumb'))
  assert.equal(thumb.statusCode, 200)
  assert.deepEqual(thumb.body, THUMB_A)
})

await test('wallpaper If-None-Match 命中 → 304 空 body；不命中 → 200', async () => {
  const first = await get(wallpaperUrl(ID_B, 'still'))
  const etag = first.headers.etag
  const hit = await get(wallpaperUrl(ID_B, 'still'), { headers: { 'if-none-match': etag } })
  assert.equal(hit.statusCode, 304)
  assert.equal(hit.body.length, 0)
  assert.equal(hit.headers.etag, etag)
  const miss = await get(wallpaperUrl(ID_B, 'still'), { headers: { 'if-none-match': '"stale-etag"' } })
  assert.equal(miss.statusCode, 200)
  assert.deepEqual(miss.body, STILL_B)
})

await test('wallpaper id/kind 非法 → 400；文件不存在 → 404', async () => {
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=abc&kind=still')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=&kind=still')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=12x&kind=still')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=' + '1'.repeat(21) + '&kind=still')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=123&kind=png')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=123&kind=../stills')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=7777777&kind=still')).statusCode, 404)
  assert.equal((await get('/dsh-chat-bg/wallpaper?id=7777777&kind=thumb')).statusCode, 404)
  assert.equal((await post('/dsh-chat-bg/wallpaper?id=123&kind=still')).statusCode, 405)
})

await test('目录穿越防护：id 白名单 + resolve 后必须仍在缓存根内', async () => {
  const escape = await get('/dsh-chat-bg/wallpaper?id=..%2F..%2Fdsh-chat-background.json&kind=still')
  assert.equal(escape.statusCode, 400)
  assert.equal(host.__test.resolveWallpaperFile('../evil', 'still'), null)
  assert.equal(host.__test.resolveWallpaperFile('..', 'still'), null)
  assert.equal(host.__test.resolveWallpaperFile('123', '../stills'), null)
  assert.equal(host.__test.wallpaperStillPath({ still: '../outside.jpg' }), null)
  assert.equal(host.__test.wallpaperStillPath({ still: 'stills/../../outside.jpg' }), null)
  const file = host.__test.resolveWallpaperFile(ID_A, 'still')
  assert.equal(path.resolve(file), path.resolve(stillFile(ID_A)))
  const relative = path.relative(path.resolve(cacheRoot), path.resolve(file))
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative))
})

/* ── select ─────────────────────────────────────────────────────────────── */

await test('select 成功：写回 enabled/mode/imagePath/imageUrl，其余字段沿用', async () => {
  const before = (await get('/dsh-chat-bg/config')).json().config
  const res = await post('/dsh-chat-bg/wallpapers/select', JSON.stringify({ id: ID_A }))
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.ok, true)
  assert.equal(body.config.enabled, true)
  assert.equal(body.config.mode, 'image')
  assert.equal(path.resolve(body.config.imagePath), path.resolve(stillFile(ID_A)))
  assert.equal(body.config.imageUrl, '')
  for (const key of ['colorLight', 'colorDark', 'surfaceAlpha', 'scrim', 'sidebar']) {
    assert.equal(body.config[key], before[key], '其余字段应沿用当前配置：' + key)
  }
  assert.deepEqual(body.item, { id: ID_A, title: 'With the Fairies - Shadowverse (Fanart)' })
  assert.match(body.imageVersion, /^\d+-\d+$/)
  assert.deepEqual(JSON.parse(fs.readFileSync(configFile, 'utf8')), body.config)
  const list = (await get('/dsh-chat-bg/wallpapers')).json()
  assert.equal(list.selectedId, ID_A)
  assert.equal(list.selectedCustom, false)
})

await test('旧 /image 路由仍按配置 imagePath 返回图片（v0.2.0 行为保留）', async () => {
  const res = await get('/dsh-chat-bg/image')
  assert.equal(res.statusCode, 200)
  assert.equal(res.headers['content-type'], 'image/jpeg')
  assert.deepEqual(res.body, STILL_A)
})

await test('select 找不到条目 / 非法 body → 404/400', async () => {
  const missing = await post('/dsh-chat-bg/wallpapers/select', JSON.stringify({ id: '7777777' }))
  assert.equal(missing.statusCode, 404)
  assert.equal(missing.json().error, 'wallpaper-not-found')
  assert.equal((await post('/dsh-chat-bg/wallpapers/select', JSON.stringify({ id: 'abc' }))).statusCode, 404)
  assert.equal((await post('/dsh-chat-bg/wallpapers/select', JSON.stringify({}))).statusCode, 404)
  assert.equal((await post('/dsh-chat-bg/wallpapers/select', '')).statusCode, 400)
  assert.equal((await post('/dsh-chat-bg/wallpapers/select', '{oops')).statusCode, 400)
  assert.equal((await get('/dsh-chat-bg/wallpapers/select')).statusCode, 405)
})

await test('select 在 still 文件缺失时返回 404', async () => {
  const backup = fs.readFileSync(stillFile(ID_B))
  fs.rmSync(stillFile(ID_B), { force: true })
  try {
    const res = await post('/dsh-chat-bg/wallpapers/select', JSON.stringify({ id: ID_B }))
    assert.equal(res.statusCode, 404)
    assert.equal(res.json().error, 'wallpaper-not-found')
  } finally {
    fs.writeFileSync(stillFile(ID_B), backup)
  }
})

/* ── refresh ────────────────────────────────────────────────────────────── */

await test('refresh 构建运行中 → accepted:false，不重复启动', async () => {
  writeBuildStatus({ state: 'running', done: 1, total: 2, current: 'Neon City' })
  const res = await post('/dsh-chat-bg/wallpapers/refresh', '')
  assert.equal(res.statusCode, 200)
  const body = res.json()
  assert.equal(body.ok, true)
  assert.equal(body.accepted, false)
  assert.equal(body.build.state, 'running')
  assert.equal(body.build.current, 'Neon City')
})

await test('refresh 空闲时受理 → accepted:true（DSH_CHAT_BG_SPAWN=off 不真跑）', async () => {
  writeBuildStatus({ state: 'done', done: 2, total: 2, message: '上次完成' })
  const fakeBuilder = path.join(sandbox, 'fake-builder.mjs')
  fs.writeFileSync(fakeBuilder, '// 测试用假 builder，不会被真的启动\n', 'utf8')
  host.__test.setBuilderScript(fakeBuilder)
  process.env.DSH_CHAT_BG_SPAWN = 'off'
  try {
    const res = await post('/dsh-chat-bg/wallpapers/refresh', JSON.stringify({ mode: 'force' }))
    assert.equal(res.statusCode, 200)
    const body = res.json()
    assert.equal(body.ok, true)
    assert.equal(body.accepted, true)
    assert.equal(body.build.state, 'running')
    assert.equal(body.build.mode, 'force')
    assert.equal(body.build.done, 0)
    assert.equal(body.build.finishedAt, 0)
    assert.equal(typeof body.build.startedAt, 'number')
  } finally {
    delete process.env.DSH_CHAT_BG_SPAWN
  }
})

await test('refresh 默认 mode=missing，非法 JSON → 400，GET → 405', async () => {
  writeBuildStatus({ state: 'idle' })
  process.env.DSH_CHAT_BG_SPAWN = 'off'
  try {
    const res = await post('/dsh-chat-bg/wallpapers/refresh', '')
    assert.equal(res.json().build.mode, 'missing')
    assert.equal((await post('/dsh-chat-bg/wallpapers/refresh', '{oops')).statusCode, 400)
  } finally {
    delete process.env.DSH_CHAT_BG_SPAWN
  }
  assert.equal((await get('/dsh-chat-bg/wallpapers/refresh')).statusCode, 405)
})

await test('refresh builder 脚本缺失 → 500 错误 JSON', async () => {
  writeBuildStatus({ state: 'idle' })
  host.__test.setBuilderScript(path.join(sandbox, 'no-such-builder.mjs'))
  try {
    const res = await post('/dsh-chat-bg/wallpapers/refresh', '')
    assert.equal(res.statusCode, 500)
    const body = res.json()
    assert.equal(body.ok, false)
    assert.equal(body.error, 'builder-missing')
    assert.match(body.message, /no-such-builder\.mjs$/)
  } finally {
    host.__test.setBuilderScript(null)
  }
  assert.equal(host.__test.getBuilderScript(), path.resolve(projectRoot, 'tools', 'build-library.mjs'))
})

await test('refresh 启动参数与 env 正确（Electron 下追加 ELECTRON_RUN_AS_NODE）', () => {
  const script = host.__test.BUILDER_SCRIPT
  const args = host.__test.builderArgs(script, 'force')
  assert.deepEqual(args, [script, '--mode', 'force', '--cache', path.resolve(cacheRoot)])

  /* DSH 给子命令的环境里可能本来就带 ELECTRON_RUN_AS_NODE=1，
     验证「非 Electron 不主动追加」时要先摘掉继承值再测。 */
  const inherited = process.env.ELECTRON_RUN_AS_NODE
  delete process.env.ELECTRON_RUN_AS_NODE
  try {
    const plainEnv = host.__test.builderEnv({})
    assert.equal(plainEnv.DSH_HOME, dshHome)
    assert.equal(plainEnv.DSH_CHAT_BG_CACHE, path.resolve(cacheRoot))
    assert.equal(plainEnv.ELECTRON_RUN_AS_NODE, undefined)
  } finally {
    if (inherited !== undefined) process.env.ELECTRON_RUN_AS_NODE = inherited
  }

  const electronEnv = host.__test.builderEnv({ electron: '30.0.0' })
  assert.equal(electronEnv.ELECTRON_RUN_AS_NODE, '1')
  assert.equal(electronEnv.DSH_HOME, dshHome)
  assert.equal(electronEnv.DSH_CHAT_BG_CACHE, path.resolve(cacheRoot))
})

/* ── 鉴权栅栏 / 清理 ────────────────────────────────────────────────────── */

await test('鉴权栅栏：新路由同样先过 requestRejection', async () => {
  rejectNext = 403
  const blocked = await get('/dsh-chat-bg/wallpapers')
  assert.equal(blocked.statusCode, 403)
  assert.equal(blocked.body.length, 0)

  rejectNext = true
  const blockedImage = await get(wallpaperUrl(ID_A, 'still'))
  assert.equal(blockedImage.statusCode, 403)
  assert.equal(blockedImage.body.length, 0)

  const allowed = await get('/dsh-chat-bg/wallpapers')
  assert.equal(allowed.statusCode, 200)
  assert.equal(allowed.json().ok, true)
})

await test('ctx.effect 清理会注销全部路由', () => {
  assert.equal(effects.length, 1)
  const cleanup = effects[0]()
  assert.equal(typeof cleanup, 'function')
  cleanup()
  assert.equal(routes.length, 0)
})

/* ============================================================================
 * 汇总
 * ========================================================================== */

fs.rmSync(sandbox, { recursive: true, force: true })

if (failures.length > 0) {
  console.error('\n' + failures.length + ' 个用例失败 / 共 ' + (passed + failures.length) + ' 个')
  process.exitCode = 1
} else {
  console.log('\n全部 ' + passed + ' 个用例通过')
}
