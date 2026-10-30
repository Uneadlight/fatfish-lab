# 大内总管（Env Doctor）

> DSH 的插件与环境大管家：一条命令查清全部运行状态，逐插件验证加载，自动化覆盖、工具链与模型版本全管，还带后台 30 分钟巡检守护。

版本：0.5.1 ｜ 工具名：`env_doctor`（技术名不变，界面显示名「大内总管」）

---

## v0.6.1（2026-10-26）：客户端 bundle 一致性检查

dsh-evolve 连续踩了两个「装完打不开 / 图标不出现」的坑（缺 exports["./client"]；client.js 注册 id 用了 loader 行 id 而不是包名），所以把这类检查固化成常驻项：

- 新检查 `checkClientBundles()`：遍历 profile 的 bundles，对每个第三方/自研包验证①包目录存在 ②声明了 dsh.client 就必须有 `exports["./client"]` 且文件存在 ③client.js 里 `__ModuleLoader__.load({id})` 必须等于包名。任一不满足 → FAIL 并给出修法。
- 接入位置：`only=all`、`only=changes`、新增 `only=bundles`，以及 30 分钟快档巡检（装完插件就会自动验，不用等重启崩一次才发现）。
- 顺带清理：发现孤儿 bundle 条目 `@agents-anywhere/dsh-bridge-next`（node_modules 里是空目录，已从 bundles 移除）。

这就是「脏活累活」：装插件、升级插件之后，这类事务性校验由大内总管自动做掉。

## 一、怎么用

直接调用 `env_doctor` 工具，按需选 `only` 组（不填 = `all`）：

| only 参数 | 检查什么 | 典型场景 |
| --- | --- | --- |
| `all` | 全部组（不含联网查更新） | 日常体检 |
| `workspace` | 工作区沙箱可写性 | 写文件被拒 |
| `bili` | billion-context sidecar 是否重读配置 | 压缩配置改了没生效 |
| `paths` | 关键目录是否存在可写 | 插件装完找不到目录 |
| `tasks` | 计划任务是否还活着 | 定时任务没跑 |
| `automation` | 插件→定时任务覆盖情况 | 插件有更新没自动跑 |
| `plugins` | 联网查插件/NPM 新版本 | 想知道有没有新版 |
| `health` | 逐个 import 验证插件入口能否加载 | 插件装了没反应/疑似坏了 |
| `inventory` | MCP 服务器/共享技能/自定义工具清单 | 想盘点能力 |
| `tools` | 自研插件目录、Ollama 视觉模型、智谱 key、RapidOCR、ffmpeg、插件包完整性、.dsh 体积 | 新装工具后验货 |
| `version` | Ollama 版本 vs GitHub 最新、本地视觉模型、智谱模型升级提示 | 模型版本检查 |
| `deep` | 复用 check.mjs 跑全量 11 项 | 深度体检 |
| `fix=true` | 自动修安全项（建目录等），危险操作只给命令 | 一键修好 |

**示例**：

```
env_doctor()                          # 全部体检
env_doctor({only: "health"})          # 插件能不能加载
env_doctor({only: "tools"})           # 自研工具是否齐全
env_doctor({only: "version"})         # 模型版本
env_doctor({fix: true})               # 自动修安全项
```

---

## 二、检查项清单

- **环境/工作区**：workspace 可写、关键目录、磁盘余量
- **bili sidecar**：配置 mtime vs 进程 startedAt（改完配置是否重读）
- **计划任务**：4 个自动化任务状态（上次/下次/结果）
- **插件健康**：20 个本地插件逐个 import 验证（DSH 运行时 peer 依赖会跳过）
- **插件方向**：自研 5 插件目录（env-doctor/vision/workflow-skill/worktree-tool/open-design-mcp）
- **工具链**：Ollama 视觉模型、智谱 API key、RapidOCR、ffmpeg
- **模型版本**：Ollama 本地版本 vs GitHub 最新；视觉模型可用性；智谱模型名升级提示
- **插件包完整性**：node_modules 包全部有 package.json（防半装/悬空链接）
- **数据体积**：.dsh 目录大小（防爆盘）
- **自动化覆盖**：哪些插件有定时任务、哪些靠手动
- **自动学习**：学习循环进程是否活着（**不在会自动重启**）、最近一轮是否报错
- **UI 资源**：插件市场缓存、OpenDesign MCP 端口

---

## 三、后台守护

- **30 分钟快检**：workspace/bili/paths/memories/pluginDirs/**pluginDrift**/disk/configDrift/autolearn（发现异常才出声）
- **6 小时慢检**：计划任务/自动化覆盖/工具链/插件版本（health、inventory、tools、version 仍按需调用，避免每 6 小时重复 import 全部插件）
- **插件变更追踪（v0.6.0）**：每次巡检对比 `.plugin-snapshot.json` 基线，自动发现**新增/移除/版本变化**的插件（自研、第三方、市场装的都算），新插件会自动提示跑 `only=health` 验货
- **定时任务**：`DSH-Plugin-Check` 每天跑一次全量；`DSH-EnvDoctor-Iterate` 每月自检
- **自动修复**：学习循环挂了自动 `Start-ScheduledTask` 拉起；安全项（建目录）自动修

---

## 四、文件位置

```
D:\work\dsh-env-doctor\
├── index.js              # 插件主代码（约 1500 行）
├── package.json          # 版本/描述（0.5.1，大内总管）
├── locale/zh.json        # 中文显示名（大内总管）
├── locale/en.json        # 英文显示名（Grand Steward）
├── cordis.patch.yml      # 插件挂载配置
├── .guard-alerts.json    # 后台巡检告警状态（运行时生成，跨重启去重）
└── selftest.mjs          # 自检脚本
```

**代码位置**：`index.js` 里各个 `checkXxx()` 函数即检查项，`guardLightChecks`/`guardSlowChecks` 是守护入口，`execute()` 是工具入口。

---

## 五、常见场景

| 现象 | 用什么 |
| --- | --- |
| 刚装了/卸了/升级了插件 | `only=changes` |
| 插件装完没反应 | `only=health` |
| 配置改完不生效 | `only=bili` 或 `only=configDrift` |
| 定时任务没跑 | `only=automation` / `only=tasks` |
| 怀疑环境问题 | `only=all` |
| 新装工具没验货 | `only=tools` |
| 模型要不要升级 | `only=version` |

---

## 六、变更记录

- v0.6.0（2026-10-26）：**插件变更追踪** `checkPluginDrift()`（基线 `.plugin-snapshot.json`，巡检自动发现新增/移除/版本变化，接入 30 分钟快检与 `only=changes`）；`only=tools` 的自研插件目录改为**动态扫描** `@local`（link 符号链接也识别），新增「自研插件未登记到 profile」检查。
- v0.5.1（2026-10-26）：外部/内置 bundle 不再按 node_modules 误判缺失；compat-check 的 FAIL 不再误报成“跑不起来”；守护告警跨重启去重；修掉 .dsh 体积与 Ollama 的写死路径；DSH 运行时 peer 依赖不再误报模块加载失败。
- v0.5.0（2026-10-25）：改名「大内总管」；加 checkLocalTools / checkModelVersions / checkMiscAndMcp；学习循环自动重启；完整中文文档（本文件）。
- v0.4.x：pluginDirs / inventory / toolchain / health / configDrift / memories 系列检查。
- v0.3.x：基础 workspace/bili/paths/tasks/automation。

### v0.6.3（2026-10-26）
- 修 checkClientBundles 误报：桌面版随包发布的 bundle（如 `dsh-community-market`）位于应用自己的 node_modules，原扫描只看 profile → 误判「包目录不存在」。现在 locateBundleDir 会回退到 `process.resourcesPath/app/node_modules`。
- 实测：`only=bundles` → 27 个入口全部可解析（6 个 DSH 内置），12 个带浏览器端且注册 id 与包名一致。
