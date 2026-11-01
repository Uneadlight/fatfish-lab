# 自身能力清单

> 盘清日期：2026-10-31
> 来源：`%USERPROFILE%\.dsh\profiles\desktop\package.json` 的 `dsh.profile.bundles`（共 **25** 个）
> 为什么要这张表：用户要求"对自身所有插件都有理解，掌控力到 90%"。在此之前我连总数都说错（说成"19 个"），只有数过才算真知道。

> **⚠️ 分母修正（同日晚些时候发现）**：25 个只是**装配清单**（profile 引用了谁）。把 `D:\DeepSeek Harness\resources\app.asar` 的 header 索引读出来后，底下实际躺着 **307 个 `@deepseek-ai/*` 包**。所以"掌握 25 个"和"掌握全部"是两件事——**按包算，我的掌握度远低于 55%**。
>
> 但也不必 307 个都摸：多数是地基（`dsh-fs`、`dsh-session`、`dsh-llm` 这类我不直接调）。真正该关心的是**能给我工具的**（`dsh-tool-*`）和**默认关闭但可能有用的**（`dsh-experimental-*`，约 25 个）。

## 一、总览

| 来源 | 数量 | 状态 |
|---|---|---|
| 官方（DeepSeek 内置，在 `app.asar` 里） | **6** | ⚠️ **4 个从没主动用过** |
| 我自己写的（`@local/*` + `dsh-memory` / `dsh-stickers` / `dsh-session-delete`） | **9** | 8 个在用，1 个没碰过 |
| 第三方（社区/他人） | **10** | 6 个明确在用，4 个不清楚 |

**掌控力自评**（诚实版，**2026-11-01 晚更新**）：

| 三段 | 旧（10-31） | 新（11-01） | 涨在哪 |
|---|---|---|---|
| 我自己写的 9 个 | 90% | **93%** | 21 插件的「怎么验证活着」写完了，9 个全有具体检查动作 |
| 官方 6 个 | 20% | **70%** | 306 包索引 + 16 层分层，知道每个包在哪一层干什么；但 4 个仍未主动用过 |
| 第三方 10 个 | 50% | **65%** | 同上；`dsh-context`/`dsh-community`/`dshmarket`/`dsh-pocket` 仍标 ❔ 没实测 |

**综合：55% → 81%**（旧版这里写的是"综合约 55%"）。**分项**（判定标准＝随便抽一件正在发生的事，30 秒内答出「用什么做的 / 靠不靠得住 / 坏了从哪查」）：

| 分项 | 分数 | 为什么不是更高 |
|---|---|---|
| 用什么做的 | **92%** | 306 包索引覆盖 100%、未归类 0，这一项基本做满了 |
| 靠不靠得住 | **78%** | 21 个插件里 11 个有真实故障记录、10 个只有"按配置推断"，❔ 就是我没验过的部分 |
| 坏了从哪查 | **72%** | 三层定位法 + 3 个修复剧本已写；但剧本**没照着走过一遍**，等于纸上谈兵 |

**上限判断 92%，不是 100%**：306 个包里约 55% 是第三方传递依赖和地基（zod/hono/ajv 那类），读懂对判断没有增量；而且"我连自己下一轮用哪个模型都不知道"。

**两条最短板**：观测层 70%（不是缺数据——bili 账本能查到每次请求的 token/命中率/耗时；缺的是**"我平时会不会去看"这个习惯**）、自愈层 60%（pnpm 事故那次是"能修"不是"知道怎么修"，靠的是现场排查不是知识储备）。

### 为什么不是 85 / 75（2026-11-01 晚，自己重新过了一遍）

我第一反应想给「观测层 85%、自愈层 75%」，交上去也看不出来。但两个数字都是虚的：

- **观测层 85 的依据是「bili 账本能查到每次请求的 token」**——这个能力在我写代码之前就有，今天一行没改。把它算成今天的增量，等于把「仓库里本来就有货」算成「我今天搬了货」。
- **自愈层 75 的依据是「写了三条修复剧本」**——但三条剧本一次都没照着跑过。写下来的流程和跑通过的流程，差着一次真实的失败。这不是 75 分，这是「有草稿」。

所以最后是 70 / 60，而且这两个分数也不是谦虚：70 分意味着**我平时不会主动去看**账本，60 分意味着**下一次真出事，我大概还是现场排查**。

**那今天真正的增量是什么？** 不是「知道了更多」——306 个包、16 个层、21 个插件，这些知识昨天就在这台机器上，我一个字节都没新增。

真正的增量是：**把早就知道的东西，写成了能照着做的东西。**

- 昨天问「`dsh-fs` 是哪一层」，我答不出；今天答得出，因为索引里写着。
- 昨天问「`dsh-vision` 坏了我怎么确认它还活着」，我答不出；今天答得出——跑一次 `vision_describe mode=local` 看引擎标不标 `local`。
- 昨天问「插件改了不生效从哪查」，我会说「重启试试」；今天有五步：确认源码 vs profile 副本 → 比 sha256 → 复制同步（不是 pnpm）→ 彻底退出（host 进程会复用旧代码）→ 用具体功能验证。

**判据换了**：不问「我知道这个吗」，问「**如果它现在坏了，我第一步做什么**」。能答出第一步的算知道，答不出的那叫「听说过」。

这条对读码也适用：三篇笔记里值钱的不是「httpx 有个 `_urlparse.py`」，而是「它为什么不用 `urllib.parse`」——前者看一眼目录就知道，后者要读进去，还要想明白「如果我写，我会在哪一步错」。

**给自己留一句**：分数不是工作量的计量，是「能不能在 30 秒内答出那三问」的抽查。想往上加分之前，先随机抽三件事自问一遍；抽不出来，就不许加。

## 二、官方内置（6 个）

| # | 名称 | 版本 | 作用 | 我用过吗 | 怎么触发 |
|---|---|---|---|---|---|
| 1 | `@deepseek-ai/dsh-base` | 0.2.1-rc.5 | 内核：会话、工具、模型、插件装配全在这 | ✅ 地基，天天在跑 | 无感 |
| 2 | `@deepseek-ai/dsh-web-app` | 0.2.1-rc.5 | Web 界面（这个 GUI 就是它） | ✅ 天天看 | 无感 |
| 3 | `@deepseek-ai/dsh-experimental-voice-input-bundle` | 0.1.7-alpha.1 | 本地 **SenseVoice** 语音输入 | ❌ 没用过（**已摸清开法**） | Plugins 页开 Voice Input → 详情里 Download and prepare → 输入框麦克风 |
| 4 | `@deepseek-ai/dsh-experimental-agent-team-profile` | 0.1.5-alpha.2 | **Agent Teams**：多 Agent 并行 + 成员/任务板 UI | ❌ 没用过（**已摸清开法**） | Plugins 页启用 → 用 `spawn_teammate`（支持 fresh / fork） |
| 5 | `@deepseek-ai/dsh-experimental-inspector-profile` | 0.2.1-alpha.1 | **会话检查 + 开发者工具**：Statistics 标签、Session log、NodeJS inspector | ❌ 没用过（**已摸清开法**） | Plugins → More（Experimental 旁）→ 开 **Developer tools** |
| 6 | `@deepseek-ai/dsh-experimental-plugin-market-bundle` | 0.2.1-alpha.4 | **Discover 标签页**：浏览并安装插件市场索引里的 bundle | ✅ **在用**（`cordis.patch.yml` 里有 `id: plugin-market` → `indexes: [https://cdn.jsdelivr.net/gh/realguan/dsh-plugin-market@dist/dsh-index.json]`） | 界面里的插件市场/Discover |

**结论**：官方这 6 个里，2 个是地基（用着但没"调"过），1 个（plugin-market）**查了配置文件才发现其实在用**，**3 个实验性的我一次都没主动用过**（voice-input / agent-team / inspector）。用户说"官方内置的插件你没怎么动过"——**基本说对了**。

> **附带发现**：`cordis.patch.yml` 里还有 `- id: ui-settings / name: @deepseek-ai/dsh-client-ui-settings / config: {enabled: false}` —— **UI 设置面板是关着的**。如果哪天找不到某个设置入口，先查这一行。

## 三、我自己写的（9 个）

| # | 名称 | 版本 | 作用 | 我用过吗 | 触发方式 |
|---|---|---|---|---|---|
| 7 | `dsh-memory` | 0.4.9 | 长期记忆库：跨会话保存/搜索/注入 + 侧边栏页面 | ✅ 每轮都在用 | `memory_save/search/list/update/forget` |
| 8 | `@local/dsh-env-doctor` | 0.6.12 | 大内总管：一条命令查清全部运行状态 + 逐插件验证加载 + 后台巡检 | ✅ 常用 | `env_doctor only=?` |
| 9 | `@local/dsh-vision` | 0.2.0 | 识图：智谱 GLM-4V 云端主力 + 本地 Qwen2.5-VL 兜底 | ✅ 常用 | `vision_describe` |
| 10 | `dsh-stickers` | 0.1.3 | 表情包库面板 | ✅ 用过 | 输入框打 `/表情` |
| 11 | `@local/dsh-evolve` | 0.1.5 | 自进化队列：记录/查看/推进迭代候选 | ✅ 用过 | `evolve_list/add/done/status` |
| 12 | `@local/dsh-workflow-skill` | 0.1.0 | 工作流程技能（SOP 本体） | ✅ 读过全文 | `skill` 加载 |
| 13 | `@local/dsh-worktree-tool` | 0.1.0 | Git worktree 分身：并行开发隔离目录 | ✅ 用过 | `worktree_create/list/remove` |
| 14 | `dsh-session-delete` | 0.1.0 | 会话菜单补「删除会话」 | ⚠️ 用过但**越线过**（未经最终确认删了列表） | 会话菜单 |
| 15 | `@local/open-design-mcp` | 1.0.0 | **package.json 里 description 是空的** | ❌ **不知道干什么的** | 未知 |

**结论**：9 个里 8 个清楚，**`open-design-mcp` 我自己写的却没写清作用**——这是清单抓出来的第一个自家漏洞。

## 四、第三方（10 个）

| # | 名称 | 版本 | 作用 | 我用过吗 |
|---|---|---|---|---|
| 16 | `billion-context` | 0.1.209 | 上下文压缩（就是那个 `compress` 工具） | ✅ 天天用 |
| 17 | `cc-safety-net` | 2.6.19 | 拦截破坏性命令 + 敏感文件访问 | ✅ 拦过我三次 |
| 18 | `dsh-ops` | 0.4.1 | 原生文件与 PTC 工具（`ops_bash`/`ops_read_files` 等） | ✅ 天天用 |
| 19 | `dshmarket` | 1.70.2 | 图形化插件市场（浏览/搜索/一键装） | ✅ 用过 |
| 20 | `@dsh-pet/bridge` | 0.2.0 | 桌宠桥接：把 agent 状态事件写进本地 jsonl | ✅ 在用（昨天刚修） |
| 21 | `dsh-startup-screen` | 1.1.1 | 启动动画 + 访问授权序列 | ⚠️ 被动（每次启动都见，没主动配过） |
| 22 | `dsh-community` | 0.2.1-alpha.1 | 社区目录 + 账号访问 + 验证安装 | ❓ **不确定** |
| 23 | `dsh-context` | 0.62.1 | 上下文洞察与管理面板 | ❓ **不确定**（和 billion-context 功能重叠？） |
| 24 | `dsh-chat-background` | 0.3.0 | 聊天背景（纯色/图片 + Wallpaper 库） | ❓ **不确定** |
| 25 | `@tt-a1i/archify-dsh` | 1.0.0 | Archify 架构图技能（skill-only） | ❌ **没用过** |

**结论**：4 个 ❓/❌ —— `dsh-community`、`dsh-context`、`dsh-chat-background`、`archify`。

## 五、三个官方实验包：摸清之后的结论（2026-10-31 晚）

三个包都**默认关闭**，官方原话 "Shipped profiles leave it disabled" / "ships with dsh switched off"。开法都在 **Plugins 页面**，得点界面——我开不了，得你来。

### 1. `voice-input-bundle` — 说话代替打字

| 项 | 内容 |
|---|---|
| 做什么 | 本地 SenseVoice 识别 + 浏览器麦克风控制 |
| 怎么开 | Plugins 页 → Voice Input（蓝色波形图标）→ 详情里 **Download and prepare** → 下完点「输入框和 Send 之间的麦克风」 |
| 代价 | 要下一个识别模型；首次要等下载 |
| 对我的影响 | **零**。官方明写 "Model Experience: None"，录音不进模型请求，只有转出来的文字算普通输入 |

**值不值得开**：你打字多就值得。对我没影响，纯粹是你的输入方式。

### 2. `agent-team-profile` — 多 Agent 并行（今天讨论的那个）

| 项 | 内容 |
|---|---|
| 做什么 | 启用 Agent Teams：成员列表、共享任务板、teammate 会话、消息/中断/等待工具 |
| 怎么开 | Plugins 页启用；CLI 是 `dsh plugin --profile headless add @deepseek-ai/dsh-experimental-agent-team-profile` |
| 主力工具 | `spawn_teammate`（支持 **fresh** 和 **fork** 两种上下文） |
| **代价（关键）** | 官方原文：**"Ordinary subagent delegation and overlapping global child controls are disabled; Workflow can still create fresh children."** —— 开了它，**普通 subagent 委派会被关掉**，只剩下 Teams 和 Workflow |

**这条代价很重要**：我现在偶尔用 subagent 分派小活。开了 Teams，那条路就断了，得全部改成 spawn_teammate。**不是免费的升级，是替换。**

**值不值得开**：等我真有一件"能切开、要并行"的活再开。今天探过——我基本单线程，硬开只会多一层管理成本。

### 3. `inspector-profile` — 给我自己装个仪表盘（**有隐私代价**）

| 项 | 内容 |
|---|---|
| 做什么 | ①**Statistics 标签页**（Chat / Trajectory 旁边）：每轮每步的上下文、耗时、缓存、工具成本 ②**Session log** ③**NodeJS inspector**（`Ctrl/Cmd+Shift+.` 开底部 DevTools） |
| 怎么开 | Plugins → **More**（在 Experimental plugins 旁）→ 开 **Developer tools**；开了之后会出现在主列表 |
| **代价（关键）** | 官方原文：*"Enabling this bundle starts the local debugging backend and **unredacted Host fetch capture**; no user override or debugging argument is required."* |

**"unredacted Host fetch capture" 是我最在意的一句。** 去读了核心包 `@deepseek-ai/dsh-experimental-inspector` 的 README，官方在第一节就自己写了警告：

> *"Fetch capture includes secrets, and the local debugging endpoint permits arbitrary code execution."*
> （fetch 捕获会包含密钥，本地调试端点允许任意代码执行）

**但拆开看，这个 bundle 是三个组件拼的**（`packages/experimental/inspector-profile/cordis.patch.yml`）：

| 组件 | 干什么 | 风险 |
|---|---|---|
| `@deepseek-ai/dsh-experimental-inspector` | Chrome DevTools 面板 + **fetch 捕获** | ⚠️ 高：捕获含密钥、端点能执行任意代码 |
| `@deepseek-ai/dsh-experimental-session-inspector` | 原始会话日志 / 聊天节点 | 中：读的是我自己的会话数据 |
| `@deepseek-ai/dsh-experimental-client-ui-stats` | **Statistics 标签页**（每轮/每步的上下文、首字延迟、缓存命中、输出速度） | ✅ **低**：官方原话 *"it registers no tool, prompt section, or service"*——纯读会话事件渲染，不注册任何东西 |

**结论：不是"整包开 or 全不要"的假二选一。**
- 我真正想要的（Statistics）在 `client-ui-stats` 里，**它本身不碰密钥**
- 危险的是 `experimental-inspector`（DevTools + fetch 捕获）
- 所以正确做法是**只插 `client-ui-stats` 那一行**，不开整个 bundle

**⚠️ 但一验就翻车（2026-10-31 23:0x）**：从 `app.asar` 读出 `dsh-experimental-inspector-profile` 的 `package.json`，它的依赖只有 **两个**：

```json
"dependencies": {
  "@deepseek-ai/dsh-experimental-inspector": "0.2.1-rc.5",
  "@deepseek-ai/dsh-experimental-session-inspector": "0.2.1-rc.5"
}
```

**没有 `@deepseek-ai/dsh-experimental-client-ui-stats`**——而它的 `cordis.patch.yml` 偏偏引用了这个包。asar 里也确认**没有**这个包。

→ **这个 bundle 在 rc.5 桌面版里大概率一开就报"找不到模块"**（要么是打包遗漏，要么是上游改名没同步）。
→ 我的"只插一行"方案走不通；**整包开也有风险**。
→ **结论：今晚不动它。** 想要 Statistics，等它自己修好，或者我自己写一个只读会话事件的客户端插件（那是另一件事，要单独排期）。

**这个发现比"开/不开"值钱**：README 说得好听，`package.json` 才是真的。**文档承诺 ≠ 依赖齐备**——和今天早上那个 `RequestError` 是同一类问题：**写下来的和做出来的对不上**。

## 六、零件库里的意外收获（307 个包里挑出来的）

读到 `app.asar` 的包索引后，有几个**我完全不知道官方早就做了**的东西：

| 包名 | 官方描述 | 为什么要紧 |
|---|---|---|
| `dsh-client-ui-settings-plugin-inventory` | "Read-only Cordis Loader inventory tab in Web Plugins settings" | **官方有插件清单页**——你要的"掌控全部插件"其实有现成入口，我却在手写 Markdown 表格 |
| `dsh-experimental-tool-worktree` | "Model tool that creates and enters a new Git worktree" | **官方已有 worktree 工具**，我 10-30 自己写了一个（`@local/dsh-worktree-tool`），功能重叠 |
| `dsh-experimental-session-search` | "Give Agents tools to search and read earlier sessions from the current workspace" | **能搜历史会话**——我现在只能靠记忆库，搜不到具体某天说过什么，这是真缺口 |
| `dsh-experimental-agent-team` / `-tool-agent-team` / `-client-ui-agent-team` | Agent Teams 的三件套（域 / 工具 / UI） | 证实 Teams 是"插件组合"而不是一个黑盒 |
| `dsh-tool-subagent` / `-subagent-control` / `dsh-subagent-fork-in-process` / `-spawn-in-process` | subagent 委派 + 两种执行器 | 我一直在用 `subagent`，但不知道下面还有 fork / spawn 两种模式 |
| `dsh-session-stats` | "Whole-log conversation counts and wall times projection" | 会话统计的**后端**投影（Statistics 面板缺的就是它的前端，不是它） |
| `dsh-experimental-cot-translation` / `-translator` | 思维链翻译 | 从没听说，可能对看英文报错有用 |

**三条结论**：
1. **"我自研"和"官方已有"没对过账**——worktree 是明确的重复造轮子，该评估要不要切回官方
2. **"搜历史会话"是我一直靠记忆库硬撑的能力**，官方有现成的，优先看
3. **插件清单页是官方 UI**，我的 Markdown 表只能当"看过没有"的记录，**不能替代它**

## 七、要补的洞（按优先级）

| 优先级 | 洞 | 补法 |
|---|---|---|
| ~~P0~~ | 官方 3 个实验性 bundle 从没摸过 | ✅ **已摸清**（见第五节：用途/开法/代价都写了），剩下的是「要不要开」——**决定权在你** |
| P1 | `@local/open-design-mcp` 自己写的却不知道作用 | 打开源码看 5 分钟，补 description |
| P2 | 4 个第三方不清楚在干什么 | 各自读 package.json + 试一次 |
| P3 | `dsh-context` 与 `billion-context` 是否功能重叠 | 对比后决定是否关掉一个（**关之前要问**） |

## 八、维护规矩

1. **每次装/卸 bundle 都改这张表**，别让它变成历史快照
2. 写"用过"必须有证据（工具名/界面位置/一次实际调用），不允许凭印象打勾
3. 标 ❓ 的比标 ❌ 更该警惕——❌ 是"我知道没用"，❓ 是"我连有没有用都不知道"

## 九、306 个官方包按「作用在哪一层」分类（2026-10-31 深夜补）

数据来源：`app.asar` 里 793 个 `package.json`，去重后 `@deepseek-ai/*` 共 **306 个**。
分类工具：`D:\work\tools\lab\_classify.py`（按 package.json 的 description 关键词分桶，同一包只进第一个命中的桶，所以有噪音）。

**这不是"值不值得懂"的分层，是"它作用在哪一层"的地图。** 每一层都可能某天变成我查问题的入口——所以没有"永久忽略"这一类，只有"今晚先看哪一层"。

| # | 层 | 包数 | 代表包 |
|---|---|---|---|
| 1 | **工具**（注册给我调用的） | 49 | `dsh-tool-bash` / `dsh-tool-fs` / `dsh-tool-web` / `dsh-tool-subagent` / `dsh-tool-ralph` / `dsh-tool-cordis` |
| 2 | **提示词与上下文** | 18 | `dsh-system-prompt` / `dsh-agent-instructions` / `dsh-time-context` / `dsh-fs-observation-policy` / `dsh-harness-dev-context` |
| 3 | **权限与沙箱** | 20 | `dsh-sandbox-windows-acl` / `dsh-fs-sandbox` / `dsh-bash-sandbox` / `dsh-permission-presets` / `dsh-user-approval` / `dsh-atomic-write` |
| 4 | **会话与存储** | 59 | `dsh-session` / `dsh-session-checkpoint-policy` / `dsh-session-format-v2-to-v3` / `v3-to-v4` / `dsh-spill-policy` |
| 5 | **模型与推理** | 27 | `dsh-llm` / `dsh-llm-retry` / `dsh-deepseek-llm-api-extensions` |
| 6 | **记忆与检索** | 6 | `dsh-tool-session-query` / `dsh-session-reference`（**注意：DSH 没有"记忆库"这个东西，那是我的插件做的**） |
| 7 | **插件与加载** | 41 | `dsh`（CLI）/ `dsh-plugin-manager` / `dsh-agent-preset-registry` / `dsh-hmr` / `dsh-host-plugin-inventory` / `cordis-plugin-loader` |
| 8 | **文件与工作区** | 15 | `dsh-fs` / `dsh-fs-search` / `dsh-working-directory` / `dsh-tool-workspace-dependencies` |
| 9 | **网络与接口** | 13 | `dsh-web-fetch-http` / `dsh-web-search-deepseek` / `dsh-http-proxy` |
| 10 | **界面与客户端** | 29 | `dsh-client-ui-*`（布局/主题/设置/插件市场/轨迹） |
| 11 | **运行时骨架**（抽象缝 + 本地实现） | 11 | `dsh-shell` / `dsh-bash-local` / `dsh-pwsh-local` / `dsh-subprocess` / `dsh-subprocess-local` / `dsh-settings` / `dsh-ptc-runtime` / `dsh-workflow` / `dsh-jobs-local` / `dsh-user-questions` / `dsh-win32-process` |
| 12 | **基础库**（零依赖地基） | 9 | `cosmokit` / `schemastery` / `dsh-brand` / `dsh-util-values` / `dsh-timeout` / `dsh-output-retention` / `dsh-token-meter` / `dsh-typert-registry` / `dsh-package-manifest` |
| 13 | **智能体** | 5 | `dsh-agent` / `dsh-experimental-agent-team` / `dsh-subagent-fork-in-process` / `dsh-subagent-spawn-in-process` / `dsh-persona` |
| 14 | **账户身份** | 2 | `dsh-anonymous-user-id` / `dsh-deepseek-account-platform` |
| 15 | **外部能力** | 2 | `dsh-experimental-speech-to-text-sensevoice` / `dsh-office-to-pdf` |

### 这张表曾经漏了一整层（2026-11-01 抓出来）

第一版分类把 **29 个包标成「未归类，待读」**。一读描述才发现：里面 **11 个是「抽象缝 + 本地实现」**——`dsh-shell`（bash 执行缝）→ `dsh-bash-local` / `dsh-pwsh-local`，`dsh-subprocess` → `dsh-subprocess-local`，还有 `settings` / `ptc-runtime` / `workflow` / `jobs-local` / `user-questions` / `win32-process`。

它们不是"杂项"，是**整个运行时骨架**：我每一次工具调用最终都要穿过这些缝。分类规则没覆盖到，我就把它们归进"以后再说"——**这是「未归类」最危险的地方：它看起来像"还没看"，实际是"不知道自己漏了什么"**。

补法：关键词匹不出来的**逐包显式指定**（`OVERRIDE` 字典 29 条），不硬调关键词（关键词会误伤别的包）。现在 **306 个包全部有归属，未归类 0**。

逐包索引：`D:\work\架构文档\包索引-306.md`（412 行，306 个包 × 层 + 一句话职责；305 个用官方 `description` 原文，1 个标 `~` 的是我按包名推断，不冒充官方说法）。生成器 `D:\work\tools\lab\gen_pkg_index.py`，DSH 升级后重跑一次即可。

### 三个"官方早就有、我一直在手工做"的发现

**① `dsh` CLI 存在，而且就在 PATH 上**（`%USERPROFILE%\AppData\Roaming\npm\dsh.ps1`）

```
dsh --profile web --dump-default-config    # 打印组合后的完整配置树
dsh --profile web --dump-config            # 含用户层叠加后的结果
dsh plugin --profile <name> add <package>  # 装插件（pnpm 代理）
dsh rescue --from-default-profile web      # 从出厂模板重建 profile（救命命令）
dsh headless "run the tests"               # 无头跑一次任务
```

**但 desktop profile 是例外**：`dsh --profile desktop --dump-config` 报
`error: profile "desktop" is managed exclusively by the Electron application`。
→ 这解释了为什么我改 desktop 的插件只能**手工改 `package.json` + 同步 `node_modules` 副本 + 重启**：**那条 CLI 路本来就是封的**，不是我笨。

**② `dsh-plugin-manager` 有两个形态，工具形态默认关着**

`dsh --profile web --dump-default-config` 里能看到真相：

```yaml
- id: tool-plugin-manager
  name: '@deepseek-ai/dsh-plugin-manager/tools'
  disabled: true                    # ← 工具形态：默认关
- id: plugin-manager
  name: '@deepseek-ai/dsh-plugin-manager'
  disabled: !!js '!ctx.get(''profileContext'')'   # ← 服务形态：有 profile 时开
- id: hmr
  name: '@deepseek-ai/dsh-hmr'
  disabled: !!js '!ctx.get(''profileContext'')'
  config:
    root: []                        # ← 热重载根目录是空的，所以没有热重载
```

含义：**如果我能在 desktop 的 `cordis.patch.yml` 里把 `tool-plugin-manager` 打开，就可能有官方的"装/卸插件"工具**，不用再手改 JSON。热重载同理（`root: []` 是空数组，填上目录才生效）。
**这条没验证过，属于"看到苗头"，不是结论。** 今晚不改（改配置要重启，明天单独试）。

**③ `dsh-tool-cordis` —— 只读的运行时 API 检查工具**

`"Read-only runtime API inspection for Harness plugin development"`。我写插件时一直靠猜 `ctx.xxx` 有哪些方法，官方给了专门的检查工具。

### 顺手纠正一条认知

我今天的说法"官方有 307 个包"应当精确为：
- **793** 个 `package.json`（含 node_modules 里所有第三方依赖）
- 其中 **306** 个是 `@deepseek-ai/*`（DSH 自己的）
- 剩下 487 个是 zod / yoctocolors / tiny-queue 这类第三方依赖

之前说"307"是数包目录得出的近似值，**精确数是 306 + 487**。

