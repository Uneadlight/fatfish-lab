/* ============================================================================
 * dsh-chat-background — Builder：把 Wallpaper Engine 创意工坊壁纸做成静态封面缓存
 * ----------------------------------------------------------------------------
 * 契约见 docs/INTERFACES.md 第 1/2 节。产物全部写到 <cacheRoot>：
 *   library.json / build-status.json / state.json / build.log / stills/ / thumbs/
 *
 * 处理流程：
 *   1) 探测 ffmpeg、Chrome、Wallpaper Engine 与工坊目录（探测顺序严格按契约）；
 *   2) 合并 workshopcache.json + config.json 播放列表 + project.json 元数据；
 *   3) 按播放列表顺序逐条生成 16:9 静态图（并发 4 个 worker）：
 *        scene  → 整文件扫描 scene.pkg 内嵌 PNG/JPEG，挑合法且面积最大的横图
 *        video  → ffmpeg -ss 2 + thumbnail=90 抽一帧
 *        web    → Chrome headless 截图
 *        失败   → 降级 preview-composite（方形 preview 居中 + 两侧模糊铺满）
 *   4) 另生成 480x270 缩略图，最后原子写出完整 library.json。
 *
 * 为什么 scene.pkg 要整文件扫签名：PKGV0001..0024 的头/索引结构并不一致，
 * 按版本解析会踩坑；PNG/JPEG 签名 + 尺寸校验反而稳定，4GB 全量扫描约 4 秒。
 *
 * 所有 ffmpeg 调用都用 child_process.spawnSync（契约要求），并发靠
 * worker_threads 实现——每个 worker 线程内部同步跑 ffmpeg，互不阻塞。
 * ========================================================================== */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads'

const BUILDER_FILE = fileURLToPath(import.meta.url)

/** 清单 schema 版本，与 Host/Client 对齐。 */
export const SCHEMA = 1
/** 并发 worker 数（契约：4）。 */
export const CONCURRENCY = 4
/** scene.pkg 内嵌图的合法性约束（契约第 2 节）。 */
const MIN_AREA = 1280 * 720
const MAX_DIM = 8192
const RATIO_MIN = 0.3
const RATIO_MAX = 4
/** 选图启发式：横图优先的宽高比区间；只有竖图时交给 preview-composite。 */
export const LANDSCAPE_MIN_RATIO = 1.2
export const LANDSCAPE_MAX_RATIO = 3
/** still 最长边上限与缩略图尺寸（契约第 1 节）。 */
const STILL_MAX_WIDTH = 3840
const THUMB_WIDTH = 480
const THUMB_HEIGHT = 270
/** build.log 超过 2MB 时重建（契约第 1 节）。 */
const LOG_MAX_BYTES = 2 * 1024 * 1024
/** web 截图超时（契约：45s）。 */
const CHROME_TIMEOUT_MS = 45000

/** 契约里的缩放裁切过滤器；末尾补一个偶数尺寸兜底，避免 yuvj420p 拒绝奇数边。 */
export const STILL_FILTER =
  "scale='if(gt(iw,3840),3840,iw)':-2,crop='min(iw,ih*16/9)':'min(ih,iw*9/16)'"
const EVEN_FILTER = "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"
const STILL_FILTER_FULL = `${STILL_FILTER},${EVEN_FILTER}`

/**
 * preview-composite：同一张 preview 拆两路，一路模糊铺满 1920x1080 当背景，
 * 一路按 96% 高度居中当前景。
 */
export const COMPOSITE_FILTER =
  "[0:v]split=2[bg0][fg0];" +
  "[bg0]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=24[bg];" +
  "[fg0]scale=-2:1036[fg];" +
  "[bg][fg]overlay=(W-w)/2:(H-h)/2"

const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const JPG_SIG = Buffer.from([0xff, 0xd8, 0xff])
const PNG_IEND = Buffer.from('IEND')
const JPG_EOI = Buffer.from([0xff, 0xd9])
const PREVIEW_RE = /^preview\.(jpe?g|png|gif|webp|bmp)$/i
const VIDEO_RE = /\.(mp4|webm|mkv|mov|avi|m4v)$/i
const HTML_RE = /\.html?$/i

/** 壁纸 type 只允许这四个值（契约第 1 节）。 */
const TYPES = ['scene', 'video', 'web', 'other']

/** ffmpeg 已知安装路径通配（契约探测顺序第 3 步）。 */
const FFMPEG_GLOBS = [
  'E:/JianyingPro/*/ffmpeg.exe',
  'D:/JianyingPro/*/ffmpeg.exe',
  'C:/Program Files/ffmpeg*/bin/ffmpeg.exe'
]

/** Chrome / Edge 已知路径（契约探测顺序）。 */
const CHROME_PATHS = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
]

/** Steam 库根候选（契约第 2 节，另加所有盘符的 SteamLibrary/Steam）。 */
const STEAM_ROOTS = [
  'C:/Program Files (x86)/Steam',
  'C:/Program Files/Steam',
  'C:/Steam',
  'D:/SteamLibrary',
  'D:/Steam',
  'E:/SteamLibrary',
  'E:/Steam',
  'F:/SteamLibrary'
]

// ============================================================================
// 一、纯函数区（测试直接 import；不碰文件系统、不 spawn）
// ============================================================================

/** 路径转 POSIX 形式（library.json 里的 relative path 用）。 */
export function toPosixPath(p) {
  return String(p == null ? '' : p).replace(/\\/g, '/')
}

/** 条目在缓存根下的四个路径；relative 一律 POSIX。 */
export function itemPaths(cacheRoot, id) {
  const sid = String(id)
  return {
    stillRel: `stills/${sid}.jpg`,
    thumbRel: `thumbs/${sid}.jpg`,
    stillAbs: path.join(cacheRoot, 'stills', `${sid}.jpg`),
    thumbAbs: path.join(cacheRoot, 'thumbs', `${sid}.jpg`)
  }
}

/** 尺寸是否满足契约的合法内嵌图约束。 */
export function isValidImageSize(w, h) {
  if (!Number.isInteger(w) || !Number.isInteger(h)) return false
  if (w <= 0 || h <= 0) return false
  if (w > MAX_DIM || h > MAX_DIM) return false
  if (w * h < MIN_AREA) return false
  const ratio = w / h
  return ratio >= RATIO_MIN && ratio <= RATIO_MAX
}

/** PNG colorType 0/4 是灰度（Alpha）掩码，通常不是壁纸本身。 */
export function isColorImage(img) {
  if (!img) return false
  if (img.kind === 'jpg') return true
  return img.colorType !== 0 && img.colorType !== 4
}

/**
 * 从 scene.pkg 的整文件字节里扫描所有结构合法的 PNG/JPEG 内嵌图。
 * 只做签名 + 尺寸解析，不做解码；返回按面积降序排列的候选。
 */
export function scanPkgImages(buf) {
  const images = []
  if (!Buffer.isBuffer(buf) || buf.length < 16) return images

  let i = 0
  while (true) {
    const at = buf.indexOf(PNG_SIG, i)
    if (at < 0) break
    const img = readPngHeader(buf, at)
    if (img) {
      images.push(img)
      i = img.end
    } else {
      i = at + PNG_SIG.length
    }
  }

  i = 0
  while (true) {
    const at = buf.indexOf(JPG_SIG, i)
    if (at < 0) break
    const img = readJpgHeader(buf, at)
    if (img) {
      images.push(img)
      i = img.end
    } else {
      i = at + JPG_SIG.length
    }
  }

  images.sort((a, b) => b.w * b.h - a.w * a.h)
  return images
}

/** 解析 offset 处的 PNG：验 IHDR，取尺寸，用 IEND 定尾。 */
function readPngHeader(buf, at) {
  if (at + 33 > buf.length) return null
  if (buf.toString('latin1', at + 12, at + 16) !== 'IHDR') return null
  const w = buf.readUInt32BE(at + 16)
  const h = buf.readUInt32BE(at + 20)
  const colorType = buf[at + 25]
  const iend = buf.indexOf(PNG_IEND, at + 33)
  if (iend < 0) return null
  return { kind: 'png', w, h, colorType, off: at, end: iend + 8 }
}

/** 解析 offset 处的 JPEG：严格走 marker 段找 SOF 尺寸，用 EOI 定尾。 */
function readJpgHeader(buf, at) {
  if (at + 4 > buf.length) return null
  let p = at + 2
  let dims = null
  let guard = 0
  while (p + 1 < buf.length && guard++ < 512) {
    if (buf[p] !== 0xff) return null
    let marker = buf[p + 1]
    while (marker === 0xff && p + 2 < buf.length) {
      p++
      marker = buf[p + 1]
    }
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0xd8) {
      p += 2
      continue
    }
    if (marker === 0xd9) break
    if (p + 4 > buf.length) return null
    const len = buf.readUInt16BE(p + 2)
    if (len < 2 || p + 2 + len > buf.length) return null
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      if (len < 7 || p + 9 > buf.length) return null
      dims = { w: buf.readUInt16BE(p + 7), h: buf.readUInt16BE(p + 5) }
    }
    if (marker === 0xda) break
    p += 2 + len
  }
  if (!dims) return null
  const eoi = buf.indexOf(JPG_EOI, p)
  if (eoi < 0) return null
  return { kind: 'jpg', w: dims.w, h: dims.h, off: at, end: eoi + 2 }
}

/**
 * 把候选内嵌图排成“可信度顺序”：横图 > 近横图 > 竖图，同一档里彩色优先、面积降序。
 * 返回完整有序列表，供“第一张是黑屏/纯色时换下一张”的降级逻辑使用。
 */
export function rankEmbeddedImages(images) {
  const valid = (images || []).filter((img) => img && isValidImageSize(img.w, img.h))
  if (!valid.length) return []
  const byArea = (list) => list.slice().sort((a, b) => b.w * b.h - a.w * a.h)
  const landscape = byArea(valid.filter((img) => {
    const ratio = img.w / img.h
    return ratio >= LANDSCAPE_MIN_RATIO && ratio <= LANDSCAPE_MAX_RATIO
  }))
  const mild = byArea(valid.filter((img) => img.w / img.h >= 0.8))
  const ordered = [
    ...byArea(landscape.filter(isColorImage)),
    ...byArea(landscape.filter((img) => !isColorImage(img))),
    ...byArea(mild.filter(isColorImage)),
    ...byArea(mild.filter((img) => !isColorImage(img)))
  ]
  const seen = new Set()
  const out = []
  for (const img of ordered) {
    const key = `${img.kind}:${img.off}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(img)
  }
  return out
}

/**
 * 从候选里选出用作 still 的内嵌图：就是 rankEmbeddedImages 的第一张。
 * 规则（契约约束 + QA 后的防错增强）：
 *   1. 先按契约过滤：0<w,h≤8192、面积≥1280x720、宽高比∈[0.3,4]；
 *   2. 横图（比∈[1.2,3]）中取面积最大者，且优先非灰度 PNG；
 *   3. 没有横图时退到比值≥0.8 的图；
 *   4. 只剩竖图/极端长图 → 返回 null，让整张 preview 合成图兜底
 *      （scene 的 preview 是渲染后的整幅画面，竖图多半是素材层）。
 */
export function selectEmbeddedImage(images) {
  return rankEmbeddedImages(images)[0] || null
}

/** 去掉 UTF-8 BOM（部分 project.json 带 BOM）。 */
export function stripBom(text) {
  return typeof text === 'string' && text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
}

/**
 * project.json 容错解析：正常 JSON 直接过；失败时去掉尾逗号/注释再试一次。
 * 仍失败则抛错，由调用方按“无 project.json”处理。
 */
export function parseProjectJsonText(text) {
  const src = stripBom(String(text == null ? '' : text)).trim()
  if (!src) throw new Error('project.json 为空')
  try {
    return JSON.parse(src)
  } catch {
    const cleaned = src
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/.*$/gm, '$1')
      .replace(/,\s*([}\]])/g, '$1')
    return JSON.parse(cleaned)
  }
}

/** type 归一化：Video/Scene/Web → 小写；未知一律 other。 */
export function normalizeType(raw) {
  const value = String(raw == null ? '' : raw).trim().toLowerCase()
  return TYPES.includes(value) ? value : 'other'
}

/** 合法 tag 列表：去重、转字符串、过滤空值。 */
export function normalizeTags(raw) {
  if (!Array.isArray(raw)) return []
  const out = []
  for (const tag of raw) {
    const value = String(tag == null ? '' : tag).trim()
    if (value && !out.includes(value)) out.push(value)
  }
  return out
}

/**
 * 元数据合并：project.json 优先，其次 workshopcache，最后 id 兜底。
 * 纯函数，方便测试。
 */
export function mergeItemMetadata({ id, dir = '', cacheEntry = null, projectJson = null, playlistIndex = null, current = false }) {
  const project = projectJson || {}
  const cache = cacheEntry || {}
  const title = String(project.title || cache.title || '').trim() || `壁纸 ${id}`
  return {
    id: String(id),
    title,
    type: normalizeType(project.type || cache.type),
    playlistIndex: Number.isInteger(playlistIndex) ? playlistIndex : null,
    current: !!current,
    tags: normalizeTags(project.tags != null ? project.tags : cache.tags),
    filesize: Number(cache.filesize) > 0 ? Number(cache.filesize) : 0,
    subscriptiondate: Number(cache.subscriptiondate) > 0 ? Number(cache.subscriptiondate) : 0,
    dir
  }
}

/**
 * 排序：播放列表里的按 1-based 下标升序在前，不在列表里的按标题中文排序在后。
 */
export function sortLibraryItems(items) {
  return (items || []).slice().sort((a, b) => {
    const pa = Number.isInteger(a.playlistIndex) ? a.playlistIndex : Infinity
    const pb = Number.isInteger(b.playlistIndex) ? b.playlistIndex : Infinity
    if (pa !== pb) return pa - pb
    if (pa === Infinity) return String(a.title).localeCompare(String(b.title), 'zh')
    return 0
  })
}

/** 从 "D:/.../431960/<id>/xxx.pkg" 这样的绝对路径里取壁纸 id。 */
export function idFromWorkshopPath(file) {
  if (typeof file !== 'string' || !file) return null
  const parts = toPosixPath(file).split('/')
  const at = parts.indexOf('431960')
  if (at >= 0 && at + 1 < parts.length && /^\d+$/.test(parts[at + 1])) return parts[at + 1]
  return null
}

/** 取 config.json 里 Monitor0 的那段壁纸配置（可能不存在）。 */
export function getMonitorConfig(config) {
  return (
    config &&
    config.Administrator &&
    config.Administrator.general &&
    config.Administrator.general.wallpaperconfig &&
    config.Administrator.general.wallpaperconfig.selectedwallpapers &&
    config.Administrator.general.wallpaperconfig.selectedwallpapers.Monitor0
  ) || null
}

/**
 * 解析 WE 播放列表：id → 1-based 下标（保存出现的第一次）。
 * 输入是 config.json 内部的路径数组。
 */
export function collectPlaylistIndex(config) {
  const map = new Map()
  const monitor = getMonitorConfig(config)
  const items = monitor && monitor.playlist && monitor.playlist.items
  if (!Array.isArray(items)) return map
  items.forEach((file, index) => {
    const id = idFromWorkshopPath(file)
    if (id && !map.has(id)) map.set(id, index + 1)
  })
  return map
}

/** 从 config.json 的 selectedwallpapers.Monitor0.file 取当前壁纸 id。 */
export function collectCurrentId(config) {
  const monitor = getMonitorConfig(config)
  return monitor ? idFromWorkshopPath(monitor.file) : null
}

/**
 * 解析 WE 壁纸文件夹树（general.browser.folders），返回 id → 文件夹路径。
 * WE 的 folders 是数组，每项形如 { title, type:'folder', items:{id:1,...}, subfolders:[...] }；
 * 这里把嵌套路径拼成 "父/子" 形式，例如 "1/景"。
 */
export function collectFolderMap(config) {
  const map = new Map()
  const folders =
    config &&
    config.Administrator &&
    config.Administrator.general &&
    config.Administrator.general.browser &&
    config.Administrator.general.browser.folders
  if (!Array.isArray(folders)) return map
  const walk = (node, parentPath) => {
    if (!node || typeof node !== 'object') return
    const title = String(node.title == null ? '' : node.title).trim()
    const here = title ? (parentPath ? parentPath + '/' + title : title) : parentPath
    const items = node.items && typeof node.items === 'object' ? Object.keys(node.items) : []
    for (const id of items) {
      if (/^\d+$/.test(id) && !map.has(id)) map.set(id, here)
    }
    const subfolders = Array.isArray(node.subfolders) ? node.subfolders : []
    for (const sub of subfolders) walk(sub, here)
  }
  for (const folder of folders) walk(folder, '')
  return map
}

/** 文件夹路径是否命中隐藏列表（支持整条路径、任意一段、子串结尾匹配）。 */
export function isHiddenFolder(folderPath, hiddenFolders) {
  if (!folderPath) return false
  const value = String(folderPath)
  const segments = value.split('/')
  return (hiddenFolders || []).some((entry) => {
    const needle = String(entry == null ? '' : entry).trim()
    if (!needle) return false
    return value === needle || segments.includes(needle) || value.endsWith('/' + needle)
  })
}

/**
 * 读取缓存根下的可见性配置 visibility.json：
 *   { "playlistOnly": true, "hiddenFolders": ["新文件夹2"] }
 * 缺省时不过滤（返回 false / []），方便其他机器开箱即用。
 */
export function readVisibility(cacheRoot) {
  const raw = readJsonFile(path.join(cacheRoot, 'visibility.json'))
  const src = raw && typeof raw === 'object' ? raw : {}
  return {
    playlistOnly: src.playlistOnly === true,
    hiddenFolders: Array.isArray(src.hiddenFolders)
      ? src.hiddenFolders.map((value) => String(value == null ? '' : value).trim()).filter(Boolean)
      : []
  }
}

/** 按 visibility.json 过滤条目；纯函数，测试直接用。 */
export function filterVisibleItems(items, visibility) {
  const source = Array.isArray(items) ? items : []
  const opts = visibility || {}
  const hidden = Array.isArray(opts.hiddenFolders) ? opts.hiddenFolders : []
  return source.filter((item) => {
    if (!item) return false
    if (opts.playlistOnly === true && !Number.isInteger(item.playlistIndex)) return false
    if (hidden.length && isHiddenFolder(item.folder, hidden)) return false
    return true
  })
}

/** 默认缓存根：env DSH_CHAT_BG_CACHE 覆盖，否则 <DSH_HOME>/dsh-chat-background/wallpapers。 */
export function defaultCacheRoot(env = process.env) {
  if (env.DSH_CHAT_BG_CACHE) return path.resolve(env.DSH_CHAT_BG_CACHE)
  const dshHome = env.DSH_HOME ? path.resolve(env.DSH_HOME) : path.join(os.homedir(), '.dsh')
  return path.join(dshHome, 'dsh-chat-background', 'wallpapers')
}

/** CLI 参数解析（契约第 2 节的全部开关）。 */
export function parseArgs(argv = []) {
  const args = { mode: 'missing', cache: null, limit: null, ids: null, quiet: false, help: false }
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i]
    const next = () => {
      const value = argv[++i]
      if (value === undefined) throw new Error(`${flag} 缺少参数`)
      return value
    }
    if (flag === '--mode') {
      const value = next()
      if (value !== 'missing' && value !== 'force') throw new Error(`--mode 只能是 missing 或 force，收到 ${value}`)
      args.mode = value
    } else if (flag === '--cache') {
      args.cache = path.resolve(next())
    } else if (flag === '--limit') {
      const value = Number(next())
      if (!Number.isInteger(value) || value < 0) throw new Error('--limit 需要非负整数')
      args.limit = value
    } else if (flag === '--ids') {
      const ids = next().split(',').map((s) => s.trim()).filter((s) => /^\d+$/.test(s))
      if (!ids.length) throw new Error('--ids 需要逗号分隔的纯数字 id')
      args.ids = ids
    } else if (flag === '--quiet') {
      args.quiet = true
    } else if (flag === '--help' || flag === '-h') {
      args.help = true
    } else {
      throw new Error(`未知参数 ${flag}`)
    }
  }
  return args
}

/** 从 JPEG 头里读宽高（Builder 自己的输出没有 EXIF，读前 64KB 足够）。 */
export function parseJpegSize(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 4) return null
  if (buf[0] !== 0xff || buf[1] !== 0xd8) return null
  let p = 2
  while (p + 9 < buf.length) {
    if (buf[p] !== 0xff) {
      p++
      continue
    }
    const marker = buf[p + 1]
    if (marker === 0xd9 || marker === 0xda) break
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { w: buf.readUInt16BE(p + 7), h: buf.readUInt16BE(p + 5) }
    }
    const len = buf.readUInt16BE(p + 2)
    if (len < 2) return null
    p += 2 + len
  }
  return null
}

/** library.json 里 source 字段的允许值。 */
export const SOURCES = ['embedded', 'video', 'web', 'preview-composite', 'preview']

/** type → 没有历史记录时推断的 source（仅用于复用旧缓存文件的条目）。 */
export function defaultSourceForType(type) {
  if (type === 'scene') return 'embedded'
  if (type === 'video') return 'video'
  if (type === 'web') return 'web'
  return 'preview-composite'
}

// ============================================================================
// 二、环境探测（会读文件系统，但不 spawn 构建任务）
// ============================================================================

/** 判断 exe 能否运行（用于 PATH 里的 ffmpeg）。 */
function executableWorks(exe) {
  if (!exe) return false
  try {
    if (path.isAbsolute(exe) && !fs.existsSync(exe)) return false
    const result = spawnSync(exe, ['-version'], { timeout: 8000, windowsHide: true, stdio: 'ignore' })
    return !!result && result.status === 0
  } catch {
    return false
  }
}

/** 在目录下一层/多层找某个可执行文件名；返回排序后的第一个。 */
function findExecutableUnder(root, fileName, maxDepth) {
  const queue = [{ dir: root, depth: 0 }]
  const hits = []
  while (queue.length) {
    const { dir, depth } = queue.shift()
    let entries = []
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      continue
    }
    entries.sort((a, b) => a.name.localeCompare(b.name))
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isFile() && entry.name.toLowerCase() === fileName.toLowerCase()) hits.push(full)
      else if (entry.isDirectory() && depth < maxDepth) queue.push({ dir: full, depth: depth + 1 })
    }
  }
  return hits[0] || null
}

/** 展开形如 E:/JianyingPro/*&#47;ffmpeg.exe 的单层通配。 */
function expandGlobExecutable(pattern) {
  const parts = toPosixPath(pattern).split('/')
  const starIndex = parts.findIndex((p) => p.includes('*'))
  if (starIndex < 0) return fs.existsSync(pattern) ? pattern : null
  const baseParts = parts.slice(0, starIndex)
  const base = baseParts.join('/') + (baseParts.length ? '/' : '')
  const matcher = parts[starIndex]
  const rest = parts.slice(starIndex + 1)
  let entries = []
  try {
    entries = fs.readdirSync(base, { withFileTypes: true })
  } catch {
    return null
  }
  entries.sort((a, b) => b.name.localeCompare(a.name, 'en', { numeric: true }))
  const re = new RegExp('^' + matcher.split('*').map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$')
  for (const entry of entries) {
    if (!re.test(entry.name)) continue
    const candidate = [base + entry.name, ...rest].join('/')
    if (fs.existsSync(candidate)) return candidate
    if (entry.isDirectory() && rest.length === 0) continue
  }
  return null
}

/** 按契约顺序探测 ffmpeg。 */
export function detectFfmpeg(env = process.env) {
  const envPath = env.DSH_CHAT_BG_FFMPEG
  if (envPath && fs.existsSync(envPath) && executableWorks(envPath)) return envPath
  if (executableWorks('ffmpeg')) return 'ffmpeg'
  for (const glob of FFMPEG_GLOBS) {
    const hit = expandGlobExecutable(glob)
    if (hit && executableWorks(hit)) return hit
  }
  const localAppData = env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
  const wingetRoot = path.join(localAppData, 'Microsoft', 'WinGet', 'Packages')
  const wingetHit = findExecutableUnder(wingetRoot, 'ffmpeg.exe', 4)
  if (wingetHit && executableWorks(wingetHit)) return wingetHit
  return null
}

/** 按契约顺序探测 Chrome（找不到则 web 壁纸走 preview-composite）。 */
export function detectChrome(env = process.env) {
  const envPath = env.DSH_CHAT_BG_CHROME
  if (envPath && fs.existsSync(envPath)) return envPath
  for (const candidate of CHROME_PATHS) if (fs.existsSync(candidate)) return candidate
  return null
}

/** 解析 Steam libraryfolders.vdf，取所有库根。 */
function readSteamLibraryRoots(file) {
  const roots = []
  try {
    const text = fs.readFileSync(file, 'utf8')
    for (const match of text.matchAll(/"path"\s+"([^"]+)"/g)) {
      const root = match[1].replace(/\\\\/g, '\\')
      if (root) roots.push(root)
    }
  } catch {
    // 文件不存在就跳过
  }
  return roots
}

/** 所有盘符的 SteamLibrary / Steam（契约要求覆盖每个盘）。 */
function allDriveSteamRoots() {
  const roots = []
  for (let code = 65; code <= 90; code++) {
    const drive = String.fromCharCode(code)
    roots.push(`${drive}:/SteamLibrary`, `${drive}:/Steam`)
  }
  return roots
}

/** 按契约顺序探测 WE 安装目录与工坊目录。 */
export function detectWe(env = process.env) {
  const weCandidates = []
  const workshopCandidates = []
  if (env.DSH_WE_DIR) weCandidates.push(env.DSH_WE_DIR)
  if (env.DSH_WE_WORKSHOP) workshopCandidates.push(env.DSH_WE_WORKSHOP)

  const roots = []
  const pushRoot = (root) => {
    if (!root) return
    const resolved = path.resolve(root)
    if (!roots.includes(resolved)) roots.push(resolved)
  }
  for (const base of STEAM_ROOTS) pushRoot(base)
  for (const base of STEAM_ROOTS) {
    pushRoot(base)
    pushRoot(path.join(base, '..')) // 有些库根直接是盘符
  }
  for (const base of STEAM_ROOTS) {
    for (const vdf of [
      path.join(base, 'steamapps', 'libraryfolders.vdf'),
      path.join(base, 'config', 'libraryfolders.vdf')
    ]) {
      for (const root of readSteamLibraryRoots(vdf)) pushRoot(root)
    }
  }
  for (const driveRoot of allDriveSteamRoots()) {
    if (fs.existsSync(driveRoot)) pushRoot(driveRoot)
  }

  let weDir = null
  let workshopRoot = null
  for (const root of roots) {
    if (!weDir && fs.existsSync(path.join(root, 'steamapps', 'common', 'wallpaper_engine'))) {
      weDir = path.join(root, 'steamapps', 'common', 'wallpaper_engine')
    }
    if (!workshopRoot && fs.existsSync(path.join(root, 'steamapps', 'workshop', 'content', '431960'))) {
      workshopRoot = path.join(root, 'steamapps', 'workshop', 'content', '431960')
    }
    if (weDir && workshopRoot) break
  }

  // env 显式覆盖优先
  for (const candidate of weCandidates) {
    if (candidate && fs.existsSync(candidate)) {
      weDir = path.resolve(candidate)
      break
    }
  }
  for (const candidate of workshopCandidates) {
    if (candidate && fs.existsSync(candidate)) {
      workshopRoot = path.resolve(candidate)
      break
    }
  }
  return { weDir, workshopRoot }
}

// ============================================================================
// 三、文件小工具
// ============================================================================

function readJsonFile(file) {
  try {
    return JSON.parse(stripBom(fs.readFileSync(file, 'utf8')))
  } catch {
    return null
  }
}

function statSafe(file) {
  try {
    const stat = fs.statSync(file)
    return stat.isFile() ? stat : null
  } catch {
    return null
  }
}

/** 原子写 JSON：同目录 tmp + rename（Windows 下 rename 覆盖已有文件）。 */
function writeJsonAtomic(file, value) {
  const tmp = `${file}.tmp-${process.pid}-${Math.random().toString(36).slice(2, 8)}`
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + '\n', 'utf8')
  fs.renameSync(tmp, file)
}

/** 原子替换一层：ffmpeg 先写 tmp，成功后再改名为最终文件。 */
function replaceFile(tmp, finalFile) {
  fs.renameSync(tmp, finalFile)
}

/** 读 JPEG 输出尺寸（Builder 自己的输出没有 EXIF）。 */
export function readJpegSize(file) {
  let fd
  try {
    fd = fs.openSync(file, 'r')
    const buf = Buffer.alloc(65536)
    const bytes = fs.readSync(fd, buf, 0, buf.length, 0)
    return parseJpegSize(buf.subarray(0, bytes))
  } catch {
    return null
  } finally {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd)
      } catch {
        // ignore
      }
    }
  }
}

/* ============================================================================
 * 壁纸取色（palette）
 * ----------------------------------------------------------------------------
 * 给「浅色方案底色 / 深色方案底色」自动取色：把 still 交给 ffmpeg 缩成
 * 32x18 的 RGB 原始像素，再在 JS 里按饱和度/亮度加权算主色相，最后生成
 * 浅色方案用的浅色系底色和深色方案用的深色系底色。
 * 这样从壁纸库换图时，面板底色会跟着壁纸主色走。
 * ========================================================================== */

const PALETTE_W = 32
const PALETTE_H = 18

/** RGB(0-255) → HSL（h 0-360，s/l 0-1）。 */
export function rgbToHsl(r, g, b) {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return { h: 0, s: 0, l }
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) * 60
  else if (max === gn) h = ((bn - rn) / d + 2) * 60
  else h = ((rn - gn) / d + 4) * 60
  return { h, s, l }
}

/** HSL → #rrggbb。 */
export function hslToHex(h, s, l) {
  const hue = ((Number(h) % 360) + 360) % 360
  const sat = Math.min(1, Math.max(0, Number(s)))
  const lig = Math.min(1, Math.max(0, Number(l)))
  const c = (1 - Math.abs(2 * lig - 1)) * sat
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1))
  const m = lig - c / 2
  let r = 0
  let g = 0
  let b = 0
  if (hue < 60) { r = c; g = x }
  else if (hue < 120) { r = x; g = c }
  else if (hue < 180) { g = c; b = x }
  else if (hue < 240) { g = x; b = c }
  else if (hue < 300) { r = x; b = c }
  else { r = c; b = x }
  const toHex = (value) => Math.round((value + m) * 255).toString(16).padStart(2, '0')
  return '#' + toHex(r) + toHex(g) + toHex(b)
}

const clamp01 = (value) => (value < 0 ? 0 : value > 1 ? 1 : value)

/**
 * 从 RGB24 原始像素 Buffer 算两档底色。纯函数，测试可喂合成数据。
 * - 权重 = 饱和度 × 中等亮度偏好（太黑/太白的像素不计）
 * - 色相用向量平均，避免红/紫跨 0° 时算错
 * - 浅色方案：同色相、低饱和、高亮度；深色方案：同色相、低饱和、低亮度
 */
export function paletteFromPixels(buf) {
  if (!buf || buf.length < 3) return null
  const count = Math.floor(buf.length / 3)
  let weightSum = 0
  let hcos = 0
  let hsin = 0
  let satSum = 0
  let rSum = 0
  let gSum = 0
  let bSum = 0
  for (let i = 0; i < count; i++) {
    const r = buf[i * 3]
    const g = buf[i * 3 + 1]
    const b = buf[i * 3 + 2]
    rSum += r
    gSum += g
    bSum += b
    const { h, s, l } = rgbToHsl(r, g, b)
    if (l < 0.06 || l > 0.96) continue
    const weight = Math.pow(s, 1.15) * (1 - Math.abs(2 * l - 1))
    if (weight <= 0.0001) continue
    weightSum += weight
    satSum += s * weight
    const rad = (h * Math.PI) / 180
    hcos += Math.cos(rad) * weight
    hsin += Math.sin(rad) * weight
  }
  let hue = 0
  let sat = 0
  if (weightSum > 0.0001) {
    hue = (Math.atan2(hsin, hcos) * 180) / Math.PI
    if (hue < 0) hue += 360
    sat = clamp01(satSum / weightSum)
  } else {
    /* 近灰度图：用整体平均色，饱和度为 0，得到中性灰调 */
    const avg = rgbToHsl(rSum / count, gSum / count, bSum / count)
    hue = avg.h
    sat = 0
  }
  const neutral = sat < 0.06
  const lightSat = neutral ? 0.02 : Math.min(0.52, Math.max(0.14, sat * 0.9))
  const darkSat = neutral ? 0.02 : Math.min(0.42, Math.max(0.1, sat * 0.75))
  const light = hslToHex(hue, lightSat, 0.82)
  const dark = hslToHex(hue, darkSat, 0.14)
  return { light, dark }
}

/** 校验 {light,dark} 是否为合法 palette。 */
export function isValidPalette(value) {
  if (!value || typeof value !== 'object') return false
  return /^#[0-9a-f]{6}$/i.test(String(value.light || '')) && /^#[0-9a-f]{6}$/i.test(String(value.dark || ''))
}

/** 用 ffmpeg 把 still 缩成 32x18 RGB 再算 palette；失败返回 null。 */
export function extractPalette(ffmpeg, imageFile) {
  if (!ffmpeg || !imageFile) return null
  let result
  try {
    result = spawnSync(
      ffmpeg,
      [
        '-v', 'error', '-nostdin', '-i', imageFile,
        '-vf', `scale=${PALETTE_W}:${PALETTE_H}:flags=area`,
        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'
      ],
      { timeout: 20000, windowsHide: true, maxBuffer: 2 * 1024 * 1024 }
    )
  } catch {
    return null
  }
  const expected = PALETTE_W * PALETTE_H * 3
  if (result.status !== 0 || !result.stdout || result.stdout.length < expected) return null
  return paletteFromPixels(result.stdout.subarray(0, expected))
}

/** 目录内所有顶层文件的 mtime 最大值（判断源是否更新）。 */
function itemSourceMtime(dir) {
  let mtime = 0
  let entries = []
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return 0
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    const stat = statSafe(full)
    if (stat && stat.mtimeMs > mtime) mtime = stat.mtimeMs
    if (!stat && entry.isDirectory()) {
      let sub = []
      try {
        sub = fs.readdirSync(full)
      } catch {
        continue
      }
      for (const name of sub) {
        const subStat = statSafe(path.join(full, name))
        if (subStat && subStat.mtimeMs > mtime) mtime = subStat.mtimeMs
      }
    }
  }
  return mtime
}

// ============================================================================
// 四、日志与构建状态
// ============================================================================

function createLogger(logFile, quiet) {
  const append = (line) => {
    try {
      fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${line}\n`)
    } catch {
      // 日志失败不影响构建
    }
  }
  return {
    info(message) {
      if (!quiet) console.log(message)
      append(message)
    },
    warn(message) {
      if (!quiet) console.warn(message)
      append('WARN ' + message)
    },
    error(message) {
      console.error(message)
      append('ERROR ' + message)
    }
  }
}

/** 启动前把超过 2MB 的 build.log 重建。 */
function rotateBuildLog(logFile) {
  const stat = statSafe(logFile)
  if (stat && stat.size > LOG_MAX_BYTES) {
    try {
      fs.rmSync(logFile, { force: true })
    } catch {
      // ignore
    }
  }
}

function createStatusWriter(file, logger) {
  const state = {
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
  let lastWrite = 0
  const write = (force) => {
    state.updatedAt = Date.now()
    try {
      writeJsonAtomic(file, state)
      lastWrite = Date.now()
    } catch (err) {
      logger.warn(`写 build-status.json 失败：${err && err.message}`)
    }
  }
  return {
    start(mode, total, message) {
      state.state = 'running'
      state.mode = mode
      state.startedAt = Date.now()
      state.updatedAt = state.startedAt
      state.finishedAt = 0
      state.done = 0
      state.total = total
      state.current = ''
      state.message = message
      state.errors = []
      write(true)
    },
    setCurrent(title) {
      state.current = title || ''
    },
    progress(done, message) {
      state.done = done
      if (message) state.message = message
      if (Date.now() - lastWrite >= 1000) write(false)
    },
    addError(id, message) {
      state.errors.push({ id: String(id), message: String(message) })
    },
    finish(finalState, message) {
      state.state = finalState
      state.finishedAt = Date.now()
      state.message = message
      state.current = ''
      write(true)
    }
  }
}

// ============================================================================
// 五、worker 侧：真正跑 ffmpeg / chrome 的地方
// ============================================================================

/**
 * 统一的同步子进程调用。ffmpeg/chrome 的 stderr 只留最后几行用于报错。
 */
function runProcess(exe, args, options = {}) {
  const timeout = options.timeout || 180000
  try {
    const result = spawnSync(exe, args, {
      timeout,
      windowsHide: true,
      encoding: 'utf8',
      maxBuffer: 8 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    const output = `${result.stdout || ''}${result.stderr || ''}`.trim()
    const tail = output.split(/\r?\n/).filter(Boolean).slice(-6).join(' | ')
    return {
      ok: result.status === 0 && !result.error,
      status: result.status,
      error: result.error ? result.error.message : null,
      tail
    }
  } catch (err) {
    return { ok: false, status: null, error: String(err && err.message || err), tail: '' }
  }
}

function ffmpegBase(ffmpeg, args) {
  return runProcess(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-nostdin', '-y', ...args])
}

function tmpSibling(file) {
  return `${file}.tmp-${process.pid}-${Math.random().toString(36).slice(2, 8)}.jpg`
}

/**
 * 用 ffmpeg 把图片缩到 8x8 raw RGB，统计亮度/彩度，用来识别“纯黑纯白纯色”的坏图。
 * 这一步是 QA 后加的：scene.pkg 里最大的横图可能是黑底遮罩或空帧。
 */
function analyzeImageStats(ffmpeg, file) {
  try {
    const result = spawnSync(
      ffmpeg,
      [
        '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-i', file,
        '-vf', 'scale=8:8,format=rgb24',
        '-frames:v', '1',
        '-f', 'rawvideo',
        'pipe:1'
      ],
      { timeout: 30000, windowsHide: true, maxBuffer: 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] }
    )
    if (!result || result.status !== 0 || !result.stdout || result.stdout.length < 8 * 8 * 3) return null
    const buf = result.stdout
    let sum = 0
    let square = 0
    let black = 0
    let white = 0
    let color = 0
    let count = 0
    for (let i = 0; i + 2 < buf.length; i += 3) {
      const r = buf[i]
      const g = buf[i + 1]
      const b = buf[i + 2]
      const y = 0.299 * r + 0.587 * g + 0.114 * b
      sum += y
      square += y * y
      if (y < 8) black++
      if (y > 247) white++
      color += Math.max(r, g, b) - Math.min(r, g, b)
      count++
    }
    if (!count) return null
    const mean = sum / count
    return {
      mean,
      std: Math.sqrt(Math.max(0, square / count - mean * mean)),
      blackFrac: black / count,
      whiteFrac: white / count,
      colorfulness: color / count
    }
  } catch {
    return null
  }
}

/** 坏图判定：几乎无亮度起伏且无彩度，或者 98% 以上像素是黑/白。 */
function isFlatStats(stats) {
  if (!stats) return false
  return (
    (stats.std < 8 && stats.colorfulness < 10) ||
    stats.blackFrac >= 0.98 ||
    stats.whiteFrac >= 0.98
  )
}

/** 生成完 still 后检查是否纯色；是则抛 code=flat，让主线程换候选或降级。 */
function assertStillUsable(ffmpeg, stillFile) {
  const stats = analyzeImageStats(ffmpeg, stillFile)
  if (!stats) return
  if (!isFlatStats(stats)) return
  const error = new Error(
    `图片接近纯色（mean=${stats.mean.toFixed(1)} std=${stats.std.toFixed(1)} ` +
    `black=${stats.blackFrac.toFixed(2)} white=${stats.whiteFrac.toFixed(2)}）`
  )
  error.code = 'flat'
  error.stats = stats
  throw error
}

/** still 落盘 + 生成 thumb 的公共收尾。 */
function finalizeStill(task, stillTmp) {
  assertStillUsable(task.ffmpeg, stillTmp)
  replaceFile(stillTmp, task.outStill)
  return produceThumbOnly(task)
}

/** 把任意图片缩裁成 16:9 still，并生成 thumb；失败抛错。 */
function produceStillFromImage(task) {
  fs.mkdirSync(path.dirname(task.outStill), { recursive: true })
  fs.mkdirSync(path.dirname(task.outThumb), { recursive: true })
  const stillTmp = tmpSibling(task.outStill)
  try {
    const still = ffmpegBase(task.ffmpeg, [
      '-i', task.input,
      '-vf', STILL_FILTER_FULL,
      '-frames:v', '1',
      '-q:v', '2',
      stillTmp
    ])
    if (!still.ok) throw new Error(`ffmpeg 缩放裁切失败：${still.tail || still.error || still.status}`)
    return finalizeStill(task, stillTmp)
  } finally {
    try {
      fs.rmSync(stillTmp, { force: true })
    } catch {
      // ignore
    }
  }
}

/** 视频抽帧：契约命令；对 <2s 的视频降级到 -ss 0 再试一次。 */
function produceStillFromVideo(task) {
  fs.mkdirSync(path.dirname(task.outStill), { recursive: true })
  const attempts = [
    ['-ss', '2', '-i', task.video, '-vf', `thumbnail=90,${STILL_FILTER_FULL}`],
    ['-ss', '0', '-i', task.video, '-vf', STILL_FILTER_FULL]
  ]
  let lastError = null
  for (const inputArgs of attempts) {
    const stillTmp = tmpSibling(task.outStill)
    try {
      const result = ffmpegBase(task.ffmpeg, [
        ...inputArgs,
        '-frames:v', '1',
        '-an', '-sn',
        '-q:v', '2',
        stillTmp
      ])
      if (!result.ok) {
        lastError = result.tail || result.error || `exit ${result.status}`
        continue
      }
      return finalizeStill(task, stillTmp)
    } catch (err) {
      if (err && err.code === 'flat') throw err
      lastError = err && err.message
    } finally {
      try {
        fs.rmSync(stillTmp, { force: true })
      } catch {
        // ignore
      }
    }
  }
  throw new Error(`ffmpeg 视频抽帧失败：${lastError || '未知原因'}`)
}

/** 视频/网页/合成路径的公共收尾：still 已存在，只补 thumb。 */
function produceThumbOnly(task) {
  fs.mkdirSync(path.dirname(task.outThumb), { recursive: true })
  const thumbTmp = tmpSibling(task.outThumb)
  try {
    const thumb = ffmpegBase(task.ffmpeg, [
      '-i', task.outStill,
      '-vf', `scale=${THUMB_WIDTH}:${THUMB_HEIGHT}`,
      '-frames:v', '1',
      '-q:v', '4',
      thumbTmp
    ])
    if (!thumb.ok) throw new Error(`ffmpeg 生成缩略图失败：${thumb.tail || thumb.error || thumb.status}`)
    replaceFile(thumbTmp, task.outThumb)
    const size = readJpegSize(task.outStill) || { w: 0, h: 0 }
    return { source: task.source, width: size.w, height: size.h }
  } finally {
    try {
      fs.rmSync(thumbTmp, { force: true })
    } catch {
      // ignore
    }
  }
}

/** Chrome headless 截网页，再缩裁成 still。 */
function produceStillFromWeb(task) {
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-cbg-chrome-'))
  const shot = path.join(profileDir, 'screenshot.png')
  try {
    const result = runProcess(
      task.chrome,
      [
        '--headless=new',
        '--disable-gpu',
        '--hide-scrollbars',
        '--allow-file-access-from-files',
        '--force-device-scale-factor=1',
        '--no-first-run',
        '--no-default-browser-check',
        '--window-size=1920,1080',
        '--virtual-time-budget=12000',
        `--user-data-dir=${profileDir}`,
        `--screenshot=${shot}`,
        pathToFileURL(task.html).href
      ],
      { timeout: CHROME_TIMEOUT_MS }
    )
    if (!result.ok) throw new Error(`Chrome 截图失败：${result.tail || result.error || result.status}`)
    const stat = statSafe(shot)
    if (!stat || stat.size < 1024) throw new Error('Chrome 截图产物不存在或为空')
    const imageTask = { ...task, input: shot, source: 'web' }
    return produceStillFromImage(imageTask)
  } finally {
    try {
      fs.rmSync(profileDir, { recursive: true, force: true })
    } catch {
      // ignore
    }
  }
}

/** preview-composite 兜底：方形/任意比例 preview 居中，两侧同图模糊铺满。 */
function produceComposite(task) {
  fs.mkdirSync(path.dirname(task.outStill), { recursive: true })
  const stillTmp = tmpSibling(task.outStill)
  try {
    const result = ffmpegBase(task.ffmpeg, [
      '-i', task.preview,
      '-filter_complex', COMPOSITE_FILTER,
      '-frames:v', '1',
      '-an', '-sn',
      '-q:v', '2',
      stillTmp
    ])
    if (!result.ok) throw new Error(`ffmpeg 合成预览图失败：${result.tail || result.error || result.status}`)
    replaceFile(stillTmp, task.outStill)
    return produceThumbOnly({ ...task, source: 'preview-composite' })
  } finally {
    try {
      fs.rmSync(stillTmp, { force: true })
    } catch {
      // ignore
    }
  }
}

/** worker 线程的任务入口。 */
async function runWorkerTask(task) {
  switch (task.kind) {
    case 'image':
      return produceStillFromImage(task)
    case 'video':
      return produceStillFromVideo(task)
    case 'web':
      return produceStillFromWeb(task)
    case 'composite':
      return produceComposite(task)
    default:
      throw new Error(`未知任务类型 ${task.kind}`)
  }
}

function cleanupWorkerTask(task) {
  if (task && task.staged && task.input) {
    try {
      fs.rmSync(task.input, { force: true })
    } catch {
      // ignore
    }
  }
}

// worker 线程：收任务 → 跑 → 回结果（结果里带 ok/error）。
if (!isMainThread) {
  parentPort.on('message', async (task) => {
    let result
    try {
      const detail = await runWorkerTask(task)
      result = { ok: true, ...detail }
    } catch (err) {
      result = { ok: false, code: err && err.code ? String(err.code) : null, error: String(err && err.message || err) }
    } finally {
      cleanupWorkerTask(task)
    }
    parentPort.postMessage(result)
  })
}

/**
 * worker_threads 版并发池：每个 worker 内部用 spawnSync 跑 ffmpeg，
 * 4 个线程就是真正的 4 路并发（单线程里 spawnSync 是阻塞的）。
 */
class WorkerPool {
  constructor(size, workerFile) {
    this.size = size
    this.workerFile = workerFile
    this.free = []
    this.pending = []
    this.closed = false
  }

  async start() {
    for (let i = 0; i < this.size; i++) this.free.push(this.spawnWorker())
  }

  spawnWorker() {
    const worker = new Worker(this.workerFile, { workerData: { __dshBuilderWorker: true } })
    worker.__task = null
    worker.__exited = false
    worker.on('message', (result) => {
      const job = worker.__task
      worker.__task = null
      this.free.push(worker)
      if (job) job.resolve(result)
      this.pump()
    })
    worker.on('error', (err) => {
      const job = worker.__task
      worker.__task = null
      worker.__exited = true
      this.replaceWorker(worker)
      if (job) job.resolve({ ok: false, error: `worker 崩溃：${err && err.message || err}` })
      this.pump()
    })
    worker.on('exit', () => {
      if (worker.__exited) return
      worker.__exited = true
      this.replaceWorker(worker)
      this.pump()
    })
    return worker
  }

  replaceWorker(dead) {
    this.free = this.free.filter((worker) => worker !== dead)
    if (this.closed) return
    try {
      this.free.push(this.spawnWorker())
    } catch {
      // 池缩容不影响已排队任务
    }
  }

  exec(task) {
    return new Promise((resolve) => {
      this.pending.push({ task, resolve })
      this.pump()
    })
  }

  pump() {
    while (!this.closed && this.pending.length && this.free.length) {
      const worker = this.free.pop()
      const job = this.pending.shift()
      worker.__task = job
      worker.postMessage(job.task)
    }
  }

  async close() {
    this.closed = true
    const workers = this.free.slice()
    this.free = []
    await Promise.all(workers.map((worker) => worker.terminate().catch(() => {})))
  }
}

// ============================================================================
// 六、主线程侧：元数据、任务准备、调度
// ============================================================================

/** 读一个壁纸目录的 project.json；损坏就当没有。 */
function readProjectJson(dir) {
  const file = path.join(dir, 'project.json')
  try {
    return parseProjectJsonText(fs.readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}

/** 读 workshopcache.json；结构可能是 {wallpapers:[...]} 或直接数组。 */
function loadWorkshopCache(weDir, logger) {
  const file = path.join(weDir, 'bin', 'workshopcache.json')
  const byId = new Map()
  const raw = readJsonFile(file)
  if (!raw) {
    logger.warn(`workshopcache.json 读取失败，改用 project.json 兜底：${file}`)
    return byId
  }
  const list = Array.isArray(raw) ? raw : Array.isArray(raw.wallpapers) ? raw.wallpapers : []
  for (const entry of list) {
    if (!entry) continue
    const id = String(entry.workshopid || entry.id || entry.publishedfileid || '')
    if (id) byId.set(id, entry)
  }
  return byId
}

/** 枚举工坊目录并合并出完整条目列表（内部字段 dir/cacheEntry/projectJson 不写进 library）。 */
function loadMetadata(state, logger) {
  const cacheById = loadWorkshopCache(state.weDir, logger)
  const config = readJsonFile(path.join(state.weDir, 'config.json'))
  const playlist = collectPlaylistIndex(config)
  const currentId = collectCurrentId(config)
  const folderMap = collectFolderMap(config)

  let dirs = []
  try {
    dirs = fs.readdirSync(state.workshopRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && /^\d+$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
  } catch (err) {
    throw new Error(`读工坊目录失败：${err && err.message}`)
  }

  const items = dirs.map((id) => {
    const dir = path.join(state.workshopRoot, id)
    const projectJson = readProjectJson(dir)
    const item = mergeItemMetadata({
      id,
      dir,
      cacheEntry: cacheById.get(id) || null,
      projectJson,
      playlistIndex: playlist.has(id) ? playlist.get(id) : null,
      current: currentId === id
    })
    item.folder = folderMap.get(id) || null
    item.projectJson = projectJson
    item.cacheEntry = cacheById.get(id) || null
    return item
  })

  const typeCounts = { scene: 0, video: 0, web: 0, other: 0 }
  for (const item of items) typeCounts[item.type] += 1

  return {
    items: sortLibraryItems(items),
    playlist,
    currentId,
    folderMap,
    cacheCount: cacheById.size,
    typeCounts
  }
}

/** 解析 preview 图：优先目录里的 preview.*，其次 project.json/cache 里的 preview 字段。 */
function resolvePreview(item, files) {
  const found = files.filter((name) => PREVIEW_RE.test(name))
  if (found.length) {
    const order = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    found.sort((a, b) => order.indexOf(path.extname(a).toLowerCase()) - order.indexOf(path.extname(b).toLowerCase()))
    const first = path.join(item.dir, found[0])
    if (statSafe(first)) return first
  }
  const raw = (item.projectJson && item.projectJson.preview) || (item.cacheEntry && item.cacheEntry.preview)
  if (typeof raw === 'string' && raw) {
    let candidate = null
    if (/^[a-z]+:\/\//i.test(raw)) {
      const marker = raw.indexOf('/__file/')
      if (marker >= 0) {
        try {
          candidate = decodeURIComponent(raw.slice(marker + '/__file/'.length))
        } catch {
          candidate = null
        }
      }
    } else {
      candidate = path.isAbsolute(raw) ? raw : path.join(item.dir, raw)
    }
    if (candidate && statSafe(candidate)) return candidate
  }
  return null
}

/** 解析视频源：project.json file → cache file → 目录里第一个视频。 */
function resolveVideo(item, files) {
  const candidates = []
  const push = (value) => {
    if (typeof value !== 'string' || !value) return
    if (!VIDEO_RE.test(value)) return
    const candidate = path.isAbsolute(value) ? value : path.join(item.dir, value)
    if (statSafe(candidate) && !candidates.includes(candidate)) candidates.push(candidate)
  }
  push(item.projectJson && item.projectJson.file)
  push(item.cacheEntry && item.cacheEntry.file)
  for (const name of files.filter((name) => VIDEO_RE.test(name)).sort((a, b) => a.localeCompare(b))) {
    const candidate = path.join(item.dir, name)
    if (!candidates.includes(candidate)) candidates.push(candidate)
  }
  return candidates[0] || null
}

/** 解析网页入口：project.json file → cache file → 根目录 index.html → 一层子目录兜底。 */
function resolveHtml(item, files) {
  const candidates = []
  const push = (value) => {
    if (typeof value !== 'string' || !value) return
    if (!HTML_RE.test(value)) return
    const candidate = path.isAbsolute(value) ? value : path.join(item.dir, value)
    if (statSafe(candidate) && !candidates.includes(candidate)) candidates.push(candidate)
  }
  push(item.projectJson && item.projectJson.file)
  push(item.cacheEntry && item.cacheEntry.file)

  const rootHtml = files.filter((name) => HTML_RE.test(name))
  const rootIndex = rootHtml.find((name) => /^index(\d+)?\.html?$/i.test(name))
  if (rootIndex) push(path.join(item.dir, rootIndex))
  else if (rootHtml.length) push(path.join(item.dir, rootHtml.sort()[0]))

  if (!candidates.length) {
    let entries = []
    try {
      entries = fs.readdirSync(item.dir, { withFileTypes: true })
    } catch {
      entries = []
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const sub = path.join(item.dir, entry.name)
      let subFiles = []
      try {
        subFiles = fs.readdirSync(sub).filter((name) => HTML_RE.test(name))
      } catch {
        continue
      }
      const index = subFiles.find((name) => /^index(\d+)?\.html?$/i.test(name)) || subFiles.sort()[0]
      if (index) {
        candidates.push(path.join(sub, index))
        break
      }
    }
  }
  return candidates[0] || null
}

/** 规划一条壁纸的源：scene / video / web / composite / none。 */
function planItem(item) {
  let files = []
  try {
    files = fs.readdirSync(item.dir)
  } catch {
    files = []
  }
  const previewPath = resolvePreview(item, files)

  if (item.type === 'scene') {
    const pkg = path.join(item.dir, 'scene.pkg')
    if (statSafe(pkg)) return { kind: 'scene', pkg, previewPath }
  }
  if (item.type === 'video') {
    const video = resolveVideo(item, files)
    if (video) return { kind: 'video', video, previewPath }
  }
  if (item.type === 'web') {
    const html = resolveHtml(item, files)
    if (html) return { kind: 'web', html, previewPath }
  }
  if (previewPath) return { kind: 'composite', preview: previewPath, previewPath }
  return { kind: 'none', previewPath }
}

/**
 * 为 scene 准备第 attempt 个候选内嵌图任务：
 * 每次重新读 pkg 并只写一小段候选图字节到 staging，避免把 100MB+ 的 pkg 常驻内存。
 */
function prepareSceneImageTask(item, plan, paths, context, attempt) {
  // 只读源文件；4GB 全量扫描约 4 秒，主线程串行做，避免 4 份 pkg 同时进内存。
  const buf = fs.readFileSync(plan.pkg)
  const ranked = rankEmbeddedImages(scanPkgImages(buf))
  if (!ranked.length || attempt >= ranked.length) return null
  const chosen = ranked[attempt]
  const ext = chosen.kind === 'png' ? 'png' : 'jpg'
  const staged = path.join(context.stagingDir, `${item.id}-${attempt}.${ext}`)
  fs.writeFileSync(staged, buf.subarray(chosen.off, chosen.end))
  return {
    ffmpeg: context.state.ffmpeg,
    outStill: paths.stillAbs,
    outThumb: paths.thumbAbs,
    kind: 'image',
    source: 'embedded',
    input: staged,
    staged: true
  }
}

/** 生成一条非 scene 壁纸的任务描述。 */
function prepareTask(item, plan, context) {
  const paths = context.paths
  const base = {
    ffmpeg: context.state.ffmpeg,
    outStill: paths.stillAbs,
    outThumb: paths.thumbAbs
  }

  if (plan.kind === 'video') {
    return { ...base, kind: 'video', source: 'video', video: plan.video }
  }

  if (plan.kind === 'web') {
    if (!context.state.chrome) {
      return plan.previewPath ? { ...base, kind: 'composite', preview: plan.previewPath } : null
    }
    return { ...base, kind: 'web', html: plan.html, chrome: context.state.chrome }
  }

  if (plan.kind === 'composite') {
    return { ...base, kind: 'composite', preview: plan.preview }
  }

  return null
}

/** preview-composite 任务。 */
function compositeTask(paths, plan, context) {
  return {
    kind: 'composite',
    ffmpeg: context.state.ffmpeg,
    preview: plan.previewPath,
    outStill: paths.stillAbs,
    outThumb: paths.thumbAbs
  }
}

/**
 * 处理一条壁纸。
 * scene 依次尝试排名靠前的内嵌图（最大图可能是黑屏遮罩/空帧）；
 * 所有主源失败后统一降级 preview-composite。
 */
async function processItem(item, context) {
  const paths = itemPaths(context.cacheRoot, item.id)
  const plan = planItem(item)
  if (plan.kind === 'none') throw new Error('没有可用源（无 scene.pkg / 视频 / 网页 / preview）')
  const prepared = { ...context, paths }

  if (plan.kind === 'scene') {
    const maxAttempts = 3
    let lastError = null
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const task = prepareSceneImageTask(item, plan, paths, prepared, attempt)
      if (!task) break
      const result = await context.pool.exec(task)
      if (result.ok) {
        return { source: result.source, width: result.width, height: result.height }
      }
      lastError = result.error
      context.logger.warn(`[${item.id}] scene 候选图 #${attempt + 1} 不可用：${lastError}`)
    }
    if (!plan.previewPath) throw new Error(`scene 没有可用内嵌图且没有 preview：${lastError || '无合法候选'}`)
    const fallback = await context.pool.exec(compositeTask(paths, plan, context))
    if (!fallback.ok) throw new Error(`scene 候选图与兜底都失败：${lastError} / ${fallback.error}`)
    return { source: 'preview-composite', width: fallback.width, height: fallback.height }
  }

  const task = prepareTask(item, plan, prepared)
  if (!task) throw new Error('源文件无法读取')

  const primary = await context.pool.exec(task)
  if (primary.ok) {
    return { source: primary.source, width: primary.width, height: primary.height }
  }

  context.logger.warn(`[${item.id}] ${task.kind} 生成失败，降级 preview-composite：${primary.error}`)
  if (!plan.previewPath) throw new Error(`主源失败且没有 preview：${primary.error}`)

  const fallback = await context.pool.exec(compositeTask(paths, plan, context))
  if (!fallback.ok) throw new Error(`主源失败且兜底失败：${primary.error} / ${fallback.error}`)
  return { source: 'preview-composite', width: fallback.width, height: fallback.height }
}

/** 并发调度：最多 CONCURRENCY 条同时在飞，一条完成立刻补下一条。 */
async function runQueue(queue, handler) {
  let next = 0
  let done = 0
  const active = new Set()
  await new Promise((resolve) => {
    const pump = () => {
      if (next >= queue.length && active.size === 0) {
        resolve()
        return
      }
      while (active.size < CONCURRENCY && next < queue.length) {
        const item = queue[next++]
        const promise = Promise.resolve()
          .then(() => handler(item))
          .catch(() => ({ error: true }))
          .finally(() => {
            active.delete(promise)
            done++
            pump()
          })
        active.add(promise)
      }
    }
    pump()
  })
  return done
}

// ============================================================================
// 七、主流程
// ============================================================================

function printUsage() {
  console.log(
    [
      '用法：node tools/build-library.mjs [选项]',
      '',
      '  --mode missing|force   missing（默认）只补缺；force 全部重做',
      '  --cache <dir>          缓存根目录（默认 DSH_HOME/dsh-chat-background/wallpapers）',
      '  --limit N              只处理前 N 条（调试）',
      '  --ids 1,2              只处理指定 id（调试）',
      '  --quiet                不往 stdout 打日志（build.log 照写）',
      '  --help                 显示帮助'
    ].join('\n')
  )
}

/** 失败收尾：写 build-status.json 的 error 状态。 */
function failBuild(context, message) {
  try {
    writeJsonAtomic(context.statusFile, {
      state: 'error',
      mode: context.args.mode,
      startedAt: context.startedAt,
      updatedAt: Date.now(),
      finishedAt: Date.now(),
      done: 0,
      total: 0,
      current: '',
      message,
      errors: []
    })
  } catch {
    // ignore
  }
  context.logger.error(message)
  return 1
}

/** 判断旧缓存能否直接复用（missing 模式跳过条件）。 */
function cacheState(cacheRoot, id) {
  const paths = itemPaths(cacheRoot, id)
  const still = statSafe(paths.stillAbs)
  const thumb = statSafe(paths.thumbAbs)
  if (!still || !thumb || still.size <= 0 || thumb.size <= 0) return { reusable: false }
  return { reusable: true, stillMtime: still.mtimeMs }
}

/** 新库与旧库（忽略 generatedAt）是否完全一致，一致就不重写，保证 missing 二次运行幂等。 */
function sameLibrary(a, b) {
  if (!a || !b) return false
  try {
    const normalize = (lib) => JSON.stringify({ ...lib, generatedAt: 0 })
    return normalize(a) === normalize(b)
  } catch {
    return false
  }
}

async function main() {
  let args
  try {
    args = parseArgs(process.argv.slice(2))
  } catch (err) {
    console.error(`参数错误：${err && err.message}`)
    printUsage()
    return 2
  }
  if (args.help) {
    printUsage()
    return 0
  }

  const startedAt = Date.now()
  const cacheRoot = args.cache || defaultCacheRoot()
  const stillsDir = path.join(cacheRoot, 'stills')
  const thumbsDir = path.join(cacheRoot, 'thumbs')
  const libraryFile = path.join(cacheRoot, 'library.json')
  const statusFile = path.join(cacheRoot, 'build-status.json')
  const stateFile = path.join(cacheRoot, 'state.json')
  const logFile = path.join(cacheRoot, 'build.log')

  fs.mkdirSync(stillsDir, { recursive: true })
  fs.mkdirSync(thumbsDir, { recursive: true })
  rotateBuildLog(logFile)
  const logger = createLogger(logFile, args.quiet)
  const status = createStatusWriter(statusFile, logger)

  logger.info(`=== dsh-chat-background Builder ${new Date().toISOString()} ===`)
  logger.info(`模式=${args.mode} 缓存=${cacheRoot}`)
  status.start(args.mode, 0, '正在探测环境…')

  // ---- 环境探测 ----
  const state = {
    ffmpeg: detectFfmpeg(process.env),
    chrome: detectChrome(process.env),
    weDir: null,
    workshopRoot: null,
    detectedAt: Date.now()
  }
  try {
    const we = detectWe(process.env)
    state.weDir = we.weDir
    state.workshopRoot = we.workshopRoot
  } catch (err) {
    logger.warn(`探测 Wallpaper Engine 失败：${err && err.message}`)
  }
  try {
    writeJsonAtomic(stateFile, state)
  } catch (err) {
    logger.warn(`写 state.json 失败：${err && err.message}`)
  }

  const context = { args, cacheRoot, statusFile, logger, state, startedAt }
  logger.info(`ffmpeg=${state.ffmpeg || '未找到'}`)
  logger.info(`chrome=${state.chrome || '未找到（web 壁纸将走 preview-composite）'}`)
  logger.info(`weDir=${state.weDir || '未找到'}`)
  logger.info(`workshopRoot=${state.workshopRoot || '未找到'}`)

  if (!state.weDir) return failBuild(context, '找不到 Wallpaper Engine 安装目录，请设置 DSH_WE_DIR 环境变量')
  if (!state.workshopRoot) return failBuild(context, '找不到 Steam 创意工坊目录 431960，请设置 DSH_WE_WORKSHOP 环境变量')
  if (!state.ffmpeg) {
    return failBuild(context, '找不到 ffmpeg，请安装 ffmpeg 或设置 DSH_CHAT_BG_FFMPEG 环境变量')
  }

  // ---- 元数据 ----
  let meta
  try {
    meta = loadMetadata(state, logger)
  } catch (err) {
    return failBuild(context, String(err && err.message || err))
  }
  logger.info(
    `工坊目录 ${meta.items.length} 条（workshopcache ${meta.cacheCount} 条）；` +
    `scene=${meta.typeCounts.scene} video=${meta.typeCounts.video} web=${meta.typeCounts.web} other=${meta.typeCounts.other}`
  )

  // ---- 可见性过滤：只看播放列表 / 隐藏指定 WE 文件夹 ----
  // 配置在 <cacheRoot>/visibility.json；缺省不过滤。
  const visibility = readVisibility(cacheRoot)
  const totalBeforeFilter = meta.items.length
  meta.items = filterVisibleItems(meta.items, visibility)
  const visibleTypeCounts = { scene: 0, video: 0, web: 0, other: 0 }
  for (const item of meta.items) visibleTypeCounts[item.type] += 1
  meta.typeCounts = visibleTypeCounts
  logger.info(
    `可见性：playlistOnly=${visibility.playlistOnly} hiddenFolders=${JSON.stringify(visibility.hiddenFolders)}；` +
    `保留 ${meta.items.length}/${totalBeforeFilter} 条` +
    `（scene=${visibleTypeCounts.scene} video=${visibleTypeCounts.video} web=${visibleTypeCounts.web} other=${visibleTypeCounts.other}）`
  )

  // ---- 旧库（用于复用 source / 判断幂等） ----
  const prevLibrary = readJsonFile(libraryFile)
  const prevById = new Map()
  if (prevLibrary && Array.isArray(prevLibrary.items)) {
    for (const entry of prevLibrary.items) if (entry && entry.id) prevById.set(String(entry.id), entry)
  }

  // ---- 组队列（missing 模式跳过已是最新的条目） ----
  const idFilter = args.ids ? new Set(args.ids.map(String)) : null
  const queue = []
  let skipped = 0
  for (const item of meta.items) {
    if (idFilter && !idFilter.has(item.id)) continue
    if (args.mode === 'missing') {
      const cache = cacheState(cacheRoot, item.id)
      if (cache.reusable) {
        const sourceMtime = itemSourceMtime(item.dir)
        if (cache.stillMtime >= sourceMtime) {
          skipped++
          continue
        }
      }
    }
    queue.push(item)
  }
  const workQueue = args.limit != null ? queue.slice(0, args.limit) : queue
  logger.info(`待处理 ${workQueue.length} 条（跳过 ${skipped} 条，mode=${args.mode}）`)

  status.start(args.mode, workQueue.length, `正在生成静态封面 0/${workQueue.length}`)

  // ---- 构建 ----
  const stagingDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-cbg-build-'))
  const pool = new WorkerPool(Math.min(CONCURRENCY, Math.max(1, workQueue.length)), BUILDER_FILE)
  const results = new Map()
  let processed = 0
  let failed = 0
  const errors = []

  try {
    await pool.start()
    await runQueue(workQueue, async (item) => {
      status.setCurrent(item.title)
      let result
      try {
        result = await processItem(item, { ...context, pool, stagingDir })
      } catch (err) {
        result = { error: String(err && err.message || err) }
      }
      processed++
      if (result.error) {
        failed++
        errors.push({ id: item.id, message: result.error })
        status.addError(item.id, result.error)
        logger.warn(`[${processed}/${workQueue.length}] ${item.id} 失败：${result.error}`)
      } else {
        results.set(item.id, result)
        logger.info(`[${processed}/${workQueue.length}] ${item.id} ${result.source} ${result.width}x${result.height} ${item.title}`)
      }
      status.progress(processed, `正在生成静态封面 ${processed}/${workQueue.length}`)
    })
  } finally {
    await pool.close()
    try {
      fs.rmSync(stagingDir, { recursive: true, force: true })
    } catch {
      // ignore
    }
  }

  // ---- 汇总 library（无论本次处理了哪些，缓存里所有已生成的条目都要写进完整清单） ----
  const libraryItems = []
  let paletteComputed = 0
  for (const item of meta.items) {
    const paths = itemPaths(cacheRoot, item.id)
    const still = statSafe(paths.stillAbs)
    const thumb = statSafe(paths.thumbAbs)
    if (!still || !thumb || still.size <= 0 || thumb.size <= 0) continue
    const built = results.get(item.id)
    const prevEntry = prevById.get(item.id)
    const dims = readJpegSize(paths.stillAbs) || { w: 0, h: 0 }
    let source = (built && built.source) || (prevEntry && prevEntry.source) || defaultSourceForType(item.type)
    if (!SOURCES.includes(source)) source = defaultSourceForType(item.type)
    /* 底色取色：优先复用旧清单里的值，缺失时用 ffmpeg 现算一次（换图/新增才有开销）。 */
    let palette = isValidPalette(prevEntry && prevEntry.palette)
      ? { light: String(prevEntry.palette.light).toLowerCase(), dark: String(prevEntry.palette.dark).toLowerCase() }
      : null
    if (!palette) {
      palette = extractPalette(state.ffmpeg, paths.stillAbs)
      if (palette) paletteComputed++
    }
    libraryItems.push({
      id: item.id,
      title: item.title,
      type: item.type,
      folder: item.folder || null,
      playlistIndex: item.playlistIndex,
      current: item.current,
      tags: item.tags,
      filesize: item.filesize,
      subscriptiondate: item.subscriptiondate,
      width: dims.w,
      height: dims.h,
      bytes: still.size,
      source,
      palette,
      still: paths.stillRel,
      thumb: paths.thumbRel
    })
  }
  if (paletteComputed > 0) logger.info(`壁纸取色：本次新算 ${paletteComputed} 条，其余复用旧清单`)
  const sortedLibraryItems = sortLibraryItems(libraryItems)
  const counts = {
    total: meta.items.length,
    scene: meta.typeCounts.scene,
    video: meta.typeCounts.video,
    web: meta.typeCounts.web,
    other: meta.typeCounts.other,
    built: sortedLibraryItems.length
  }
  const library = {
    schema: SCHEMA,
    generatedAt: prevLibrary && prevLibrary.generatedAt ? prevLibrary.generatedAt : Date.now(),
    weDir: toPosixPath(state.weDir),
    workshopRoot: toPosixPath(state.workshopRoot),
    counts,
    items: sortedLibraryItems
  }

  let libraryWritten = false
  if (!sameLibrary(prevLibrary, library)) {
    library.generatedAt = Date.now()
    writeJsonAtomic(libraryFile, library)
    libraryWritten = true
  }

  const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1)
  const message =
    `完成：可用 ${counts.built}/${counts.total} 张，本次新建 ${results.size} 张，` +
    `跳过 ${skipped} 张，失败 ${failed} 张（耗时 ${elapsed}s）`
  logger.info(message)
  logger.info(`library.json ${libraryWritten ? '已更新' : '无变化（跳过写入）'}：${libraryFile}`)
  if (errors.length) {
    for (const error of errors) logger.warn(`失败条目 ${error.id}：${error.message}`)
  }
  status.finish('done', message)
  return 0
}

// 只有被直接当作脚本执行时才跑 main；被测试 import 或作为 worker 加载时不跑。
// 注意：profile 里的插件目录是符号链接（node_modules/dsh-chat-background → 工作区），
// Node 加载模块时 import.meta.url 会解析成真实路径，而 process.argv[1] 仍是链接路径。
// 直接比较字符串会让 --cache 由 Host spawn 时静默不跑，所以这里两边都 realpath 后再比。
function realpathSafe(file) {
  try {
    return fs.realpathSync.native(file)
  } catch {
    return String(file)
  }
}

function sameFile(left, right) {
  const a = realpathSafe(left)
  const b = realpathSafe(right)
  return process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b
}

const isDirectRun =
  isMainThread &&
  !!process.argv[1] &&
  sameFile(process.argv[1], BUILDER_FILE) &&
  !(workerData && workerData.__dshBuilderWorker)

if (isDirectRun) {
  main()
    .then((code) => {
      if (typeof code === 'number') process.exitCode = code
    })
    .catch((err) => {
      console.error(`Builder 未捕获异常：${err && err.stack || err}`)
      process.exitCode = 1
    })
}
