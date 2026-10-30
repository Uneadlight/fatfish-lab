# dsh-env-doctor 变更日志

## v0.6.12（2026-10-30）记忆巡检阈值跟着 60,000 预算重算

- 背景：2026-10-29 用户把记忆注入预算从 30,000 翻到 **60,000 字符**（4/5 保底 12,000 → 20,000），但本插件的四项巡检阈值还停在旧档，导致两种错报方向：①5/5 报警线 20,000 太紧（实际 37 条 / 18,466 字符，再长几百字就天天 WARN）；②总字符 45,000 / 估算注入 32,000 也按旧预算设的，翻倍后会把"正常"报成"该净化了"。
- 改动（四个常量按新预算重定，比例不变）：
  | 常量 | 旧 | 新 | 依据 |
  |---|---|---|---|
  | `LIMIT_FIVE_CHARS` | 20,000 | **24,000** | 预算 40%（原 30,000×2/3=20,000 是同一思路，但 2/3 太紧，改成 40% 留出正常增长） |
  | `LIMIT_INJECT_EST` | 32,000 | **48,000** | 预算 80% 报警线 |
  | `LIMIT_CHARS` | 45,000 | **90,000** | 正文总量随预算翻倍 |
  | `LIMIT_FIVES` / `LIMIT_FOURS` / `LIMIT_COUNT` | 40 / 60 / 150 | 不变 | 条数不是成本主因，没动 |
- 同步把 `D:\work\自进化\记忆库优化规则.md` 与 `D:\work\大肥鱼系统架构.md` 里的旧数字（30,000/12,000/≤32,000）改成新口径——SSOT 审计的 `stale_params` 会把文档与代码不一致报出来，这次就是它报的。
- 验证：`node --check` 通过；三套项目测试无影响（29+51+71）；SSOT 审计重跑 `stale_params 0`；src 与 profile 副本 SHA256 `A7D8ECFF597F3D382B2AD8A2220A34BE03E34D3F878F725D730F9DAA8CD0D559` 一致；版本 0.6.11 → 0.6.12。
- 边界：改的是"什么时候提醒"，不是"提醒了怎么办"。真要净化仍按 `记忆库优化规则.md` 的分层阈值走。

## v0.6.11（2026-10-30）停用任务的告警降噪（用户主动停 ≠ 故障）

- 背景：每轮系统提示固定挂着 4 条 WARN，全是用户主动停掉的任务（`DSH-Auto-Learn` / `DSH-Closure-Loop` / `DSH-Metric-W0`），其中 `DSH-Auto-Learn` 因为 `checkTasks` 和 `checkAutoLearn` 各报一次而重复出现两次。这属于噪音：天天报同一件已知的事，既不解决问题，还会让"有告警要处理"变成假压力（真出故障时反而没人细看）。
- 改动 1（数据驱动白名单）：新增 `D:\work\自进化\task-expectations.json` → `{"expectedDisabled": {"任务名": "原因"}}`。只有「在清单里 + 状态 Disabled」才静音；**不在清单里的任务被禁用照样报 WARN**（宁吵勿漏）。文件不存在或解析失败 = 什么都不静音（fail-open）。
- 改动 2（合并成一行）：静音的任务不再逐条报，改为末尾一行 `[INFO] 已停用的计划任务 N 个（用户主动，不算故障）`，detail 里带每条的停用原因与恢复命令；`only=tasks` 仍逐条给出明细。
- 改动 3（去重）：`checkAutoLearn` 遇到已知停用的任务直接返回（不再重复报第二遍），该项由 `checkTasks` 的汇总行统一负责。
- 验证：`node --check` 通过；`only=tasks` 与 `only=automation` 实跑；`selftest.mjs all` 通过；src 与 profile 副本 SHA256 `20262ED0E1AA623486178455E6375134F0A3C2ED35F12A0A8B15D3CE27061B06` 一致；版本 0.6.10 → 0.6.11。
- 边界：这只改"报不报"，不改"任务为什么停"。真要恢复某任务，改 json 或 `schtasks /Change /ENABLE` 后告警会自然按新状态走。

## v0.6.10（2026-10-29）修 only=ssot 报告路径中文乱码

- 现象（用户重启后首跑实测）：`only=ssot` 各项数字都对，但报告路径里的中文段全变成方块问号字符。
- 根因：Python 在 Windows 上**重定向 stdout 时默认用系统代码页（GBK）**，而插件按 `utf8` 解码 → 中文路径变乱码。数字是 ASCII 所以没受影响。
- 改动：`checkSsotAudit` 的 `execFileSync` 传 `env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" }`；再加一层兜底——路径里出现替换字符就改为列 `audit/` 目录取最新 `.md`。
- 验证：harness 实跑输出 `报告 D:\work\自进化\audit\ssot-20261029-175352.md`（中文正常）；`node --check` 通过；源码与 profile 副本已同步。

## v0.6.9（2026-10-29）新增 only=ssot 数据腐化审计入口 + 修 OCR 假阳性

- 背景：`D:\work\自进化\audit_ssot.py`（当日新写）能查"文档里的参数 vs 代码真值、知识库索引、依赖声明、死代码/死链、残留文件/僵尸进程"，但入口分散；同时发现本插件的 RapidOCR 检查是**假阳性**——只查 `tools\ocr-venv` 目录存在就报 `[OK] venv 可用`，实际那里只有 pip/setuptools，`rapidocr_onnxruntime` 根本 import 不到。
- 改动 1（新能力）：`only=ssot` 转调审计脚本，按本插件统一格式输出——真腐化（参数漂移/索引幽灵/越界引用/僵尸进程）报 WARN，候选类（未声明依赖/疑似死代码/死链/残留）报 INFO，全 0 时报 `[OK] 无真腐化`。**不并进 `only=all`**：理由三条写进代码注释（职能不同、耗时 0.5s vs 55s、失败隔离）。
- 改动 2（修假阳性）：`checkLocalTools` 的 RapidOCR 从"目录存在"改为**真 `import rapidocr_onnxruntime` 探测**；候选顺序 `tools\ocr-venv312` → `tools\ocr-venv`（懒探测，第一个通了就停），版本号用 `importlib.metadata` 取。
  - 连带查清：py3.10 的 `ocr-venv` 里 `import onnxruntime` 报 `DLL load failed while importing onnxruntime_pybind11_state`，重建 py3.12 的 `ocr-venv312` 后正常（onnxruntime 1.31.1，rapidocr 1.4.4，236 MB）。
  - 细节：探测子进程必须给 `stdio: ["ignore","pipe","pipe"]`，否则 execFileSync 会把失败 venv 的整段 traceback 漏进巡检输出。
- 改动 3（防呆）：新增未知 `only` 拦截（`KNOWN_ONLY` Set）→ `[FAIL] 未知的 only=xxx` + 可用值清单。起因是实测旧代码下 `only=ssot` 静默返回「0 项 / 全部通过」，会把参数写错伪装成体检正常。
- 边界：审计逻辑仍住在 `audit_ssot.py`，本插件只做入口/格式化，不改它；审计产物落 `D:\work\自进化\audit\ssot-<stamp>.md|.json`。
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

- **`checkMemories()` 增加阈值提醒**：条数 > 80 或正文 > 28,000 字符时，返回 WARN「记忆库该净化了（触发自我优化前提）」，`fix` 指向 `D:\work\自进化\记忆库优化规则.md`。
- 为什么：用户要求"不用时时刻刻注意记忆库，觉得太多/效率不够时再优化"——把"该察觉到"这件事交给巡检，而不是靠我记着。
- 当前状态：61 条 / 21,540 字符，低于阈值，不会误报。
- 验证：`node --check` ✅；`selftest.mjs` 全部通过（8 条提示）。

## 历史（摘要）

- v0.6.3：修复桌面自带 bundle（dsh-community-market）被误报为孤儿。
- v0.6.2：Ollama 未运行/本地模型未装降级为 INFO（按需启动）。
- v0.6.1：新增客户端 bundle 一致性检查（exports["./client"] 与 ModuleLoader id = 包名）。
- v0.6.0：插件变更追踪（基线快照）、自研插件目录动态扫描（@local）。
- v0.5.x：模块化拆分、提示词优化、时区处理、巡检性能。
