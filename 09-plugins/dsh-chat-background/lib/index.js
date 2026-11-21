/* ============================================================================
 * dsh-chat-background — Host 半侧
 * ----------------------------------------------------------------------------
 * 五件事：
 *   1) 把配置落到 ~/.dsh/dsh-chat-background.json（Host 是唯一真源）
 *   2) GET/POST /dsh-chat-bg/config   —— 设置页读写
 *   3) GET  /dsh-chat-bg/image        —— 按配置里的本地路径把图片喂给浏览器
 *   4) GET  /dsh-chat-bg/wallpapers   —— Wallpaper Engine 壁纸库清单
 *      GET  /dsh-chat-bg/wallpaper    —— 壁纸库里的静态封面 / 缩略图字节流
 *   5) POST /dsh-chat-bg/wallpapers/refresh —— 后台补齐/重建封面
 *      POST /dsh-chat-bg/wallpapers/select  —— 选中某张壁纸并写回配置
 *
 * 为什么图片要由 Host 喂：浏览器的 CSS 读不到本地文件路径，而把几百 KB 的
 * 图片塞进 data URL 再存 localStorage 又贵又难维护。这里直接从磁盘读流回去，
 * 图片本身留在原位，配置里只记一个路径。
 *
 * 自定义路由必须过一道信任栅栏（connection.requestRejection），否则任意网页
 * 都能借本机端口读文件。栅栏由 DSH 自己的连接服务判定。
 * ========================================================================== */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const NS = 'dsh-chat-background'
const ROUTE_BASE = '/dsh-chat-bg'
const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
const CONFIG_FILE = path.join(DSH_HOME, 'dsh-chat-background.json')

/** 壁纸库缓存根：Builder 写，Host 读。测试可用 env 覆盖到临时目录。 */
const WALLPAPER_CACHE = process.env.DSH_CHAT_BG_CACHE
  ? path.resolve(process.env.DSH_CHAT_BG_CACHE)
  : path.join(DSH_HOME, 'dsh-chat-background', 'wallpapers')
const LIBRARY_FILE = path.join(WALLPAPER_CACHE, 'library.json')
const BUILD_STATUS_FILE = path.join(WALLPAPER_CACHE, 'build-status.json')
const BUILDER_SCRIPT = path.resolve(PACKAGE_ROOT, 'tools', 'build-library.mjs')

const WALLPAPER_ROUTE = ROUTE_BASE + '/wallpaper'
/** 壁纸 id 只收纯数字（最多 20 位，足够覆盖 Steam 创意工坊 id）。 */
const WALLPAPER_ID_RE = /^\d{1,20}$/
/** kind → 缓存子目录。同时充当 kind 的白名单。 */
const WALLPAPER_KINDS = { still: 'stills', thumb: 'thumbs' }
/** 封面一周内可复用，配合 ETag 让浏览器换图后重新取。 */
const WALLPAPER_CACHE_CONTROL = 'private, max-age=604800'

/** 单张图上限，防止误指到镜像/视频文件把内存打满。 */
const MAX_IMAGE_BYTES = 40 * 1024 * 1024

const MIME = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.avif': 'image/avif',
  '.bmp': 'image/bmp'
}

const DEFAULTS = {
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

const PLUGIN_VERSION = (() => {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'package.json'), 'utf8'))
    return String(pkg.version || '0.0.0')
  } catch (err) {
    return '0.0.0'
  }
})()

const clamp = (n, lo, hi) => {
  const num = Number(n)
  if (!Number.isFinite(num)) return lo
  return num < lo ? lo : num > hi ? hi : num
}

const isHex = (v) => typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v)

/** 把 JSON 里可能出现的字符串/数字收敛成有限数字，`null` 视为缺省。 */
const finiteNumber = (value, fallback) => {
  if (value === null || value === undefined || value === '') return fallback
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

/** 把外部输入收敛成一份可信配置（手改过的 JSON 也走这里）。 */
function sanitize(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  return {
    enabled: src.enabled === true,
    mode: src.mode === 'image' ? 'image' : 'color',
    colorLight: isHex(src.colorLight) ? src.colorLight.toLowerCase() : DEFAULTS.colorLight,
    colorDark: isHex(src.colorDark) ? src.colorDark.toLowerCase() : DEFAULTS.colorDark,
    imagePath: typeof src.imagePath === 'string' ? src.imagePath.trim().slice(0, 1024) : '',
    imageUrl: typeof src.imageUrl === 'string' ? src.imageUrl.trim().slice(0, 2048) : '',
    surfaceAlpha: clamp(src.surfaceAlpha == null ? DEFAULTS.surfaceAlpha : src.surfaceAlpha, 0.2, 1),
    scrim: clamp(src.scrim == null ? DEFAULTS.scrim : src.scrim, 0, 0.8),
    sidebar: src.sidebar !== false
  }
}

function readConfig() {
  try {
    const text = fs.readFileSync(CONFIG_FILE, 'utf8')
    return sanitize(JSON.parse(text))
  } catch (err) {
    return sanitize(DEFAULTS)
  }
}

function writeConfig(config) {
  const body = JSON.stringify(config, null, 2)
  fs.mkdirSync(path.dirname(CONFIG_FILE), { recursive: true })
  const tmp = CONFIG_FILE + '.tmp'
  fs.writeFileSync(tmp, body, 'utf8')
  fs.renameSync(tmp, CONFIG_FILE)
  return config
}

/** 图片版本号：路径 + 大小 + mtime，用来在换图后让浏览器重新取。 */
function imageVersion(file) {
  try {
    const stat = fs.statSync(file)
    return String(stat.size) + '-' + String(Math.round(stat.mtimeMs))
  } catch (err) {
    return ''
  }
}

/* ============================================================================
 * 壁纸库：library.json / build-status.json 读取
 * ----------------------------------------------------------------------------
 * library.json 可能有好几 MB，用 mtime+size 做内存缓存，文件一改就自动重载；
 * build-status.json 很小，每次现读，保证构建进度及时。
 * ========================================================================== */

/** Builder 脚本路径。线上固定为 tools/build-library.mjs，测试可临时替换。 */
let builderScript = BUILDER_SCRIPT

/** library.json 缓存戳（mtimeMs:size）与解析结果。 */
let libraryCacheStamp = ''
let libraryCacheValue = null

const DEFAULT_BUILD_STATUS = {
  state: 'idle',
  mode: 'missing',
  startedAt: 0,
  updatedAt: 0,
  finishedAt: 0,
  done: 0,
  total: 0,
  current: '',
  message: '',
  errors: []
}

/** 壁纸底色取色：{light,dark} 两个 #rrggbb；缺失/非法返回 null。 */
function normalizeWallpaperPalette(raw) {
  const src = raw && typeof raw === 'object' ? raw : null
  if (!src) return null
  const light = typeof src.light === 'string' ? src.light.trim().toLowerCase() : ''
  const dark = typeof src.dark === 'string' ? src.dark.trim().toLowerCase() : ''
  if (!isHex(light) || !isHex(dark)) return null
  return { light, dark }
}

/** 条目字段兜底：库文件是 Builder 写的，但 Host 不盲信磁盘内容。 */
function normalizeWallpaperItem(raw) {
  const src = raw && typeof raw === 'object' ? raw : null
  if (!src) return null
  const id = src.id === null || src.id === undefined ? '' : String(src.id).trim()
  if (!WALLPAPER_ID_RE.test(id)) return null
  const type = src.type === 'scene' || src.type === 'video' || src.type === 'web' ? src.type : 'other'
  return {
    id,
    title: typeof src.title === 'string' && src.title ? src.title : id,
    type,
    playlistIndex: finiteNumber(src.playlistIndex, null),
    current: src.current === true,
    tags: Array.isArray(src.tags) ? src.tags.filter((tag) => typeof tag === 'string') : [],
    filesize: finiteNumber(src.filesize, 0),
    subscriptiondate: finiteNumber(src.subscriptiondate, 0),
    width: finiteNumber(src.width, 0),
    height: finiteNumber(src.height, 0),
    source: typeof src.source === 'string' ? src.source : '',
    palette: normalizeWallpaperPalette(src.palette),
    still: typeof src.still === 'string' ? src.still.replace(/\\/g, '/') : '',
    thumb: typeof src.thumb === 'string' ? src.thumb.replace(/\\/g, '/') : ''
  }
}

function normalizeLibrary(raw) {
  const src = raw && typeof raw === 'object' ? raw : null
  if (!src || !Array.isArray(src.items)) return null
  const items = []
  for (const entry of src.items) {
    const item = normalizeWallpaperItem(entry)
    if (item) items.push(item)
  }
  return {
    schema: finiteNumber(src.schema, 1),
    generatedAt: finiteNumber(src.generatedAt, 0),
    weDir: typeof src.weDir === 'string' ? src.weDir : '',
    workshopRoot: typeof src.workshopRoot === 'string' ? src.workshopRoot : '',
    counts: src.counts && typeof src.counts === 'object' ? src.counts : null,
    items
  }
}

/** 读 library.json；不存在 / 解析失败 / 结构不对都返回 null（= library-missing）。 */
function readLibrary() {
  let stat
  try {
    stat = fs.statSync(LIBRARY_FILE)
  } catch (err) {
    resetLibraryCache()
    return null
  }
  const stamp = String(Math.round(stat.mtimeMs)) + ':' + String(stat.size)
  if (libraryCacheStamp === stamp && libraryCacheValue) return libraryCacheValue
  try {
    const parsed = JSON.parse(fs.readFileSync(LIBRARY_FILE, 'utf8'))
    const library = normalizeLibrary(parsed)
    if (!library) {
      resetLibraryCache()
      return null
    }
    libraryCacheStamp = stamp
    libraryCacheValue = library
    return library
  } catch (err) {
    resetLibraryCache()
    return null
  }
}

function resetLibraryCache() {
  libraryCacheStamp = ''
  libraryCacheValue = null
}

function readBuildStatus() {
  try {
    const parsed = JSON.parse(fs.readFileSync(BUILD_STATUS_FILE, 'utf8'))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return Object.assign({}, DEFAULT_BUILD_STATUS)
    }
    return Object.assign({}, DEFAULT_BUILD_STATUS, parsed)
  } catch (err) {
    return Object.assign({}, DEFAULT_BUILD_STATUS)
  }
}

/** 计数：优先用 Builder 写的 counts，但 built 必须等于实际条目数。 */
function wallpaperCounts(library) {
  const counts = {
    total: library.items.length,
    scene: 0,
    video: 0,
    web: 0,
    other: 0,
    built: library.items.length
  }
  for (const item of library.items) counts[item.type] += 1
  if (library.counts) {
    for (const key of ['total', 'scene', 'video', 'web', 'other']) {
      const num = finiteNumber(library.counts[key], null)
      if (num !== null) counts[key] = num
    }
  }
  return counts
}

function wallpaperUrl(id, kind) {
  return WALLPAPER_ROUTE + '?id=' + encodeURIComponent(id) + '&kind=' + kind
}

/** 清单接口的条目视图：只给浏览器需要的字段 + 两个图片 URL。 */
function toWallpaperView(item) {
  return {
    id: item.id,
    title: item.title,
    type: item.type,
    playlistIndex: item.playlistIndex,
    current: item.current,
    tags: item.tags,
    filesize: item.filesize,
    subscriptiondate: item.subscriptiondate,
    width: item.width,
    height: item.height,
    source: item.source,
    palette: item.palette,
    thumb: wallpaperUrl(item.id, 'thumb'),
    still: wallpaperUrl(item.id, 'still')
  }
}

/** Windows 路径大小写不敏感；其他平台按字节比较。 */
function samePath(left, right) {
  if (!left || !right) return false
  const a = path.resolve(String(left))
  const b = path.resolve(String(right))
  if (process.platform === 'win32') return a.toLowerCase() === b.toLowerCase()
  return a === b
}

/** 条目里声明的 still 相对路径 → 缓存根内的绝对路径；越界/缺失返回 null。 */
function wallpaperStillPath(item) {
  const root = path.resolve(WALLPAPER_CACHE)
  if (!item || !item.still) return null
  const file = path.resolve(root, item.still)
  const relative = path.relative(root, file)
  if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    return null
  }
  return file
}

/** 当前配置的 imagePath 是否指向库里某一项的 still。 */
function resolveSelection(library, config) {
  if (!config.imagePath) return { selectedId: null, selectedCustom: false }
  if (library) {
    for (const item of library.items) {
      const file = wallpaperStillPath(item)
      if (file && samePath(file, config.imagePath)) {
        return { selectedId: item.id, selectedCustom: false }
      }
    }
  }
  return { selectedId: null, selectedCustom: true }
}

/**
 * id + kind 收敛成缓存根内的绝对文件路径。
 * id 先过白名单正则，resolve 后再确认没跑出缓存根（双重防目录穿越）。
 */
function resolveWallpaperFile(id, kind) {
  const rawId = id === null || id === undefined ? '' : String(id)
  const rawKind = kind === null || kind === undefined ? '' : String(kind)
  if (!WALLPAPER_ID_RE.test(rawId)) return null
  if (!Object.prototype.hasOwnProperty.call(WALLPAPER_KINDS, rawKind)) return null
  const root = path.resolve(WALLPAPER_CACHE)
  const file = path.resolve(root, WALLPAPER_KINDS[rawKind], rawId + '.jpg')
  const relative = path.relative(root, file)
  if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    return null
  }
  return file
}

function etagMatches(header, etag) {
  if (!header) return false
  const tags = String(header).split(',').map((tag) => tag.trim())
  return tags.includes(etag) || tags.includes('*') || tags.includes('W/' + etag)
}

function requestMethod(req) {
  return String((req && req.method) || 'GET').toUpperCase()
}

function requestUrl(req) {
  try {
    return new URL(String((req && req.url) || '/'), 'http://localhost')
  } catch (err) {
    return new URL('/', 'http://localhost')
  }
}

/* ============================================================================
 * 后台构建进程
 * ----------------------------------------------------------------------------
 * DSH Host 进程本身是 Electron 二进制，process.execPath 指向的是 Harness 的
 * exe 而不是 node.exe。Electron 提供了 ELECTRON_RUN_AS_NODE=1：带着它启动
 * 同一枚可执行文件就退化成纯 Node，脚本才能正常跑。普通 node 环境不要设。
 * ========================================================================== */

function builderEnv(versions = process.versions) {
  const env = Object.assign({}, process.env, {
    DSH_HOME,
    DSH_CHAT_BG_CACHE: WALLPAPER_CACHE
  })
  if (versions && versions.electron) env.ELECTRON_RUN_AS_NODE = '1'
  return env
}

function builderArgs(script, mode) {
  return [script, '--mode', mode, '--cache', WALLPAPER_CACHE]
}

/**
 * 拉起构建进程。返回 { ok, error }。
 * 测试用 env DSH_CHAT_BG_SPAWN=off 只走「受理」分支，不真的起进程。
 */
function startBuilder(script, mode) {
  if (process.env.DSH_CHAT_BG_SPAWN === 'off') return { ok: true, spawned: false }
  try {
    const child = spawn(process.execPath, builderArgs(script, mode), {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: builderEnv()
    })
    child.on('error', () => { /* 子进程错误不冒泡到 Host 进程 */ })
    child.unref()
    return { ok: true, spawned: true }
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) }
  }
}

const name = NS
const inject = ['webServer', 'connection']

function resolveWebServer(ctx) {
  try {
    const viaGet = typeof ctx.get === 'function' ? ctx.get('webServer') : undefined
    if (viaGet) return viaGet
  } catch (err) { /* 取不到就当没有 */ }
  return ctx.webServer
}

function hasRoutes(server) {
  return !!server && typeof server.register === 'function' && typeof server.tapIndex === 'function'
}

function apply(ctx) {
  const disposers = []
  const webServer = resolveWebServer(ctx)

  /* 桌面端若用 file:// + IPC 下发前端，就没有可注册路由的载体。
     此时客户端半侧回落到 localStorage 配置（只支持 imageUrl），不影响加载。 */
  if (!hasRoutes(webServer)) {
    try {
      ctx.logger?.warn?.(`[${NS}] 当前 profile 没有可用的 webServer，Host 配置接口跳过，改由浏览器侧自持配置。`)
    } catch (err) { /* 日志失败不影响加载 */ }
    return
  }

  function rejected(req, res) {
    try {
      const conn = (typeof ctx.get === 'function' ? ctx.get('connection') : undefined) || ctx.connection
      if (!conn || typeof conn.requestRejection !== 'function') return false
      const code = conn.requestRejection(req)
      if (code === undefined || code === null || code === false) return false
      res.statusCode = typeof code === 'number' ? code : 403
      res.end()
      return true
    } catch (err) {
      return false
    }
  }

  function register(route) {
    const inner = route.handler
    return webServer.register(Object.assign({}, route, {
      handler: async (req, res) => {
        if (rejected(req, res)) return
        return inner(req, res)
      }
    }))
  }

  function sendJson(res, code, payload) {
    const body = Buffer.from(JSON.stringify(payload), 'utf8')
    res.writeHead(code, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Content-Length': String(body.length)
    })
    res.end(body)
  }

  function readBody(req, limit = 256 * 1024) {
    return new Promise((resolve) => {
      let size = 0
      const chunks = []
      req.on('data', (chunk) => {
        size += chunk.length
        if (size > limit) {
          req.destroy()
          resolve('')
          return
        }
        chunks.push(chunk)
      })
      req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
      req.on('error', () => resolve(''))
    })
  }

  disposers.push(register({
    kind: 'exact',
    path: ROUTE_BASE + '/config',
    handler: async (req, res) => {
      const method = String(req.method || 'GET').toUpperCase()
      if (method === 'GET') {
        const config = readConfig()
        sendJson(res, 200, {
          ok: true,
          version: PLUGIN_VERSION,
          config,
          imageVersion: config.imagePath ? imageVersion(config.imagePath) : ''
        })
        return
      }
      if (method !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'method not allowed' })
        return
      }
      const text = await readBody(req)
      if (!text) {
        sendJson(res, 400, { ok: false, error: 'empty body' })
        return
      }
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: 'invalid json' })
        return
      }
      try {
        const config = writeConfig(sanitize(parsed))
        sendJson(res, 200, {
          ok: true,
          version: PLUGIN_VERSION,
          config,
          imageVersion: config.imagePath ? imageVersion(config.imagePath) : ''
        })
      } catch (err) {
        sendJson(res, 500, { ok: false, error: String(err) })
      }
    }
  }))

  disposers.push(register({
    kind: 'exact',
    path: ROUTE_BASE + '/image',
    handler: (req, res) => {
      const config = readConfig()
      const file = config.imagePath
      if (!file) { res.writeHead(404); res.end(); return }
      const type = MIME[path.extname(file).toLowerCase()]
      if (!type) { res.writeHead(415); res.end(); return }
      let bytes
      try {
        const stat = fs.statSync(file)
        if (!stat.isFile() || stat.size > MAX_IMAGE_BYTES) { res.writeHead(413); res.end(); return }
        bytes = fs.readFileSync(file)
      } catch (err) {
        res.writeHead(404); res.end(); return
      }
      res.writeHead(200, {
        'Content-Type': type,
        'Cache-Control': 'no-store',
        'Content-Length': String(bytes.length)
      })
      res.end(bytes)
    }
  }))

  /* ── 壁纸库清单 ──────────────────────────────────────────────────────── */

  disposers.push(register({
    kind: 'exact',
    path: ROUTE_BASE + '/wallpapers',
    handler: (req, res) => {
      if (requestMethod(req) !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'method not allowed' })
        return
      }
      const build = readBuildStatus()
      const library = readLibrary()
      if (!library) {
        sendJson(res, 200, {
          ok: false,
          version: PLUGIN_VERSION,
          error: 'library-missing',
          build,
          message: '壁纸库还没生成：先点「重新扫描/生成」，或运行 node tools/build-library.mjs。'
        })
        return
      }
      const selection = resolveSelection(library, readConfig())
      sendJson(res, 200, {
        ok: true,
        version: PLUGIN_VERSION,
        counts: wallpaperCounts(library),
        build,
        selectedId: selection.selectedId,
        selectedCustom: selection.selectedCustom,
        items: library.items.map(toWallpaperView)
      })
    }
  }))

  /* ── 壁纸图片字节流（still / thumb） ─────────────────────────────────── */

  disposers.push(register({
    kind: 'exact',
    path: WALLPAPER_ROUTE,
    handler: (req, res) => {
      if (requestMethod(req) !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'method not allowed' })
        return
      }
      const url = requestUrl(req)
      const file = resolveWallpaperFile(url.searchParams.get('id'), url.searchParams.get('kind'))
      if (!file) { res.writeHead(400); res.end(); return }
      let stat
      try {
        stat = fs.statSync(file)
        if (!stat.isFile()) { res.writeHead(404); res.end(); return }
      } catch (err) {
        res.writeHead(404); res.end(); return
      }
      const etag = '"' + String(stat.size) + '-' + String(Math.round(stat.mtimeMs)) + '"'
      const headers = {
        'Content-Type': 'image/jpeg',
        'Cache-Control': WALLPAPER_CACHE_CONTROL,
        'ETag': etag
      }
      if (etagMatches(req.headers && req.headers['if-none-match'], etag)) {
        res.writeHead(304, headers)
        res.end()
        return
      }
      let bytes
      try {
        bytes = fs.readFileSync(file)
      } catch (err) {
        res.writeHead(404); res.end(); return
      }
      headers['Content-Length'] = String(bytes.length)
      res.writeHead(200, headers)
      res.end(bytes)
    }
  }))

  /* ── 启动后台构建 ────────────────────────────────────────────────────── */

  disposers.push(register({
    kind: 'exact',
    path: ROUTE_BASE + '/wallpapers/refresh',
    handler: async (req, res) => {
      if (requestMethod(req) !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'method not allowed' })
        return
      }
      const text = await readBody(req)
      let mode = 'missing'
      if (text) {
        let parsed
        try {
          parsed = JSON.parse(text)
        } catch (err) {
          sendJson(res, 400, { ok: false, error: 'invalid json' })
          return
        }
        if (parsed && typeof parsed === 'object' && parsed.mode === 'force') mode = 'force'
      }
      const build = readBuildStatus()
      if (build.state === 'running') {
        sendJson(res, 200, { ok: true, accepted: false, build })
        return
      }
      let scriptOk = false
      try {
        scriptOk = fs.statSync(builderScript).isFile()
      } catch (err) {
        scriptOk = false
      }
      if (!scriptOk) {
        sendJson(res, 500, {
          ok: false,
          error: 'builder-missing',
          message: '找不到生成脚本：' + builderScript
        })
        return
      }
      const started = startBuilder(builderScript, mode)
      if (!started.ok) {
        sendJson(res, 500, { ok: false, error: started.error })
        return
      }
      const now = Date.now()
      sendJson(res, 200, {
        ok: true,
        accepted: true,
        build: Object.assign({}, build, {
          state: 'running',
          mode,
          startedAt: now,
          updatedAt: now,
          finishedAt: 0,
          done: 0,
          errors: [],
          current: '',
          message: mode === 'force' ? '正在重建全部壁纸封面' : '正在补齐缺失的壁纸封面'
        })
      })
    }
  }))

  /* ── 选中壁纸：写回配置（和设置页保存同一条路径） ───────────────────── */

  disposers.push(register({
    kind: 'exact',
    path: ROUTE_BASE + '/wallpapers/select',
    handler: async (req, res) => {
      if (requestMethod(req) !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'method not allowed' })
        return
      }
      const text = await readBody(req)
      if (!text) {
        sendJson(res, 400, { ok: false, error: 'empty body' })
        return
      }
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: 'invalid json' })
        return
      }
      const notFound = () => sendJson(res, 404, { ok: false, error: 'wallpaper-not-found' })
      const id = parsed && parsed.id !== null && parsed.id !== undefined ? String(parsed.id).trim() : ''
      if (!WALLPAPER_ID_RE.test(id)) { notFound(); return }
      const library = readLibrary()
      const item = library ? library.items.find((entry) => entry.id === id) : null
      if (!item) { notFound(); return }
      /* still 用条目声明的相对路径（校验在缓存根内）；缺失时退回按 id 推导的规范路径。 */
      const file = wallpaperStillPath(item) || resolveWallpaperFile(item.id, 'still')
      if (!file) { notFound(); return }
      try {
        const stat = fs.statSync(file)
        if (!stat.isFile()) { notFound(); return }
      } catch (err) {
        notFound(); return
      }
      try {
        const current = readConfig()
        const config = writeConfig(sanitize(Object.assign({}, current, {
          enabled: true,
          mode: 'image',
          imagePath: file,
          imageUrl: ''
        })))
        sendJson(res, 200, {
          ok: true,
          config,
          imageVersion: imageVersion(file),
          item: { id: item.id, title: item.title }
        })
      } catch (err) {
        sendJson(res, 500, { ok: false, error: String(err) })
      }
    }
  }))

  ctx.effect(() => () => {
    for (const dispose of disposers) {
      try { dispose() } catch (err) { /* noop */ }
    }
  })
}

const __test = {
  WALLPAPER_CACHE,
  LIBRARY_FILE,
  BUILD_STATUS_FILE,
  CONFIG_FILE,
  BUILDER_SCRIPT,
  PLUGIN_VERSION,
  DEFAULT_BUILD_STATUS,
  readLibrary,
  readBuildStatus,
  resetLibraryCache,
  resolveWallpaperFile,
  wallpaperStillPath,
  wallpaperCounts,
  resolveSelection,
  normalizeLibrary,
  samePath,
  builderEnv,
  builderArgs,
  getBuilderScript: () => builderScript,
  setBuilderScript: (file) => { builderScript = file ? String(file) : BUILDER_SCRIPT }
}

export { apply, inject, name, __test }
