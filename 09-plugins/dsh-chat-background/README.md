# dsh-chat-background

给 DeepSeek Harness 的聊天界面换背景：**纯色**或**图片**，浅色/深色方案各自独立，可调面板不透明度与压暗层。
0.3.0 起内置 **Wallpaper Engine 壁纸库**：把你已下载（Steam 创意工坊订阅）的壁纸直接挑成对话背景，
不用再手输本地图片路径；动态壁纸（场景 / 视频 / 网页）会自动生成静态封面，选中的那张就是静态背景图。
壁纸库默认**只收录 Wallpaper Engine 播放列表里的壁纸**（本机 349 张），并支持隐藏指定 WE 文件夹，
见下文「壁纸可见性」。

装在 `desktop` / `web` profile 都行。

## 装好之后在哪

**设置 → 对话背景**。

- 打开「启用自定义背景」立刻生效。
- 「壁纸库」卡片里点 **打开壁纸库**：搜索、按类型筛选、按 WE 播放列表顺序排序，点任意一张立即切换。
- 每个壁纸都会生成：
  - `stills/<id>.jpg`：16:9 静态背景图（场景从 `scene.pkg` 内嵌原画提取，视频抽帧，网页截图）；
  - `thumbs/<id>.jpg`：壁纸库缩略图。
- 缓存默认在 `~/.dsh/dsh-chat-background/wallpapers/`，可以在面板里「重新生成」来补齐新订阅的壁纸。

## 依赖（只用本机已有的程序，插件不打包它们）

| 用途 | 程序 | 说明 |
|---|---|---|
| 视频壁纸抽帧 / 图片缩放裁剪 | `ffmpeg` | 自动探测 PATH、`E:/JianyingPro/*/ffmpeg.exe`、`D:/JianyingPro/*/ffmpeg.exe` 等；可用 `DSH_CHAT_BG_FFMPEG` 指定 |
| 网页壁纸截图 | Chrome / Edge | 自动探测常见安装位置；可用 `DSH_CHAT_BG_CHROME` 指定 |
| 壁纸来源 | Wallpaper Engine | 自动解析 Steam 的 `libraryfolders.vdf`；可用 `DSH_WE_DIR` / `DSH_WE_WORKSHOP` 指定 |

找不到 ffmpeg 时仍可浏览壁纸库，但动态壁纸只能退化成方形预览图合成的背景；找不到 Wallpaper Engine 时
面板会提示「壁纸库接口不可用 / 壁纸库还没生成」。

## 选项

| 选项 | 默认 | 作用 |
|---|---|---|
| 启用自定义背景 | 关 | 总开关。关着时界面与原生完全一致 |
| 类型 | 纯色 | `纯色` 只换各层表面底色；`图片` 把表面改成半透明，让图片透上来 |
| 浅色 / 深色方案底色 | `#f3efe6` / `#15171b` | 两套配色各自取色，跟随 DSH 主题切换。**从壁纸库选图时会自动按壁纸主色更新这两档底色**，见下文「底色跟随壁纸」 |
| 图片地址 | 空 | `http(s)` 网址或 `data:image/...` 的 data URL |
| 本地图片路径 | 空 | 也可手输任意本地 jpg/png/webp/gif/avif 路径 |
| 面板不透明度 | 72% | 仅图片模式。越低越透，文字越难读 |
| 压暗层 | 18% | 仅图片模式。浅色方案盖白、深色方案盖黑 |
| 侧栏也一起换 | 开 | 侧栏是否跟着换色 |

> 选壁纸库里的图时，Host 会把该图的本地路径写进「本地图片路径」，所以旧的手动输入方式仍然可用。

## 底色跟随壁纸

从壁纸库换图时，「浅色方案底色 / 深色方案底色」会自动跟着壁纸主色变：

- Builder 在生成静态封面时顺便取色（`palette` 存在 `library.json` 里）：
  把 still 缩到 32×18 原始像素，按饱和度/亮度加权求主色相，再生成
  浅色方案用的浅色系底色（同色相、低饱和、高亮度）和深色方案用的深色系底色（同色相、低饱和、低亮度）。
- 选壁纸时浏览器把这两档颜色写进配置并立即生效；手动改色会保留到下次换图。
- 灰度/黑白壁纸会自动退化成中性灰调，不会出现奇怪的颜色。
- 想改取色参数（饱和度/亮度）：改 `tools/build-library.mjs` 里的 `paletteFromPixels`，
  删掉 `library.json` 后跑一次 `node tools/build-library.mjs --mode missing` 重新取色。
- 只有「壁纸库」里的图会自动取色；手动输入本地图片路径时两档底色保持原样。

## 壁纸可见性（只看播放列表 / 隐藏文件夹）

壁纸库收录哪些图由缓存目录里的 `visibility.json` 决定（默认只收录 WE 播放列表里的壁纸）：

```json
{
  "playlistOnly": true,
  "hiddenFolders": ["新文件夹2"]
}
```

- `playlistOnly`：只收录 Wallpaper Engine 播放列表（`config.json` → `selectedwallpapers.Monitor0.playlist`）
  里出现过的壁纸；关掉后会把创意工坊里所有已下载壁纸都列出来。
- `hiddenFolders`：按 WE 的壁纸文件夹标题隐藏（支持嵌套路径，例如 `"1/景"`）。本机把「新文件夹2」里的
  28 张（其中 17 张已下载）排除掉了，播放列表规则本身也会排除它们。
- 文件位置：`~/.dsh/dsh-chat-background/wallpapers/visibility.json`。
- 改完在设置页点「重新扫描/生成」，或命令行执行：
  ```bash
  node tools/build-library.mjs --mode missing --cache "%USERPROFILE%\.dsh\dsh-chat-background\wallpapers"
  ```
  之后重新打开「壁纸库」即可看到新的数量（不需要重启 DSH）。
- 被排除的条目的静态图仍留在 `stills/`、`thumbs/` 里（只是不再出现在清单），把配置改回来再生成一次就能恢复。

## 实现方式

不硬改 DOM 结构，走 DSH 官方扩展点：

- **`ctx.theme.overrideTokens(source, tokens)`** —— 主题令牌覆盖层。覆盖 `--dsw-alias-bg-base`、
  `--dsw-alias-bg-layer-1/2`、`--dsw-alias-bg-overlay`、`--dsw-alias-bg-module-platform`、
  `--dsw-specific-sidebar-fill`，自动分浅色/深色两套。
- **`ctx.slots.register({name:'settings.section'})`** —— 设置页里加「对话背景」。
- 图片模式另外注入一段运行时 CSS，在 `body` 上画背景图（`background-attachment: fixed`）并叠遮罩。
- Host 路由（都过 `connection.requestRejection` 鉴权栅栏）：
  - `GET/POST /dsh-chat-bg/config` —— 配置读写
  - `GET /dsh-chat-bg/image` —— 读配置里的本地图片
  - `GET /dsh-chat-bg/wallpapers` —— 壁纸库清单 + 构建状态
  - `GET /dsh-chat-bg/wallpaper?id=&kind=still|thumb` —— 静态背景图 / 缩略图
  - `POST /dsh-chat-bg/wallpapers/refresh` —— 重新扫描并补齐静态图
  - `POST /dsh-chat-bg/wallpapers/select` —— 选中某张壁纸，写配置并返回最新 config
- 静态图构建器：`tools/build-library.mjs`（纯 Node + ffmpeg + Chrome，无 npm 依赖），
  缓存结构与构建契约见 `docs/INTERFACES.md`。

## 测试

```bash
node test/host.test.mjs
node test/client.test.mjs
node test/we-library.test.mjs
```

## 排错

- **壁纸库是空的 / 只有旧条目**：点面板里的「重新生成」，或命令行
  `node tools/build-library.mjs --mode missing`，看 `~/.dsh/dsh-chat-background/wallpapers/build.log`。
- **选中的图不出现**：确认「启用自定义背景」开着、类型是「图片」；配置落盘在 `~/.dsh/dsh-chat-background.json`。
- **想换回自己的图**：在「本地图片路径」里填任意路径即可；壁纸库条目只是把路径填好而已。
- **重建后想让浏览器立刻刷新**：换图接口带 mtime 版本号，会自动重取。

## License

MIT
