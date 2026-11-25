# Changelog

## 0.3.3（2026-11-25）

- 修复：`package.json` 补回 `repository` 字段（指向 `Uneadlight/fatfish-lab`）。此前为了市场 tarball 安装路径，仓库副本删掉了该字段，源码也跟着没写，导致 npm 上 0.3.2 的元数据缺少回链，市场站点的 `probe-npm.mjs` 认不到，从而退回 tarball 安装。
- 无功能改动（0.3.2 的 ffmpeg 管道修复保持不变）。

## 0.3.2 — 2026-11-24

**修复：动态壁纸封面在受限环境里生成失败（`Permission denied`）。**

起因：面板点「重新生成」后，新订阅的那张壁纸每次都在 `build-status.json` 里记为失败，
错误是 `Could not open file : ...\stills\<id>.jpg.tmp-*` / `Permission denied`。

根因（同机实测对照）：

| 写入方 | 目标 | 结果 |
| --- | --- | --- |
| ffmpeg 子进程 | `~/.dsh/dsh-chat-background/wallpapers/stills` | 拒绝 |
| ffmpeg 子进程 | `C:\Users\<user>\Downloads` | 拒绝 |
| ffmpeg 子进程 | `%TEMP%` | 拒绝 |
| ffmpeg 子进程 | 工作区 `E:\DS公作区\.tmp` | 成功 |
| node / PowerShell（宿主进程） | `~/.dsh/.../stills` | 成功 |

即：受限沙箱只允许**子进程**写工作区，而宿主进程能写 `.dsh`。
所以「让 ffmpeg 直接写目标文件」这条路在任何目标位置都走不通。

改法：**让 ffmpeg 输出到 stdout，由宿主进程落盘。**

- 新增 `ffmpegJpegToFile(ffmpeg, args, outFile, timeout)`
  —— `spawnSync` 加 `-f image2pipe -c:v mjpeg pipe:1`，接住字节后 `fs.writeFileSync`；
  退出码非 0 时返回 stderr 最后 6 行，便于面板显示原因。
- 四处调用改为走它：`produceStillFromImage` / `produceStillFromVideo` /
  `produceThumbOnly` / `produceComposite`（`preview-composite` 兜底同病）。
- `tmpSibling()` 恢复为「同目录临时文件」（现在由宿主进程写，有权限，保留原子替换语义）。
- `replaceFile()` 增加跨卷回退：`EXDEV` 时 `copyFileSync` + `rmSync`。

实测（同一受限环境，与面板一致）：删掉那张的 still/thumb 后跑 `--mode missing` →
`完成：可用 352/352 张，本次新建 1 张，跳过 351 张，失败 0 张（耗时 1.3s）`，
产物 752,139 B / 23,406 B，与手动绕过时的字节数一致。

**顺带修了两处过期测试断言**（与本修复无关，但一直红着，会掩盖真问题）：

- `test/host.test.mjs`：版本断言写死 `'0.3.0'` → 改成读 `package.json` 的 `version`。
- `test/client.test.mjs`：`ModuleLoader` id 断言写死 `'dsh-chat-background'` → 改成读 `package.json` 的 `name`
  （包名已改为 `@un10086/dsh-chat-background`）。

**说明**：本版 `package.json` 暂时移除了 `repository` 字段。这是为了让插件市场（PR
awesome-dsh-plugin#17466）走条目里的 `tarball:` 指向 GitHub Release，而不是回落到 npm 上
补丁损坏的旧版本；等 npm 账号解冻、0.3.2 发布成功后恢复。

## 0.3.1 — 2026-11-21

修复 `cordis.patch.yml` 里 `name` 值未加引号的问题——YAML 中 `@` 是保留字符，
不加引号会让补丁解析失败，表现是三个自研插件在重启后仍提示加载异常。

## 0.3.0 — 2026-11-20

首个发布到 npm 的版本：内置 Wallpaper Engine 壁纸库（读取播放列表、扫描工坊目录、
为动态壁纸生成静态封面），面板提供搜索、选中、随机、重新生成与进度轮询。
