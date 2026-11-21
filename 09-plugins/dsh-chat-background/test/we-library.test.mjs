/* ============================================================================
 * dsh-chat-background — Builder 单元测试
 * ----------------------------------------------------------------------------
 * 直接运行：node test/we-library.test.mjs
 *   - 纯函数：scene.pkg 图片扫描/选择、元数据合并与排序、路径处理、CLI 解析、JPEG 头解析；
 *   - 小端到端：真实 ffmpeg + Wallpaper Engine 环境跑 `--limit 3 --cache <临时目录>`，
 *     环境不全时 skip 并打印原因（不判失败）。
 * ========================================================================== */

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  COMPOSITE_FILTER,
  SCHEMA,
  SOURCES,
  STILL_FILTER,
  collectCurrentId,
  collectFolderMap,
  collectPlaylistIndex,
  defaultCacheRoot,
  detectFfmpeg,
  detectWe,
  filterVisibleItems,
  idFromWorkshopPath,
  isHiddenFolder,
  isValidImageSize,
  itemPaths,
  mergeItemMetadata,
  normalizeTags,
  normalizeType,
  paletteFromPixels,
  isValidPalette,
  parseArgs,
  parseJpegSize,
  parseProjectJsonText,
  rankEmbeddedImages,
  readVisibility,
  rgbToHsl,
  hslToHex,
  scanPkgImages,
  selectEmbeddedImage,
  sortLibraryItems,
  stripBom,
  toPosixPath
} from '../tools/build-library.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const BUILDER = path.resolve(HERE, '..', 'tools', 'build-library.mjs')

// ---------------------------------------------------------------------------
// 合成 PNG/JPEG 夹具：只要求结构能被扫描器解析，不需要真能解码
// ---------------------------------------------------------------------------

const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function pngChunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  return Buffer.concat([length, Buffer.from(type, 'latin1'), data, Buffer.alloc(4)])
}

/** 宽度/高度/颜色类型可控的合法 PNG 结构（IDAT 用占位字节）。 */
function makePng(w, h, colorType = 6, payload = 64) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr[8] = 8
  ihdr[9] = colorType
  return Buffer.concat([
    PNG_SIG,
    pngChunk('IHDR', ihdr),
    payload > 0 ? pngChunk('IDAT', Buffer.alloc(payload)) : Buffer.alloc(0),
    pngChunk('IEND', Buffer.alloc(0))
  ])
}

/** 合法 JPEG marker 结构（SOI + APP0 + SOF0 + SOS + 数据 + EOI）。 */
function makeJpeg(w, h, payload = 128) {
  const app0 = Buffer.from([
    0xff, 0xe0, 0x00, 0x10,
    0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00
  ])
  const sofBody = Buffer.alloc(15)
  sofBody[0] = 8
  sofBody.writeUInt16BE(h, 1)
  sofBody.writeUInt16BE(w, 3)
  sofBody[5] = 3
  sofBody.set([1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1], 6)
  const sof = Buffer.concat([Buffer.from([0xff, 0xc0, 0x00, 0x11]), sofBody])
  const sos = Buffer.from([0xff, 0xda, 0x00, 0x0c, 0x03, 0x01, 0x00, 0x02, 0x11, 0x03, 0x11, 0x00, 0x3f, 0x00])
  return Buffer.concat([
    Buffer.from([0xff, 0xd8]),
    app0,
    sof,
    sos,
    Buffer.alloc(payload),
    Buffer.from([0xff, 0xd9])
  ])
}

// ---------------------------------------------------------------------------
// 纯函数测试
// ---------------------------------------------------------------------------

test('toPosixPath / itemPaths：路径始终输出 POSIX 相对路径', () => {
  assert.equal(toPosixPath('a\\b\\c.jpg'), 'a/b/c.jpg')
  assert.equal(toPosixPath('a/b'), 'a/b')
  assert.equal(toPosixPath(null), '')

  const cache = path.join('tmp', 'cache')
  const paths = itemPaths(cache, '123456')
  assert.equal(paths.stillRel, 'stills/123456.jpg')
  assert.equal(paths.thumbRel, 'thumbs/123456.jpg')
  assert.equal(paths.stillRel.includes('\\'), false)
  assert.equal(paths.stillAbs, path.join(cache, 'stills', '123456.jpg'))
  assert.equal(paths.thumbAbs, path.join(cache, 'thumbs', '123456.jpg'))
})

test('isValidImageSize：契约约束（尺寸上限 / 最小面积 / 宽高比）', () => {
  assert.equal(isValidImageSize(3840, 2160), true)
  assert.equal(isValidImageSize(1280, 720), true)
  assert.equal(isValidImageSize(1279, 720), false)
  assert.equal(isValidImageSize(1280, 719), false)
  assert.equal(isValidImageSize(0, 720), false)
  assert.equal(isValidImageSize(8193, 2160), false)
  assert.equal(isValidImageSize(2160, 8193), false)
  assert.equal(isValidImageSize(10000, 100), false)
  assert.equal(isValidImageSize(1000, 4000), false) // 比 0.25 < 0.3
  assert.equal(isValidImageSize(4000, 1000), true) // 比 4.0 刚好允许
  assert.equal(isValidImageSize(4001, 1000), false)
})

test('scanPkgImages：整文件扫描 PNG/JPEG 签名并解析尺寸', () => {
  const png = makePng(3840, 2160, 6)
  const jpg = makeJpeg(1920, 1080)
  const tinyPng = makePng(320, 180, 2)
  const garbage = Buffer.from([0xff, 0xd8, 0xff, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03])
  const buffer = Buffer.concat([Buffer.from('PKGV0024-header'), png, Buffer.from('junk'), jpg, garbage, tinyPng])

  const images = scanPkgImages(buffer)
  const sizes = images.map((img) => `${img.kind}:${img.w}x${img.h}`)
  assert.deepEqual(sizes, ['png:3840x2160', 'jpg:1920x1080', 'png:320x180'])
  assert.equal(images[0].colorType, 6)
  // 段偏移可用于从原文件里 carve
  assert.deepEqual(buffer.subarray(images[0].off, images[0].off + 8), PNG_SIG)
  assert.deepEqual(buffer.subarray(images[1].off, images[1].off + 3), Buffer.from([0xff, 0xd8, 0xff]))
})

test('scanPkgImages：损坏/不完整签名不会产生候选', () => {
  const halfPng = Buffer.concat([PNG_SIG, Buffer.alloc(20)])
  const fakeJpeg = Buffer.from([0xff, 0xd8, 0xff, 0x12, 0x34, 0x56, 0x78])
  assert.deepEqual(scanPkgImages(Buffer.concat([halfPng, fakeJpeg])), [])
  assert.deepEqual(scanPkgImages(Buffer.alloc(0)), [])
  assert.deepEqual(scanPkgImages(null), [])
})

test('selectEmbeddedImage / rankEmbeddedImages：面积优先、横图优先、彩色优先、竖图返回 null', () => {
  const big = makePng(3840, 2160, 6)
  const mid = makeJpeg(2560, 1440)
  const small = makePng(1280, 720, 2)
  const portrait = makePng(1080, 1920, 6)
  const gray = makePng(4000, 2250, 0)
  const candidates = scanPkgImages(Buffer.concat([small, mid, portrait, gray, big]))

  const ranked = rankEmbeddedImages(candidates)
  assert.equal(ranked[0].w, 3840) // 面积最大的横图
  assert.ok(ranked.length >= 4)
  const chosen = selectEmbeddedImage(candidates)
  assert.equal(chosen.w, 3840)
  assert.equal(chosen.kind, 'png')

  // 只有竖图 → null（交给 preview-composite）
  const onlyPortrait = scanPkgImages(makePng(1080, 1920, 6))
  assert.deepEqual(rankEmbeddedImages(onlyPortrait), [])
  assert.equal(selectEmbeddedImage(onlyPortrait), null)

  // 彩色图优先于同档灰度图（灰度 PNG 常见是遮罩）
  const grayBig = makePng(3840, 2160, 0)
  const colorSmall = makePng(1920, 1080, 2)
  const mixed = scanPkgImages(Buffer.concat([grayBig, colorSmall]))
  const picked = selectEmbeddedImage(mixed)
  assert.equal(picked.colorType, 2)
  assert.equal(picked.w, 1920)
})

test('scanPkgImages：只有合法尺寸的图进入排名（超大 / 超小被过滤）', () => {
  const huge = makeJpeg(41627, 49068)
  const tooSmall = makeJpeg(1200, 600)
  const good = makeJpeg(1920, 1080)
  const candidates = scanPkgImages(Buffer.concat([huge, tooSmall, good]))
  assert.equal(candidates.length, 3)
  assert.equal(selectEmbeddedImage(candidates).w, 1920)
})

test('stripBom / parseProjectJsonText：BOM 与尾逗号容错', () => {
  assert.equal(stripBom('\uFEFF{"a":1}'), '{"a":1}')
  const parsed = parseProjectJsonText('\uFEFF{\n  "type": "Video",\n  "tags": ["Anime",],\n}')
  assert.equal(parsed.type, 'Video')
  assert.deepEqual(parsed.tags, ['Anime'])
  assert.throws(() => parseProjectJsonText('{ 完全不是 JSON'), /JSON/)
})

test('normalizeType / normalizeTags：type 白名单与 tag 清洗', () => {
  assert.equal(normalizeType('Video'), 'video')
  assert.equal(normalizeType('Scene'), 'scene')
  assert.equal(normalizeType('Web'), 'web')
  assert.equal(normalizeType('Application'), 'other')
  assert.equal(normalizeType(undefined), 'other')
  assert.deepEqual(normalizeTags(['Anime', 'Anime', '  ', 3]), ['Anime', '3'])
  assert.deepEqual(normalizeTags(null), [])
})

test('mergeItemMetadata：project.json 优先、cache 补字段、id 兜底标题', () => {
  const item = mergeItemMetadata({
    id: '1197607981',
    dir: 'D:/ws/1197607981',
    cacheEntry: {
      title: 'cache 标题',
      type: 'Scene',
      tags: ['Abstract'],
      filesize: 21453743,
      subscriptiondate: 1734943775
    },
    projectJson: { title: 'project 标题', type: 'scene', tags: ['Anime'] },
    playlistIndex: 7,
    current: true
  })
  assert.equal(item.id, '1197607981')
  assert.equal(item.title, 'project 标题')
  assert.equal(item.type, 'scene')
  assert.deepEqual(item.tags, ['Anime'])
  assert.equal(item.filesize, 21453743)
  assert.equal(item.subscriptiondate, 1734943775)
  assert.equal(item.playlistIndex, 7)
  assert.equal(item.current, true)
  assert.equal(item.dir, 'D:/ws/1197607981')

  const fallback = mergeItemMetadata({ id: '42', cacheEntry: { type: 'Web' } })
  assert.equal(fallback.title, '壁纸 42')
  assert.equal(fallback.type, 'web')
  assert.equal(fallback.playlistIndex, null)
  assert.equal(fallback.filesize, 0)
  assert.deepEqual(fallback.tags, [])

  const unknown = mergeItemMetadata({ id: '43', cacheEntry: { type: 'Application' } })
  assert.equal(unknown.type, 'other')
})

test('sortLibraryItems：播放列表顺序优先，其余按标题中文排序在后', () => {
  const noPlaylistA = { id: 'a', title: 'A 标题', playlistIndex: null }
  const noPlaylistB = { id: 'b', title: 'B 标题', playlistIndex: null }
  const items = [
    { id: '3', title: 'three', playlistIndex: 3 },
    noPlaylistB,
    { id: '1', title: 'one', playlistIndex: 1 },
    noPlaylistA,
    { id: '2', title: 'two', playlistIndex: 2 }
  ]
  const sorted = sortLibraryItems(items)
  assert.deepEqual(sorted.filter((item) => item.playlistIndex != null).map((item) => item.id), ['1', '2', '3'])
  const tail = sorted.slice(3).map((item) => item.title)
  const expectedTail = ['A 标题', 'B 标题'].sort((a, b) => a.localeCompare(b, 'zh'))
  assert.deepEqual(tail, expectedTail)
})

test('idFromWorkshopPath / 播放列表 / 当前壁纸解析', () => {
  assert.equal(
    idFromWorkshopPath('D:/SteamLibrary/steamapps/workshop/content/431960/1197607981/scene.pkg'),
    '1197607981'
  )
  assert.equal(
    idFromWorkshopPath('D:\\SteamLibrary\\steamapps\\workshop\\content\\431960\\2993876913\\red.mp4'),
    '2993876913'
  )
  assert.equal(idFromWorkshopPath('D:/SomeOther/123/scene.pkg'), null)
  assert.equal(idFromWorkshopPath(null), null)

  const config = {
    Administrator: {
      general: {
        wallpaperconfig: {
          selectedwallpapers: {
            Monitor0: {
              file: 'D:/SteamLibrary/steamapps/workshop/content/431960/3795054330/scene.pkg',
              playlist: {
                items: [
                  'D:/SteamLibrary/steamapps/workshop/content/431960/2993876913/scene.pkg',
                  'D:/SteamLibrary/steamapps/workshop/content/431960/3024446328/red.mp4',
                  'D:/SteamLibrary/steamapps/workshop/content/431960/2993876913/scene.pkg'
                ]
              }
            }
          }
        }
      }
    }
  }
  const playlist = collectPlaylistIndex(config)
  assert.equal(playlist.get('2993876913'), 1)
  assert.equal(playlist.get('3024446328'), 2)
  assert.equal(playlist.size, 2)
  assert.equal(collectCurrentId(config), '3795054330')
  assert.deepEqual([...collectPlaylistIndex(null)], [])
  assert.equal(collectCurrentId({}), null)
})

test('parseArgs：默认值、完整参数、非法参数', () => {
  assert.deepEqual(parseArgs([]), { mode: 'missing', cache: null, limit: null, ids: null, quiet: false, help: false })
  const args = parseArgs(['--mode', 'force', '--cache', 'C:/tmp/x', '--limit', '3', '--ids', '1, 2, abc', '--quiet'])
  assert.equal(args.mode, 'force')
  assert.equal(args.cache, path.resolve('C:/tmp/x'))
  assert.equal(args.limit, 3)
  assert.deepEqual(args.ids, ['1', '2'])
  assert.equal(args.quiet, true)
  assert.throws(() => parseArgs(['--mode', 'nah']), /missing 或 force/)
  assert.throws(() => parseArgs(['--unknown']), /未知参数/)
  assert.throws(() => parseArgs(['--limit', 'x']), /非负整数/)
  assert.throws(() => parseArgs(['--ids']), /缺少参数/)
})

test('parseJpegSize：从 SOF0 解析宽高，坏数据返回 null', () => {
  assert.deepEqual(parseJpegSize(makeJpeg(1920, 1080)), { w: 1920, h: 1080 })
  assert.deepEqual(parseJpegSize(makeJpeg(480, 270)), { w: 480, h: 270 })
  assert.equal(parseJpegSize(Buffer.from('not a jpeg')), null)
  assert.equal(parseJpegSize(Buffer.alloc(2)), null)
  assert.equal(parseJpegSize(null), null)
})

test('defaultCacheRoot：env 覆盖优先级', () => {
  assert.equal(
    defaultCacheRoot({ DSH_CHAT_BG_CACHE: 'C:/custom/cache' }),
    path.resolve('C:/custom/cache')
  )
  const withHome = defaultCacheRoot({ DSH_HOME: 'C:/fake/home' })
  assert.equal(withHome, path.join(path.resolve('C:/fake/home'), 'dsh-chat-background', 'wallpapers'))
})

test('过滤器常量符合契约（16:9 裁切 + preview 合成）', () => {
  assert.ok(STILL_FILTER.includes('3840'))
  assert.ok(STILL_FILTER.includes('crop'))
  assert.ok(STILL_FILTER.includes('16/9'))
  assert.ok(COMPOSITE_FILTER.includes('split=2'))
  assert.ok(COMPOSITE_FILTER.includes('overlay=(W-w)/2:(H-h)/2'))
  // 本机 ffmpeg（剪映自带）没有 boxblur 滤镜，必须用 gblur，避免线上构建全挂
  assert.ok(COMPOSITE_FILTER.includes('gblur'))
  assert.ok(!COMPOSITE_FILTER.includes('boxblur'))
})

// ---------------------------------------------------------------------------
// 小端到端：真实 ffmpeg + WE 环境，不可用时 skip
// ---------------------------------------------------------------------------

function runBuilder(args) {
  return spawnSync(process.execPath, [BUILDER, ...args], {
    encoding: 'utf8',
    timeout: 300000,
    windowsHide: true,
    env: { ...process.env }
  })
}

test('端到端：--limit 3 生成缓存，再次 --mode missing 幂等', (t) => {
  const ffmpeg = detectFfmpeg(process.env)
  const we = detectWe(process.env)
  if (!ffmpeg || !we.weDir || !we.workshopRoot) {
    t.skip(`环境缺少 ffmpeg 或 Wallpaper Engine，跳过端到端：ffmpeg=${ffmpeg || '无'} weDir=${we.weDir || '无'} workshopRoot=${we.workshopRoot || '无'}`)
    return
  }

  const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-cbg-e2e-'))
  try {
    const first = runBuilder(['--mode', 'missing', '--cache', cacheDir, '--limit', '3', '--quiet'])
    assert.equal(first.status, 0, `builder 退出码 ${first.status}：${first.stderr}`)

    const libraryFile = path.join(cacheDir, 'library.json')
    assert.ok(fs.existsSync(libraryFile), '缺少 library.json')
    const library = JSON.parse(fs.readFileSync(libraryFile, 'utf8'))
    assert.equal(library.schema, SCHEMA)
    assert.equal(typeof library.generatedAt, 'number')
    assert.ok(library.counts.total >= 300, `total 异常：${library.counts.total}`)
    assert.equal(library.counts.built, library.items.length)
    assert.ok(library.items.length >= 1 && library.items.length <= 3)
    assert.ok(fs.existsSync(path.join(cacheDir, 'state.json')))
    assert.ok(fs.existsSync(path.join(cacheDir, 'build-status.json')))

    const state = JSON.parse(fs.readFileSync(path.join(cacheDir, 'state.json'), 'utf8'))
    assert.equal(state.ffmpeg, ffmpeg)
    assert.ok(state.detectedAt > 0)

    for (const item of library.items) {
      assert.match(item.id, /^\d+$/)
      assert.ok(['scene', 'video', 'web', 'other'].includes(item.type), `非法 type ${item.type}`)
      assert.ok(SOURCES.includes(item.source), `非法 source ${item.source}`)
      assert.ok(item.width > 0 && item.height > 0, '缺少 width/height')
      assert.ok(Math.abs(item.width / item.height - 16 / 9) < 0.02, `still 不是 16:9：${item.width}x${item.height}`)
      assert.match(item.still, /^stills\/\d+\.jpg$/)
      assert.match(item.thumb, /^thumbs\/\d+\.jpg$/)
      assert.ok(isValidPalette(item.palette), `缺少合法的 palette：${item.id}`)

      const stillAbs = path.join(cacheDir, item.still)
      const thumbAbs = path.join(cacheDir, item.thumb)
      const stillStat = fs.statSync(stillAbs)
      assert.ok(stillStat.size > 1000, 'still 太小')
      assert.equal(stillStat.size, item.bytes)

      const dims = parseJpegSize(fs.readFileSync(stillAbs).subarray(0, 65536))
      assert.deepEqual(dims, { w: item.width, h: item.height })
      assert.ok(Math.max(dims.w, dims.h) <= 3840)

      const thumbDims = parseJpegSize(fs.readFileSync(thumbAbs).subarray(0, 65536))
      assert.deepEqual(thumbDims, { w: 480, h: 270 })
    }

    const status = JSON.parse(fs.readFileSync(path.join(cacheDir, 'build-status.json'), 'utf8'))
    assert.equal(status.state, 'done')
    assert.equal(status.mode, 'missing')
    assert.deepEqual(status.errors, [])

    // 第二次 missing（只看这 3 个 id）：应全部跳过，且不改动已生成的 library/still/thumb
    const builtIds = library.items.map((item) => item.id).join(',')
    const firstItem = library.items[0]
    const before = {
      library: fs.statSync(libraryFile).mtimeMs,
      still: fs.statSync(path.join(cacheDir, firstItem.still)).mtimeMs,
      thumb: fs.statSync(path.join(cacheDir, firstItem.thumb)).mtimeMs
    }
    const second = runBuilder(['--mode', 'missing', '--cache', cacheDir, '--ids', builtIds, '--quiet'])
    assert.equal(second.status, 0, `二次运行退出码 ${second.status}：${second.stderr}`)
    const after = {
      library: fs.statSync(libraryFile).mtimeMs,
      still: fs.statSync(path.join(cacheDir, firstItem.still)).mtimeMs,
      thumb: fs.statSync(path.join(cacheDir, firstItem.thumb)).mtimeMs
    }
    assert.equal(after.library, before.library, '二次 missing 改动了 library.json')
    assert.equal(after.still, before.still, '二次 missing 改动了 still')
    assert.equal(after.thumb, before.thumb, '二次 missing 改动了 thumb')

    const status2 = JSON.parse(fs.readFileSync(path.join(cacheDir, 'build-status.json'), 'utf8'))
    assert.equal(status2.state, 'done')
    assert.equal(status2.done, 0)
  } finally {
    fs.rmSync(cacheDir, { recursive: true, force: true })
  }
})

// ---------------------------------------------------------------------------
// 可见性过滤：只看播放列表 / 隐藏 WE 文件夹
// ---------------------------------------------------------------------------

test('collectFolderMap 解析 WE 文件夹树（含嵌套子文件夹）', () => {
  const config = {
    Administrator: {
      general: {
        browser: {
          folders: [
            {
              type: 'folder',
              title: '1',
              items: { 111: 1, 222: 1 },
              subfolders: [{ type: 'folder', title: '景', items: { 333: 1 }, subfolders: [] }]
            },
            { type: 'folder', title: '新文件夹2', items: { 444: 1 }, subfolders: [] }
          ]
        }
      }
    }
  }
  const folders = collectFolderMap(config)
  assert.equal(folders.get('111'), '1')
  assert.equal(folders.get('222'), '1')
  assert.equal(folders.get('333'), '1/景')
  assert.equal(folders.get('444'), '新文件夹2')
  assert.equal(folders.size, 4)
  assert.equal(collectFolderMap(null).size, 0)
})

test('filterVisibleItems / isHiddenFolder：播放列表 + 隐藏文件夹', () => {
  const items = [
    { id: '1', playlistIndex: 1, folder: '1' },
    { id: '2', playlistIndex: null, folder: '1/景' },
    { id: '3', playlistIndex: 3, folder: '新文件夹2' },
    { id: '4', playlistIndex: null, folder: null }
  ]
  assert.deepEqual(
    filterVisibleItems(items, { playlistOnly: true, hiddenFolders: [] }).map((item) => item.id),
    ['1', '3']
  )
  assert.deepEqual(
    filterVisibleItems(items, { playlistOnly: false, hiddenFolders: ['新文件夹2'] }).map((item) => item.id),
    ['1', '2', '4']
  )
  assert.deepEqual(
    filterVisibleItems(items, { playlistOnly: true, hiddenFolders: ['1/景', '新文件夹2'] }).map((item) => item.id),
    ['1']
  )
  assert.deepEqual(filterVisibleItems(null, {}).map((item) => item.id), [])

  assert.equal(isHiddenFolder('1/景', ['景']), true)
  assert.equal(isHiddenFolder('1/景', ['1/景']), true)
  assert.equal(isHiddenFolder('1', ['景']), false)
  assert.equal(isHiddenFolder(null, ['景']), false)
  assert.equal(isHiddenFolder('新文件夹2', ['  ']), false)
})

test('readVisibility：缺省不过滤，坏值收敛', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-cbg-visibility-'))
  try {
    assert.deepEqual(readVisibility(dir), { playlistOnly: false, hiddenFolders: [] })
    fs.writeFileSync(
      path.join(dir, 'visibility.json'),
      JSON.stringify({ playlistOnly: true, hiddenFolders: ['新文件夹2', '  ', 123] })
    )
    assert.deepEqual(readVisibility(dir), { playlistOnly: true, hiddenFolders: ['新文件夹2', '123'] })
    fs.writeFileSync(path.join(dir, 'visibility.json'), 'not json')
    assert.deepEqual(readVisibility(dir), { playlistOnly: false, hiddenFolders: [] })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// ---------------------------------------------------------------------------
// 壁纸取色：浅色 / 深色方案底色随图变化
// ---------------------------------------------------------------------------

test('paletteFromPixels / rgbToHsl / hslToHex：按主色生成浅色与深色底色', () => {
  const size = 32 * 18
  const red = Buffer.alloc(size * 3)
  for (let i = 0; i < size; i++) {
    red[i * 3] = 210
    red[i * 3 + 1] = 40
    red[i * 3 + 2] = 60
  }
  const palette = paletteFromPixels(red)
  assert.ok(isValidPalette(palette))
  const rgb = (hex) => [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16))
  const [lr, lg, lb] = rgb(palette.light)
  const [dr, dg, db] = rgb(palette.dark)
  assert.ok(lr > lg && lr > lb, '浅色底色应保留红色调')
  assert.ok(dr > dg && dr > db, '深色底色应保留红色调')
  assert.ok((lr + lg + lb) / 3 > 150, '浅色底色应偏亮')
  assert.ok((dr + dg + db) / 3 < 80, '深色底色应偏暗')

  const gray = paletteFromPixels(Buffer.alloc(size * 3, 128))
  assert.ok(isValidPalette(gray))
  const [gr, gg, gb] = rgb(gray.light)
  assert.ok(Math.max(Math.abs(gr - gg), Math.abs(gg - gb), Math.abs(gr - gb)) <= 3,
    '灰度图的浅色底色应接近中性灰')

  assert.equal(paletteFromPixels(Buffer.alloc(0)), null)
  assert.equal(paletteFromPixels(null), null)
  assert.equal(isValidPalette(null), false)
  assert.equal(isValidPalette({ light: '#fff', dark: '#000000' }), false)
  assert.equal(isValidPalette({ light: '#ffffff', dark: '#000000' }), true)

  const hsl = rgbToHsl(255, 0, 0)
  assert.equal(Math.round(hsl.h), 0)
  assert.equal(hsl.s, 1)
  assert.equal(hsl.l, 0.5)
  assert.equal(hslToHex(0, 1, 0.5), '#ff0000')
  assert.equal(hslToHex(120, 1, 0.5), '#00ff00')
})
