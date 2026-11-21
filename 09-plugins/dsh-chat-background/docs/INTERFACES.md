# dsh-chat-background 0.3.0 — 实现契约（三方共用）

本文件是 Host / Client / Builder 三部分之间唯一的接口约定。任何一方改动这里的字段名、路径或语义，
必须同步通知 Lead。所有文件都位于 `E:\DS公作区\dsh-chat-background`。

## 0. 环境事实

- Windows。Node.js 24（`node` 在 PATH 中）。无外网依赖，不要新增 npm 依赖。
- Wallpaper Engine：`D:/SteamLibrary/steamapps/common/wallpaper_engine`
  - `bin/workshopcache.json`：367 条壁纸元数据（title/type/tags/filesize/subscriptiondate/workshopid）。
  - `config.json`：`Administrator.general.wallpaperconfig.selectedwallpapers.Monitor0`
    - `.file`：当前壁纸文件（绝对路径）
    - `.playlist.items`：播放列表（364 个文件绝对路径，顺序即 WE 里的显示顺序）
  - 创意工坊内容：`D:/SteamLibrary/steamapps/workshop/content/431960/<id>/`
    - 369 个壁纸目录（比 workshopcache 多 2 个：3456595246、3803580100，需用 project.json 兜底）
    - 每个目录一般有 `project.json`、`preview.jpg|png|gif`、以及 `scene.pkg` / `*.mp4|webm` / `index.html`
- ffmpeg：`E:/JianyingPro/10.6.0.14057/ffmpeg.exe`（构建时自动探测，探测顺序见 Builder 一节）。
- Chrome：`C:/Program Files/Google/Chrome/Application/chrome.exe`（web 壁纸截图用）。
- 缓存根目录（作者机上的真实路径）：`C:/Users/Administrator/.dsh/dsh-chat-background/wallpapers`
  - 通用规则：`path.join(process.env.DSH_HOME || os.homedir() + '/.dsh', 'dsh-chat-background', 'wallpapers')`
  - 可用环境变量 `DSH_CHAT_BG_CACHE` 覆盖（测试用）。
- 已安装 v0.2.0 的线上产物：`C:\Users\Administrator\.dsh\profiles\desktop\node_modules\dsh-chat-background`
  （lib/index.js、lib/client.js，可作为风格参考，**不要修改线上目录**）。

## 1. 缓存目录布局

```
<cacheRoot>/
  library.json          # 清单，Builder 写，Host 读
  build-status.json     # 构建状态，Builder 写，Host 读
  state.json            # 探测到的工具/目录路径（Builder 写）
  visibility.json       # 可见性配置（人工/本机维护，Builder 读）：只看播放列表、隐藏 WE 文件夹
  build.log             # 构建日志（Builder 写，>2MB 时重建）
  stills/<id>.jpg       # 16:9 静态背景图，最长边 ≤ 3840，JPEG q≈90
  thumbs/<id>.jpg       # 480x270 缩略图，JPEG q≈80
```

### library.json

```json
{
  "schema": 1,
  "generatedAt": 1792600000000,
  "weDir": "D:/SteamLibrary/steamapps/common/wallpaper_engine",
  "workshopRoot": "D:/SteamLibrary/steamapps/workshop/content/431960",
  "counts": { "total": 369, "scene": 311, "video": 52, "web": 5, "other": 1, "built": 369 },
  "items": [
    {
      "id": "1197607981",
      "title": "With the Fairies - Shadowverse (Fanart)",
      "type": "scene",
      "folder": null,
      "playlistIndex": 1,
      "current": false,
      "tags": ["Anime"],
      "filesize": 21453743,
      "subscriptiondate": 1734943775,
      "width": 3840,
      "height": 2160,
      "bytes": 987654,
      "source": "embedded",
      "palette": { "light": "#c0c8e2", "dark": "#191e2f" },
      "still": "stills/1197607981.jpg",
      "thumb": "thumbs/1197607981.jpg"
    }
  ]
}
```

- `items` 排序：有 `playlistIndex` 的按升序在前；没有的按 `title.localeCompare(..., 'zh')` 在后。
- `type` 只能是 `scene | video | web | other`。
- `folder`：该壁纸在 WE 里的文件夹路径（如 `"新文件夹2"`、`"1/景"`）；不属于任何文件夹时为 `null`。
- `palette`：从 still 自动提取的两档底色，供「浅色方案底色 / 深色方案底色」跟随壁纸变化：
  浅色方案用同色系浅色（HSL 亮度 ≈0.82），深色方案用同色系深色（亮度 ≈0.14）；近灰度图退化为中性灰。
  取色算法见 `tools/build-library.mjs` 的 `paletteFromPixels`（ffmpeg 缩到 32×18 RGB 后按饱和度/亮度加权求主色相）。
  旧清单里已有合法 palette 时直接复用；只有新图/换图才重新计算。
- `playlistIndex`：WE 播放列表中的 1-based 下标；不在列表里为 `null`。
- `current`：是否 WE 当前正在使用的壁纸（同名目录匹配 `selectedwallpapers.Monitor0.file` 的目录）。
- `source`：`embedded`（scene.pkg 里提取的图）/ `video`（视频抽帧）/ `web`（网页截图）/
  `preview-composite`（方形预览图合成 16:9）/ `preview`（直接拷 preview 图）。
- `still`、`thumb`：相对 `<cacheRoot>` 的 POSIX 路径。
- 只有成功生成 still+thumb 的条目写进 items；counts.built = items.length。某一条失败时
  尽量降级到 `preview-composite`；彻底失败则不收录，并写入 build-status.json 的 errors。

### build-status.json

```json
{
  "state": "idle | running | done | error",
  "mode": "missing | force",
  "startedAt": 0, "updatedAt": 0, "finishedAt": 0,
  "done": 0, "total": 369, "current": "标题",
  "message": "人话说明",
  "errors": [ { "id": "123", "message": "..." } ]
}
```

- Builder 启动时写 `running`，每完成一项刷新一次（最多 1 秒一次），结束写 `done`（有 errors 也算 done）或 `error`。
- Host 在 library 不存在时也要能返回 build 状态。

### state.json

```json
{ "ffmpeg": "E:/JianyingPro/10.6.0.14057/ffmpeg.exe", "chrome": "C:/.../chrome.exe",
  "weDir": "...", "workshopRoot": "...", "detectedAt": 1792600000000 }
```

### visibility.json（可见性过滤，人工维护）

```json
{ "playlistOnly": true, "hiddenFolders": ["新文件夹2"] }
```

- 文件不存在时等价于 `{ "playlistOnly": false, "hiddenFolders": [] }`（不过滤，开箱即用）。
- `playlistOnly: true`：只保留 `playlistIndex != null` 的条目。
- `hiddenFolders`：按 WE 文件夹路径隐藏（整路径、任意一段、`/` 结尾匹配都算命中）。
- Builder 在元数据阶段过滤后再排队/汇总，`counts.total`/`counts.built` 都反映过滤后的数量；
  被过滤条目的 still/thumb 文件保留在磁盘上但不出现在 `library.json`，改回配置重新生成即可恢复。

## 2. Builder：`tools/build-library.mjs`

CLI：`node tools/build-library.mjs [--mode missing|force] [--cache <dir>] [--limit N] [--ids 1,2] [--quiet]`

- `--mode missing`（默认）：已有 still+thumb 且源文件未更新的条目跳过；只补缺。
- `--mode force`：全部重做。
- `--limit N` / `--ids`：调试用，只处理前 N 条 / 指定 id。
- 结束时必须写出完整 `library.json`（即使只处理了部分条目，也要把全部可识别的条目写进去，
  已有缓存的条目沿用旧 still/thumb）。
- 找不到 Wallpaper Engine / 创意工坊目录 / ffmpeg 时：写 `build-status.json`（state=error, message 人话），
  非零退出码；不要抛未捕获异常。
- 单条失败：记录 errors，继续；能降级就降级（scene/video/web 失败 → preview-composite）。
- 并发 4 个 worker，ffmpeg 通过 `child_process.spawnSync` 调用（不要第三方库）。
- 探测顺序：
  - ffmpeg：env `DSH_CHAT_BG_FFMPEG` → PATH 里的 `ffmpeg` → 已知路径通配
    `E:/JianyingPro/*/ffmpeg.exe`、`D:/JianyingPro/*/ffmpeg.exe`、
    `C:/Program Files/ffmpeg*/bin/ffmpeg.exe`、`%LOCALAPPDATA%/Microsoft/WinGet/Packages/.../ffmpeg.exe`。
  - chrome：env `DSH_CHAT_BG_CHROME` → `C:/Program Files/Google/Chrome/Application/chrome.exe`
    → `C:/Program Files (x86)/Google/Chrome/Application/chrome.exe`
    → `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`。
  - WE/工坊：env `DSH_WE_DIR` / `DSH_WE_WORKSHOP` → 解析 Steam 的 `steamapps/libraryfolders.vdf`
    （候选库根：`C:/Program Files (x86)/Steam`、`C:/Program Files/Steam`、
    `C:/Steam`、`D:/SteamLibrary`、`D:/Steam`、`E:/SteamLibrary`、`E:/Steam`、`F:/SteamLibrary` 等，
    含每个盘的 `SteamLibrary`/`Steam`）→ 在候选库下找 `steamapps/common/wallpaper_engine`
    与 `steamapps/workshop/content/431960`。
- 元数据合并：workshopcache.json（title/type/tags/filesize/subscriptiondate）+ project.json
  （title/type/tags/file/preview，需去 BOM、容错解析）+ 目录名 id 兜底；
  WE 文件夹树（`config.json` → `Administrator.general.browser.folders`）解析成 `folder` 字段。
- 可见性过滤：读 `<cacheRoot>/visibility.json`，在排队前剔除不符合 `playlistOnly` / `hiddenFolders`
  的条目（见第 1 节）。
- 静态图生成规则（全部输出 16:9，JPEG）：
  - scene：读 `<id>/scene.pkg`（≤40MB），**整文件扫描** PNG/JPEG 内嵌图（不要依赖 PKG 版本解析；
    PKGV0001..0024 结构不一致）。取尺寸合法（0<w,h≤8192，面积≥1280×720，W/H∈[0.3,4]）中面积最大者，
    用 ffmpeg 缩放裁切：`scale='if(gt(iw,3840),3840,iw)':-2,crop='min(iw,ih*16/9)':'min(ih,iw*9/16)'`。
  - video：取 `<id>` 下 project.json `file` 指向的视频（或目录里第一个 mp4/webm/mkv/mov）。
    `ffmpeg -ss 2 -i <video> -vf "thumbnail=90,scale='if(gt(iw,3840),3840,iw)':-2,crop='min(iw,ih*16/9)':'min(ih,iw*9/16)'" -frames:v 1 -q:v 2 out.jpg`。
  - web：用 Chrome headless 截图 `--headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files
    --window-size=1920,1080 --virtual-time-budget=12000 --screenshot=<tmp.png> file:///<index.html>`，
    再用 ffmpeg 转成 16:9；截图超时 45s。
  - 兜底 preview-composite：方形 preview 居中，两侧同图模糊铺满（ffmpeg filter_complex，
    目标 1920×1080，前景高 96%）。
  - thumb：由 still 缩到 480×270。
  - palette：`ffmpeg -i <still> -vf scale=32:18:flags=area -f rawvideo -pix_fmt rgb24 -` 取原始像素，
    按 `paletteFromPixels` 求主色相，输出 `{ light, dark }` 两个 #rrggbb。旧清单里已有合法 palette 直接复用，
    因此 `--mode missing` 重复跑不会反复取色。
- 日志：stdout + `<cacheRoot>/build.log`。

## 3. Host：`lib/index.js`

保留 v0.2.0 的全部行为（配置读写、`/dsh-chat-bg/config`、`/dsh-chat-bg/image`、鉴权栅栏、static 导入），
只新增以下内容。所有新路由沿用同样的 `connection.requestRejection` 栅栏。

路由（均以 `/dsh-chat-bg` 为前缀）：

1. `GET /wallpapers` → 200
```json
{
  "ok": true,
  "version": "0.3.0",
  "counts": { "total": 369, "scene": 311, "video": 52, "web": 5, "other": 1, "built": 369 },
  "build": { ...build-status.json 内容... },
  "selectedId": "1197607981",
  "selectedCustom": false,
  "items": [
    { "id": "1197607981", "title": "...", "type": "scene", "playlistIndex": 1,
      "current": false, "tags": ["Anime"], "filesize": 21453743, "subscriptiondate": 1734943775,
      "width": 3840, "height": 2160, "source": "embedded",
      "palette": { "light": "#c0c8e2", "dark": "#191e2f" },
      "thumb": "/dsh-chat-bg/wallpaper?id=1197607981&kind=thumb",
      "still": "/dsh-chat-bg/wallpaper?id=1197607981&kind=still" }
  ]
}
```
- `palette`：Builder 写的两档底色原样透传给浏览器（缺失/非法时为 `null`），供 Client 在选图时自动套用。
- `selectedId`：用当前配置的 `imagePath` 与 library 条目的 still 绝对路径比对得出；匹配不到且 `imagePath`
  非空 → `selectedId: null, selectedCustom: true`。
- library 不存在：`{ "ok": false, "error": "library-missing", "build": {...}, "message": "人话" }`，HTTP 200。
- 用文件 mtime+size 做内存缓存；library.json 变更后自动重载。
2. `GET /wallpaper?id=<纯数字>&kind=still|thumb` → JPEG 字节流。
   - id 非法 / kind 非法 → 400；文件不存在 → 404。
   - 头：`Content-Type: image/jpeg`、`Cache-Control: private, max-age=604800`、`ETag: "<size>-<mtimeMs>"`；
     请求头 `If-None-Match` 命中 → 304。
   - 路径必须 resolve 在 `<cacheRoot>` 内（防目录穿越）。
3. `POST /wallpapers/refresh` body 可选 `{"mode":"missing"|"force"}`（默认 missing）→ 200
   - 已在构建：`{ "ok": true, "accepted": false, "build": {...} }`
   - 已受理：spawn `process.execPath [<pkgRoot>/tools/build-library.mjs, '--mode', mode, '--cache', cacheRoot]`，
     `detached:true, stdio:'ignore', windowsHide:true`，`unref()`；返回 `{ "ok": true, "accepted": true, "build": { "state":"running", ... } }`。
   - 脚本不存在或 spawn 抛错：`{ "ok": false, "error": "..." }`（500）。
4. `POST /wallpapers/select` body `{"id":"1197607981"}` → 200
   - 找到条目、still 文件存在 → 用现有 `sanitize`/`writeConfig` 写入：
     `enabled: true, mode: 'image', imagePath: <still 绝对路径>, imageUrl: ''`（其余字段保持当前配置）。
   - 返回 `{ "ok": true, "config": {...}, "imageVersion": "...", "item": { "id","title" } }`。
   - 找不到条目 / 文件 → 404 `{ "ok": false, "error": "wallpaper-not-found" }`。

其他要求：
- 新增常量 `WALLPAPER_CACHE`（支持 env `DSH_CHAT_BG_CACHE` 覆盖，默认 `DSH_HOME/dsh-chat-background/wallpapers`）。
- 保留 `imageVersion`、`MAX_IMAGE_BYTES` 等旧逻辑。
- 允许在模块里导出 `__test`（如 `readLibrary`, `cacheRoot`, `MIME`）供测试用；`apply/inject/name` 保持。
- 不要改 `cordis.patch.yml`。

## 4. Client：`lib/client.js`

仍是 `window.__ModuleLoader__.load({ id: 'dsh-chat-background', factory })` 形式，只能 `require('react')`，
不引入 JSX、react-dom、第三方库。保留 v0.2.0 的全部设置项与生效逻辑（token 覆盖、运行时 CSS、
localStorage 缓存、Host 配置同步、`__test` 导出、卸载清理），只做以下增强：

- 图片模式（`cfg.mode === 'image'`）下新增一张「壁纸库」卡片，位于图片设置下面、恢复默认按钮上面：
  1. 打开面板时 `fetch('/dsh-chat-bg/wallpapers')`：
     - 成功：保存 `{ok, counts, build, items, selectedId, selectedCustom}` 到 state。
     - `ok:false`（library-missing 等）：显示错误 + 「生成壁纸库」按钮。
  2. 卡片内容：
     - 标题行：「Wallpaper Engine 壁纸库」+ 计数徽标（如 `369 张 · 场景 311 / 视频 52 / 网页 5`）。
     - 当前壁纸：`selectedId` 对应条目的 thumb + 标题 + `#播放列表序号`；没有选中则「未选择」；
       `selectedCustom` 时显示「自定义本地图片」。
     - 按钮：`打开壁纸库`、`随机一张`、`重新扫描/生成`（build 运行中禁用并显示进度）。
     - build 运行中显示进度条/文字 `正在生成静态封面 done/total`，每 2.5s 轮询 `/wallpapers` 直到 state 不是 running。
  3. 壁纸库弹窗（点击「打开壁纸库」）：
     - 自绘 fixed 覆盖层：`position:fixed; inset:0; z-index:2000; background:rgba(0,0,0,.55)`，
       居中一个 `min(1100px, 92vw)` × `min(760px, 88vh)` 的面板，flex 纵向布局，圆角 14px，
       背景 `var(--dsw-alias-bg-module-platform)`，文字 `var(--dsw-alias-label-primary)`。
     - 头部：标题 + 计数 + 关闭按钮。
     - 工具栏：搜索框（标题/id，忽略大小写）、类型下拉（全部/场景/视频/网页）、
       排序下拉（播放列表顺序/名称/最近订阅/分辨率）、随机一张、重新生成、完成按钮。
     - 内容：滚动网格 `repeat(auto-fill, minmax(150px,1fr))`，每格 16:9；
       图片 `loading="lazy"`，src 用接口返回的 thumb URL；左下角标题两行截断；
       左上角 `#序号` 徽标；右上角类型徽标（场景/视频/网页）；选中项高亮 + ✓。
     - 点击格子：`POST /dsh-chat-bg/wallpapers/select {id}`，成功则把返回的 config 走
       `saveCache + applyConfig + setCfg`，`selectedId` 更新，状态行显示「已切换：标题」；弹窗不自动关闭。
       **底色跟随壁纸**：若条目带 `palette`，用 `palette.light/dark` 覆盖配置里的 `colorLight/colorDark`，
       再 `POST /dsh-chat-bg/config` 写回 Host；令牌与运行时 CSS 会随新底色立即重算。
       面板里加一行提示：「从壁纸库选图时会自动按壁纸主色更新浅色/深色底色；手动改色后以下次换图取色为准。」
     - 搜索/筛选/排序在客户端完成；列表 349 条（本机按 visibility 过滤后），可全量渲染。
  4. 所有新样式用 `__cbgw_` 前缀的 class，走现有 `ensurePanelCss` 注入方式（首次注入 + 幂等）。
- 兜底：Host 不可达 / 接口 404 时不阻塞原功能，卡片显示「壁纸库接口不可用（需 0.3.0 Host 生效）」。
- `__test` 扩展导出：至少增加 `galleryCss` 之类不依赖 DOM 的纯函数可测；具体自定，但 `sanitize`,
  `tokensFor`, `cssFor`, `hexToRgba`, `setImageVersion` 必须保留。

## 5. 测试与验收

- 三份 `node test/*.test.mjs`（或 .mjs）可直接 `node` 运行，无外部依赖：
  - `test/host.test.mjs`：用 stub ctx（webServer.register 收集路由、connection.requestRejection 放行、
    ctx.effect）动态 import Host，构造 mock req/res 调 5 个路由；覆盖 config GET/POST、wallpapers 列表、
    wallpaper 图片（200/304/400/404/穿越防护）、select、refresh（用假 builder 脚本或跳过 spawn）。
    测试期间 `process.env.DSH_CHAT_BG_CACHE` 指向临时目录，`process.env.DSH_HOME` 同样指临时目录。
  - `test/client.test.mjs`：沿用 v0.2.0 `test/smoke.mjs` 的 window/document/localStorage/fetch 桩，
    执行 client.js 的 factory → apply → 面板组件渲染，断言壁纸库请求、选中切换后配置与 CSS 生效。
  - `test/we-library.test.mjs`：Builder 纯函数测试（pkg 图片扫描/选择、元数据合并、排序），
    在临时目录里跑 `--limit 3` 的端到端（真实 ffmpeg/WE 环境，失败可 skip 并打印原因）。
- Lead 负责最终安装与浏览器验收，任何人不要调用 `plugin_manager`、不要改 profile 目录。

## 6. 硬性纪律

- 只改自己 task 写作用域内的文件；共享文件（package.json、locale、icon、README、docs）由 Lead 负责。
- 不要动 `C:/Users/Administrator/.dsh/profiles/desktop`、不要卸载/安装插件、不要重启 App。
- 不要读取/修改 369 个壁纸目录里的原始文件（只读）。
- 中文注释、UTF-8、2 空格缩进，和现有 lib 代码风格一致。
