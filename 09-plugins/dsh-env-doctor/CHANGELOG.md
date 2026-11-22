# dsh-env-doctor 变更日志

## v0.6.24（2026-11-22）新增「ComfyUI 本地生图服务」检查项：生图链路也是本地工具链的一环

- 背景：候选 `ev-1795251758036`。本机 ComfyUI 是本地生图（SDXL/LoRA/表情包/放大）的唯一入口，但此前巡检只查 Ollama / RapidOCR / ffmpeg，ComfyUI 坏了要等真正要生图时才发现。2026-11-21 那轮修 ComfyUI（torch 矩阵 + 4 组补丁）就是「没有检查项 → 坏了一整天才发现」的实例。
- 改法：`checkLocalTools()` 里 Ollama 之后插入「2.5) ComfyUI 本地生图服务」——①`WORKSPACE_DIR/ComfyUI` 目录存在；②`curl http://127.0.0.1:8188/system_stats` 探服务（`--max-time 4`），在线报 OK 并从 `"comfyui_version"` 取版本，不在线报 INFO「未启动（按需启动）」、fix 指向 `知识库\绘图\03-ComfyUI-GPU环境修复.md`。**故意不在这里 import torch 探 CUDA**：那要 5-15 秒，会把 `only=all` 拖慢；「服务能起」本身就是 torch 2.6.0+cu124 + comfy_kitchen 补丁整条链路通的证据。
- 验证：`node --check index.js` → `SYNTAX OK`；`python -c "import json;json.load(open('package.json'))"` → OK；`node selftest.mjs all` → 见运行记录。**需重启 DSH 生效**（`link:` 安装，进程内是启动时 import 的旧模块）。
- 判据：**巡检只查「能不能发现」，不查「跑得动跑不动」**——重探测（torch / 模型加载）留给真正要用的时候；巡检的价值是「坏了能第一时间看见」，不是「每次体检都跑一遍全量基准」。

## v0.6.23（2026-11-20）记忆库阈值翻倍：用户 m05927「阈值有点低…都翻倍一下…提高到一个以后很长时间都不用理他的一个上线」

- 背景：巡检报「记忆库该净化了」两条——5/5 字符 64,996 > 26,000、总条数 288 > 260。用户认为阈值太低，要求提到「长期不用理」的程度（不是靠降重要性让告警消失）。
- 改法：`LIMIT_FIVE_CHARS` 48,000 → **90,000**（对齐 `mem-maintain.py` 口径，且 90,000 = 120,000 预算的 75%，留 30,000 给 4/5 索引行）；`LIMIT_FIVES` 70 → **140**；`LIMIT_COUNT` 300 → **600**；`LIMIT_CHARS` 300,000 → **600,000**；`LIMIT_INJECT_EST` 保持 **96,000**（80% 预算硬线，不动）。
- 验证：`node --check` 通过；`env_doctor only=all` → 0 项需处理。
- 判据：阈值按「预算比例 + 翻倍」定，不是「让告警消失」；真正决定成本的 injectEst 线保持不动，改的是「近似指标」的宽松度。
## v0.6.22（2026-11-13）巡检告警行删秒级时间戳：`最近巡检 HH:MM:SS` 每 30 分钟重写一次 system prompt

- 背景：`guardSummary()` 经 `systemPrompt.section(order:9)` 进 system prompt。guardTick 每 30 分钟刷新 `guardLastRun` → `fmtTime()` 输出变 → 整份 prompt 字节变 → billion-context 记一次 prompt rewrite（重计费 ~5 万 token）。会话内逐行 diff 实锤：相邻 system/message 的变化行包含这行时间戳（15:17:06 → 下一个值）。
- 改法：删「最近巡检 ${fmtTime(guardLastRun)}」短语，保留「告警 N 条」+ 明细——告警集合本身的变化是必要变化，「什么时候巡检的」由 env_doctor 命令输出里给，不占系统提示。
- 关联：dsh-memory v0.6.17 同日改〔开工检查〕〔工具提示〕两处（三源定罪的另外两源）。用户 m00150「按你的想法修一下吧，能省一点是一点」。
- 验证：`node --check` 通过；`selftest.mjs all` → rc=0（0 项需处理）。**需重启 DSH 生效**（profile 为 link: Junction）。备份 `E:\DS公作区\备份\cache-stable-20261113\doctor-index.js`。

## v0.6.21（2026-11-12）条数/字符线改量 live：`deprecated` 条目不注入，不该算进成本

- 背景：`[巡检]` 长期挂着「记忆库该净化了：总条数 214 > 200」，但同一次输出里的 `[OK] 记忆库正常` 明确写着正文 137,850 字符（上限 150,000）、5/5 18,235 字符（上限 48,000）——**唯一超线的是总条数**。
- 查证：214 条里有 **21 条已废弃**（`deprecated: true`），active 只有 193。`dsh-memory/lib/index.js:367/788/1051` 三处 `if (m.deprecated) continue;` 证明废弃条目**不注入、不进索引、不浮出**，成本为零。
- 误导在哪：`checkMemories()` 的 `count`/`chars` 量的是**全部条目**（含废弃），而 `fiveList`/`fours`/注入估算量的是 `live`——同一函数里两套口径。更矛盾的是 `E:\DS公作区\自进化\记忆库优化规则.md:37` 明确「`deprecated` 优于删除」：**照规则做事（标废弃而不是删）反而把 count 顶高**，等于惩罚照规则走的人。这是本文件第三次「近似指标否定精确指标」（v0.6.19 的 5/5 条数线、v0.6.20 的 4/5 条数线）。
- 改法：①新增 `liveCount` / `liveChars` / `deprecatedCount`；②`count`/`chars` 保留给结构检查与展示（不含废弃的那部分改在 detail 里单列）；③两条 reasons 改成 `liveCount > LIMIT_COUNT`、`liveChars > LIMIT_CHARS`；④detail 里把废弃条数显式标出来（`193 条活跃 · 另 21 条已废弃 · …`），**透明比隐藏好**——不是装作那 21 条不存在。
- 验证：抽 `checkMemories()` 到独立进程实跑 → 单条 `{level:"OK", detail:"193 条活跃 · 另 21 条已废弃 · 5/5:25 · 4/5:127 · 237.3 KB · 正文 126956 字符 · 5/5 18235 字符"}`，WARN 消失；`node --check` 通过。**要重启 DSH 才生效**（`link:` 安装，进程内是启动时 import 的旧模块）。
- 判据：**改口径不是调阈值**——阈值回答「多少算多」，口径回答「数谁」。这次一个字都没动 `LIMIT_*`。

## v0.6.20（2026-11-09）4/5 条数线作废：索引化之后它不再度量成本

- 背景：dsh-memory v0.6.15/0.6.16 把 4/5 和 3/5 及以下全部改成**一行索引**（约 80 字符/条），全库注入 87,138 → 26,206 字符（−70%）。但本插件的 `checkMemories()` 仍在报「4/5 已 115 条 > 80」，每次巡检都挂着这条 WARN。
- 误导在哪：①`fourInjectEst = Σ min(500, 正文长度)` 是按 **2026-10 的全文注入**估的，115 条估 57,500，实际索引约 9,085——**高估约 6 倍**；②4/5 条数从此只决定「索引行数」，而行数早就算进字符里了，单独拿条数报警等于**用近似指标否定精确指标**（同 v0.6.19 的 5/5 条数线，同一形状第二次犯）。
- 改法：①删掉 `LIMIT_FOURS = 80` 与 `if (fours > LIMIT_FOURS)` 这条判断；②`fourInjectEst` 从「Σ min(500, len)」改成「4/5 条数 × 80 字符/行」（新常量 `INDEX_LINE_CHARS = 80`）；③注释里写清「字符才是硬指标，条数只是近似」这条判据。
- 验证：`node --check index.js` → `SYNTAX_OK`（改完**要重启 DSH 才生效**——`link:` 安装，进程内是启动时 import 的旧模块）。
- 判据：**检查项度量的对象变了，判据必须跟着变**——条数、字符、行数，哪个才是成本的直接来源，就量哪个。

## v0.6.19（2026-11-07）两条常驻误报：禁用任务认不出、记忆库条数线过紧

- 背景：`[巡检]` 长期挂着「计划任务已禁用：DSH-EnvDoctor-Iterate / DSH-Memory-Daily-Check / DSH-Memory-Weekly-Iterate」三条 WARN，但它们是 11-07「去繁就简」**我主动停的**，不是故障；同时「记忆库该净化了」报「5/5 已 51 条 > 50」，而 5/5 实测只有 **37,215 字符**（远低于 48,000 字符线）。
- 误导在哪：①三条 WARN 让每次巡检看起来「有 3 个东西坏了」，实际是**我自己关的**——不知道背景的人（包括未来的我）会去查这三个任务；②条数判据与 `E:\DS公作区\自进化\记忆库优化规则.md` 的「**字符才是硬指标，条数只是近似**」直接冲突，等于用近似指标否定精确指标。
- 改法：①**只改数据不改代码**——`checkTasks`（index.js:1277-1287）早就写了 `expectedDisabled(name)` 分支，是 `E:\DS公作区\自进化\task-expectations.json` 里没有这 3 个任务才走 WARN。补 5 条（3 个停用 + 2 个已删），每条写清「为什么停/删」——**没有理由的例外清单半年后没人知道该不该恢复**。②`LIMIT_FIVES` 50 → 60：60 条 × 800 字符 ≈ 48,000，正好对齐字符线。
- 顺手清掉 `.guard-alerts.json` 里 7 条陈旧快照（备份 `.guard-alerts.json.bak-20261107`，2,364 B）——其中 3 条对应已删除的任务，永远不可能再被重算。
- 验证：`node --check` → SYNTAX OK；`selftest.mjs all` → **0 项需处理、1 项注意、3 条提示**（改前 5 项注意）；`env_doctor only=tasks` → 3 个禁用任务全部降成 `[INFO] 计划任务已停用（已知）` 并带停用原因，总判「全部通过（5 条提示）」。
- 判据：**「用户主动做的事」和「系统故障」必须在同一份输出里能分开**——否则主动精简会被自己的巡检当成故障，然后你会去修一个本来就是对的东西。例外清单必须带理由，否则它会从「白名单」退化成「垃圾桶」。

## v0.6.18（2026-11-05）OpenDesign 检查改成「装了才查」

- 背景：`open-design-mcp` 插件 2026-11-05 已卸载（MCP server 从没连上、0 使用），但 env_doctor 的检查是**硬编码的**——`index.js` 里只探测 OD daemon 端口 63256，跟插件装没装无关，于是每次巡检都报一条 `OpenDesign MCP：OD 未启动 → open_design MCP 断开`。
- 误导在哪：这条带着「MCP 断开」字样，看起来像某个还在的插件坏了，实际那个插件已经不存在了。排查时会白花时间（今晚就白查了一轮）。
- 改法：先读 `PROFILE_PKG`（profile 的 `package.json`）的 `dsh.profile.bundles`，只有列表里有 `open-design` 字样才做端口探测；否则整段跳过，不产出任何 check 项。
- 验证：`selftest.mjs all` → 0 项需处理、1 项注意、**3 条提示**（原来 5 条，少了 OpenDesign 和插件变更追踪）。
- 判据：**检查项要跟着被检查对象的生命周期走**——对象没了，检查项要跟着消失，不能悬空。

## v0.6.17（2026-11-04）记忆巡检阈值对齐 120,000 预算（修误报）

- 背景：2026-11-04 22:58 巡检报「记忆库该净化了」，但同期 `mem-maintain.py` 的报告说「全部 OK：注入 44.2%、没有命中任何触发线」。两边矛盾，去查判据——`index.js` 里还是 60,000 预算时代的数（5/5 ≤24,000、4/5 ≤60 条、估算注入 ≤48,000、总字符 ≤90,000）。dsh-memory 0.5.0 起预算已到 **120,000**（报警线 80% = 96,000），阈值没跟着走，就会挂着永久误报。
- 实测定位真凶不是估算注入（47,038 < 48,000），是 **4/5 条数瞬时 61 > 60** 触发的。
- 改动：`LIMIT_FIVE_CHARS` 24,000→48,000、`LIMIT_FIVES` 40→50、`LIMIT_FOURS` 60→80、`LIMIT_COUNT` 150→200、`LIMIT_CHARS` 90,000→150,000、`LIMIT_INJECT_EST` 48,000→96,000；注释写明这是「防失控的粗线」，精确口径仍在 `E:\DS公作区\自进化\mem-maintain.py`，并记下 22:58 那次是 4/5 条数过线。
- 同步：`E:\DS公作区\自进化\记忆库优化规则.md` 的阈值、预算演进、判定标准三处一起改（否则文档和代码又漂移）。
- 验证：`node --check` 通过；用真实 `memories.json` 重算——live 134 / five 34 / four 60 / fiveChars 19,939 / injectEst 47,038 / chars 75,569，新阈值下 0 个越线。
- 注意：本插件是 `link:` 安装，改完**要重启 DSH 才生效**（生效前巡检仍用 0.6.16 的旧阈值）。

## v0.6.16（2026-11-04）新增「源码版本 vs profile 版本不同步」检测

- 背景：2026-11-03 晚上发现 `dsh-evolve` 源码改到 **0.1.6**、profile 里装的还是 **0.1.5**——**11-02 改的代码从没生效过，而我以为生效了**。`checkPluginDrift` 抓不到这种形态：它比的是"这次基线 vs 上次基线"，profile 版本没变，它就报"无变化"。
- 改动：新增 `checkSourceVersionSync()`，遍历已安装插件，对**实体目录**（非符号链接）且有对应源码目录（`E:\DS公作区\<包名去掉 @local/ 前缀>`）的，比 `package.json` 的 version，不一致就报 WARN 并给出同步命令。
- **为什么只查实体目录**：`@local/dsh-env-doctor`、`@local/dsh-vision`、`dsh-memory` 是 `link:` 安装（符号链接，profile 和源码是同一份文件），版本只可能一致；`dsh-evolve`、`dsh-workflow-skill`、`dsh-worktree-tool`、`open-design-mcp`、`dsh-stickers`、`dsh-chat-background` 是实体目录（拷贝），才有不同步风险。
- **为什么不做成"自动同步"**：不同步有两种含义——"我改了但忘了同步"（该同步）和"我故意让 profile 停在旧版"（不该动）。自动同步会抹掉第二种的意图。只报出来，同步与否我做判断。
- 插入位置：`checkPluginDrift()` 之后；在 `only=all` 和 `only=changes` 两处路由都加上。
- 验证：`node --check` 通过；用真实环境跑判据模拟——6 个实体目录插件里 5 个版本一致、`open-design-mcp` 因源码目录在 `open-design-dsh-bundle` 而正确跳过；再把 `dsh-stickers` 的 profile 版本临时改成 0.1.2（源码 0.1.3）→ **抓到不同步**，改回 0.1.3 → 恢复一致。
- 注意：本插件是 `link:` 安装，改完**要重启 DSH 才生效**。

## v0.6.15（2026-11-03）新增「有待生效的插件（需重启 DSH）」检测

- 背景：当天连续装了两个插件（`dsh-fail-guard` 21:25、`dsh-self-guard` 21:38），`only=health` 仍只报「20 个本地插件，20 个能正常加载」——**我没法判断是"没装好"还是"装了没重启"**，只能靠数个数去猜（20 → 21）。这个歧义每次装插件都会出现，猜错的代价是：以为装好了、实际工具和钩子都不在，等用到时才发现。
- 改动：`checkPluginHealth()` 开头算一次本机落盘时间，跟本进程启动时间比：`const startedAt = Date.now() - Math.round(process.uptime() * 1000);`，命中 `statSync(join(PROFILE_DIR,"node_modules",p.name,"package.json")).birthtimeMs > startedAt` 的插件列进一条 WARN，写明是哪几个、什么时候落盘的。
- **为什么用 `birthtime` 不用 `mtime`**（踩过）：从 npm 缓存或压缩包复制的文件会带着上游旧 `mtime`——实测 `dsh-fail-guard` 的 `package.json` mtime 是 **1985-10-26**，按 mtime 判会漏报；只有 `birthtime` 反映"什么时候落到这台机器上"。实测 birthtime 正好命中当天新装的两个，且不误报 `dsh-context`/`billion-context`/`dsh-ops`/`dsh-memory` 等旧插件。
- 插入位置：用 `out.splice(1, 0, ...)` 放在摘要行之后，**不参与 `brokenCount`**——"待重启"不是故障，不该把摘要染成"有 N 个有问题"。
- 验证：`node --check` 通过；用真实 birthtime 跑对照脚本，输出 `dsh-fail-guard(21:25:34)`、`dsh-self-guard(21:38:37)`，其余 20 个不误报。
- 注意：本插件是 `link:` 安装，改完**要重启 DSH 才生效**（生效前行为与 0.6.14 相同）。
- **补丁（同日晚，被自己搞瞎后加的）**：`readJson()` 原来直接 `JSON.parse(readFileSync(path,"utf8"))`，遇到 UTF-8 BOM 就抛 `Unexpected token '\uFEFF'`。2026-11-03 21:46 我用 PowerShell `Set-Content -Encoding UTF8` 改本插件的 `package.json`，**PS 5.1 默认写 BOM**，于是本插件报出自己的 FAIL：「@local/dsh-env-doctor：package.json 不可读」——工具被自己的 BOM 搞瞎了。修法：`const text = readFileSync(path,"utf8"); return JSON.parse(text.charCodeAt(0)===0xfeff ? text.slice(1) : text);`。实测：带 BOM 时旧写法报 `Unexpected token '﻿'`、新写法通过。**这是防御性的**——profile 里 31 个 bundle 任何一个带 BOM 都会让本插件误报 FAIL，而 BOM 往往来自别的工具（我这次就是）。

## v0.6.14（2026-11-02）内置 bundle 不再计入变更追踪 + 任务结果码补全

- 背景：10-31/11-01 守护日志连续两次报「插件变更追踪：检测到变化 — 新增 4：@deepseek-ai/dsh-experimental-...@?」。这 4 个是随 DSH 应用发布的**内置 bundle**（在 app.asar 里），不是 profile 安装的插件；`installedPluginMap` 却把它们按 profile bundle 记进基线，版本解析不到就成了 `@?`，DSH 本体一更新就误报“新增/移除插件”。
- 改动 1：`installedPluginMap` 跳过 `@deepseek-ai/*` 内置 bundle；`checkPluginDrift` 对比旧基线时也忽略这些键，避免升级后首次运行误报“移除 10 个”。`checkPluginDirs`/`checkClientBundles` 早就按“内置不归 profile 管”处理，这次把变更追踪对齐。
- 改动 2：`checkAutomation` 的“已禁用”分支补上 `expectedDisabled()` 白名单，和 `checkTasks`/`checkAutoLearn` 保持一致；用户主动停用的任务不再在 `only=automation` 里单独报 WARN。
- 改动 3：`TASK_RESULT_TEXT` 补 `267014`（被用户终止）与 `2147946720`（被系统拒绝启动，0x800710E0）；自检里 DSH-Ledger-Collect 的告警从裸十六进制变成可读原因，**告警本身保留**（该任务 02:33 后确实没再成功写账本）。
- 改动 4：修正 `checkMemories` 注释里估算注入阈值仍写 32,000 的笔误（代码实际是 48,000）。
- 验证：`node --check` 通过；`selftest.mjs all --no-network` 通过；版本 0.6.13 → 0.6.14。
- 边界：内置 bundle 仍由 `checkClientBundles` 统计（只数不追踪），插件变更追踪现在只覆盖 profile 实际安装的包。

## v0.6.13（2026-11-01）配置漂移判据从 mtime 改成内容哈希

- 背景：2026-11-01 巡检连报两条 `[WARN] 配置已改动，可能没重启`（`package.json` 13:27:51、`cordis.patch.yml` 13:17:43），而 DSH 进程启动于 13:07:37。查下来告警本身是真的（确实没重启），但**这个判据太粗**：它比的是 mtime，只要文件被写过就报警——`git checkout`、`touch`、脚本把同样内容重写一遍都会触发，而这些对运行时毫无影响。
- 改动：`configBaseline` 从存 mtime 改成存 **sha256 前 16 位**；`checkConfigDrift()` 比对哈希，相同就 OK（detail 写「内容哈希与启动时一致」），不同才 WARN，且 detail 带 `base → now` 前 8 位，一眼能看出是不是真变了。
- 判据依据：**配置的属性是内容，不是文件系统的记账**。mtime 只说明「有人碰过这个文件」，哈希才说明「配置到底变没变」。这与「统计指标健康 ≠ 状态健康」是同一条——判据要落在被描述的对象上。
- 边界：哈希只在**进程启动时**捕获一次，所以「改了又改回来」查不出来（内容确实和启动时一致，那也确实不需要重启）。
- 验证：`node --check` 通过；0.6.12 → 0.6.13。

## v0.6.12（2026-10-30）记忆巡检阈值跟着 60,000 预算重算

- 背景：2026-10-29 用户把记忆注入预算从 30,000 翻到 **60,000 字符**（4/5 保底 12,000 → 20,000），但本插件的四项巡检阈值还停在旧档，导致两种错报方向：①5/5 报警线 20,000 太紧（实际 37 条 / 18,466 字符，再长几百字就天天 WARN）；②总字符 45,000 / 估算注入 32,000 也按旧预算设的，翻倍后会把"正常"报成"该净化了"。
- 改动（四个常量按新预算重定，比例不变）：
  | 常量 | 旧 | 新 | 依据 |
  |---|---|---|---|
  | `LIMIT_FIVE_CHARS` | 20,000 | **24,000** | 预算 40%（原 30,000×2/3=20,000 是同一思路，但 2/3 太紧，改成 40% 留出正常增长） |
  | `LIMIT_INJECT_EST` | 32,000 | **48,000** | 预算 80% 报警线 |
  | `LIMIT_CHARS` | 45,000 | **90,000** | 正文总量随预算翻倍 |
  | `LIMIT_FIVES` / `LIMIT_FOURS` / `LIMIT_COUNT` | 40 / 60 / 150 | 不变 | 条数不是成本主因，没动 |
- 同步把 `E:\DS公作区\自进化\记忆库优化规则.md` 与 `E:\DS公作区\大肥鱼系统架构.md` 里的旧数字（30,000/12,000/≤32,000）改成新口径——SSOT 审计的 `stale_params` 会把文档与代码不一致报出来，这次就是它报的。
- 验证：`node --check` 通过；三套项目测试无影响（29+51+71）；SSOT 审计重跑 `stale_params 0`；src 与 profile 副本 SHA256 `A7D8ECFF597F3D382B2AD8A2220A34BE03E34D3F878F725D730F9DAA8CD0D559` 一致；版本 0.6.11 → 0.6.12。
- 边界：改的是"什么时候提醒"，不是"提醒了怎么办"。真要净化仍按 `记忆库优化规则.md` 的分层阈值走。

## v0.6.11（2026-10-30）停用任务的告警降噪（用户主动停 ≠ 故障）

- 背景：每轮系统提示固定挂着 4 条 WARN，全是用户主动停掉的任务（`DSH-Auto-Learn` / `DSH-Closure-Loop` / `DSH-Metric-W0`），其中 `DSH-Auto-Learn` 因为 `checkTasks` 和 `checkAutoLearn` 各报一次而重复出现两次。这属于噪音：天天报同一件已知的事，既不解决问题，还会让"有告警要处理"变成假压力（真出故障时反而没人细看）。
- 改动 1（数据驱动白名单）：新增 `E:\DS公作区\自进化\task-expectations.json` → `{"expectedDisabled": {"任务名": "原因"}}`。只有「在清单里 + 状态 Disabled」才静音；**不在清单里的任务被禁用照样报 WARN**（宁吵勿漏）。文件不存在或解析失败 = 什么都不静音（fail-open）。
- 改动 2（合并成一行）：静音的任务不再逐条报，改为末尾一行 `[INFO] 已停用的计划任务 N 个（用户主动，不算故障）`，detail 里带每条的停用原因与恢复命令；`only=tasks` 仍逐条给出明细。
- 改动 3（去重）：`checkAutoLearn` 遇到已知停用的任务直接返回（不再重复报第二遍），该项由 `checkTasks` 的汇总行统一负责。
- 验证：`node --check` 通过；`only=tasks` 与 `only=automation` 实跑；`selftest.mjs all` 通过；src 与 profile 副本 SHA256 `20262ED0E1AA623486178455E6375134F0A3C2ED35F12A0A8B15D3CE27061B06` 一致；版本 0.6.10 → 0.6.11。
- 边界：这只改"报不报"，不改"任务为什么停"。真要恢复某任务，改 json 或 `schtasks /Change /ENABLE` 后告警会自然按新状态走。

## v0.6.10（2026-10-29）修 only=ssot 报告路径中文乱码

- 现象（用户重启后首跑实测）：`only=ssot` 各项数字都对，但报告路径里的中文段全变成方块问号字符。
- 根因：Python 在 Windows 上**重定向 stdout 时默认用系统代码页（GBK）**，而插件按 `utf8` 解码 → 中文路径变乱码。数字是 ASCII 所以没受影响。
- 改动：`checkSsotAudit` 的 `execFileSync` 传 `env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" }`；再加一层兜底——路径里出现替换字符就改为列 `audit/` 目录取最新 `.md`。
- 验证：harness 实跑输出 `报告 E:\DS公作区\自进化\audit\ssot-20261029-175352.md`（中文正常）；`node --check` 通过；源码与 profile 副本已同步。

## v0.6.9（2026-10-29）新增 only=ssot 数据腐化审计入口 + 修 OCR 假阳性

- 背景：`E:\DS公作区\自进化\audit_ssot.py`（当日新写）能查"文档里的参数 vs 代码真值、知识库索引、依赖声明、死代码/死链、残留文件/僵尸进程"，但入口分散；同时发现本插件的 RapidOCR 检查是**假阳性**——只查 `tools\ocr-venv` 目录存在就报 `[OK] venv 可用`，实际那里只有 pip/setuptools，`rapidocr_onnxruntime` 根本 import 不到。
- 改动 1（新能力）：`only=ssot` 转调审计脚本，按本插件统一格式输出——真腐化（参数漂移/索引幽灵/越界引用/僵尸进程）报 WARN，候选类（未声明依赖/疑似死代码/死链/残留）报 INFO，全 0 时报 `[OK] 无真腐化`。**不并进 `only=all`**：理由三条写进代码注释（职能不同、耗时 0.5s vs 55s、失败隔离）。
- 改动 2（修假阳性）：`checkLocalTools` 的 RapidOCR 从"目录存在"改为**真 `import rapidocr_onnxruntime` 探测**；候选顺序 `tools\ocr-venv312` → `tools\ocr-venv`（懒探测，第一个通了就停），版本号用 `importlib.metadata` 取。
  - 连带查清：py3.10 的 `ocr-venv` 里 `import onnxruntime` 报 `DLL load failed while importing onnxruntime_pybind11_state`，重建 py3.12 的 `ocr-venv312` 后正常（onnxruntime 1.31.1，rapidocr 1.4.4，236 MB）。
  - 细节：探测子进程必须给 `stdio: ["ignore","pipe","pipe"]`，否则 execFileSync 会把失败 venv 的整段 traceback 漏进巡检输出。
- 改动 3（防呆）：新增未知 `only` 拦截（`KNOWN_ONLY` Set）→ `[FAIL] 未知的 only=xxx` + 可用值清单。起因是实测旧代码下 `only=ssot` 静默返回「0 项 / 全部通过」，会把参数写错伪装成体检正常。
- 边界：审计逻辑仍住在 `audit_ssot.py`，本插件只做入口/格式化，不改它；审计产物落 `E:\DS公作区\自进化\audit\ssot-<stamp>.md|.json`。
- 验证：`node --check` 通过；`selftest.mjs all` → 0 项需处理；`only=tools` 报 `[OK] RapidOCR 可用 rapidocr 1.4.4（import 实测通过，用 ocr-venv312）`；自写假 ctx harness 端到端跑 `only=ssot` → 5 项 / 62.8s / 真腐化 0，`only=ssotX` → 正确 FAIL；源码与 profile 副本 SHA256 一致。

## v0.6.8（2026-10-29）记忆库净化阈值跟着新注入预算重算

- 背景：dsh-memory v0.4.6 把注入预算 18,000 → 30,000，5/5 全文注入后线上 5/5 为 13,302 字符。旧阈值 `LIMIT_FIVE_CHARS = 12000` 会因此**永远挂着 WARN**（误报，等于把告警调成背景噪音）。
- 改动（`checkMemories`）：
  - `LIMIT_FIVE_CHARS` 12000 → **20000**（占新预算 2/3）；
  - `LIMIT_FIVES` 32 → **40**（5/5 现 31 条）；
  - 新增 `LIMIT_INJECT_EST = 32000` 与**估算注入量**指标：`5/5 正文 + Σ(4/5 正文, 每人按 ≤500 字符计)`（4/5 超 480 字会被截断，所以按截断后算才接近真实）。
  - 触发原因文字里带上估算值，方便判断是"5/5 太多"还是"4/5 灌水"。
- `LIMIT_FOURS=60 / LIMIT_COUNT=150 / LIMIT_CHARS=45000` 不变。
- 验证：`node --check` 通过；`node selftest.mjs all` → 0 项需处理、**记忆库正常**（不再警告）；版本 0.6.8，源码与 profile 副本同步。

## v0.6.7（2026-10-28）插件风险扫描（只读）

- `only=plugins` 新增 `checkPluginRisk()`，与 `checkPlugins` 并列输出：
  - **安装脚本**：package.json 的 `preinstall/install/postinstall/prepare` 非空 → WARN，带命令原文（安装时会执行，必须让人看见）。
  - **exports 悬空**：`exports` 指向的 `./` 文件不存在 → WARN（包不完整/装坏）。
  - **源码敏感调用**：扫描插件目录 js（跳过 node_modules/dist，最多 40 文件、每个 ≤400KB），命中 `child_process/execSync/spawnSync`、`rmSync/unlinkSync/rmdirSync/rm -rf`、`fetch/https.request/net.connect`、`eval/new Function` → INFO，带 `file:line` 证据（每条最多 3 条，防刷屏）。
- 扫描对象：profile 依赖里 `dsh-*` / `@local/dsh-*` / `@dsh-*` 的包；**只读，不改第三方源码**。
- 备份 `index.js.bak-20261028-risk`；`node --check` 通过。

## v0.6.6（2026-10-27）记忆库阈值改为「字符优先」

- `checkMemories()`：5/5 上限从「条数」改为**字符优先**——`5/5 ≤ 12,000 字符（约 32 条）`，detail 追加 `5/5 N 字符`；保留 4/5 ≤60、总数 ≤150、正文 ≤45,000。
- 背景：5/5 曾 23 条 / 8,957 字符把 9,000 注入预算吃满，4/5 一条都进不来（兜底失效）。用户拍板把 5/5 上限扩到 12,000（边际成本约 ¥1/月）。

## v0.6.4（2026-10-27）记忆库净化触发提醒

- **`checkMemories()` 增加阈值提醒**：条数 > 80 或正文 > 28,000 字符时，返回 WARN「记忆库该净化了（触发自我优化前提）」，`fix` 指向 `E:\DS公作区\自进化\记忆库优化规则.md`。
- 为什么：用户要求"不用时时刻刻注意记忆库，觉得太多/效率不够时再优化"——把"该察觉到"这件事交给巡检，而不是靠我记着。
- 当前状态：61 条 / 21,540 字符，低于阈值，不会误报。
- 验证：`node --check` ✅；`selftest.mjs` 全部通过（8 条提示）。

## 历史（摘要）

- v0.6.3：修复桌面自带 bundle（dsh-community-market）被误报为孤儿。
- v0.6.2：Ollama 未运行/本地模型未装降级为 INFO（按需启动）。
- v0.6.1：新增客户端 bundle 一致性检查（exports["./client"] 与 ModuleLoader id = 包名）。
- v0.6.0：插件变更追踪（基线快照）、自研插件目录动态扫描（@local）。
- v0.5.x：模块化拆分、提示词优化、时区处理、巡检性能。
