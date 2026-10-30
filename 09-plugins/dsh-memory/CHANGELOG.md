# dsh-memory 变更日志

## v0.4.9（2026-10-29）记忆库并发写保护：跨进程锁 + 写前重读合并

- 起因：用户转达的排查方向——多个对话框/进程同时改 `memories.json` 会不会互相覆盖。实测确认**会**。
- **实测证据（同一压力测试，8 进程 × 20 条 = 期望 160 条）**：
  - 改前（`lib/index.js.bak-20261029-133051`，0.4.5 代码）：**只剩 44 条，静默丢了 116 条**，零报错。
  - 改后（v0.4.9）：**160/160 全在，0 丢失**，`conflicts.log` 记录 12 次合并（说明真的撞上了，不是没并发）。
- 根因：每个写操作都是 `loadDb() → 改 → saveDb()` 的 read-modify-write。原子写（tmp+rename）只保证"不会读到半截 JSON"，**不保证不丢更新**——两个进程各自读到同一版，后写的把先写的整条覆盖。
- 两层防护：
  1. **跨进程建议锁** `memories.json.lock`（`openSync(..., "wx")` 抢锁，15ms 退避重试，2s 超时放行，10s 陈旧锁自动清理，进程崩了不会永久锁死）。
  2. **写前比对文件签名**（`mtimeMs:size`，在 `loadDb()` 时记录）：发现盘上那份已不是我们读的那份 → 重读 + **按 id 合并**（同 id 取 `updatedAt` 较新者；盘上有、本次没提的条目**保留**），并把一次合并写进 `memory/conflicts.log`。
- 删除语义：`memory_forget` 会登记 `pendingDeletes`，合并时跳过这些 id —— 否则删除会被"盘上还有"的逻辑复活。
- 单进程正常路径零成本：签名没变就不重读、不合并。
- 新测试 `iterate/test-store-lock.mjs`（11 条）：A 并发 4×5 不丢；B 删除不复活 + 别的进程写的仍在；C 总数自洽 + 锁已释放。
- 全量回归：19 + 6 + 14 + 10 + 31 + 11 全绿；`SELFCHECK OK exports=apply,inject,name`；src 与 profile SHA256 `BF140D5DBB3DA2FF79650E6B6272C638906CBCA89A0148B0881A4C558EDAB7AC` 一致。
- 边界：这是**协作式**保护，防的是"本插件自己的写路径"；外部脚本直接 `writeFileSync` 覆盖整个文件，锁拦不住（但写前签名比对仍能把对方新增的合并回来）。
- 生效条件：**重启 DSH**。

## v0.4.8（2026-10-29）修「仪表盘与物理状态不一致」：三个计数缺陷

- 起因：注入实测 `32,966/60,000（55%）`，尾行却说"另有 **20 条整条缺席**"。55% 占用却挤掉 20 条，物理上不成立。
- **缺陷 1（尾行错算缺席）**：`hiddenMemories = ordered.slice(shown.length)` 把 **3/5 及以下**也算成"缺席"——它们按设计本来就不注入（只有 5/5 与 4/5 参与）。那 20 条不是被预算挤掉，是层级不够。
- **缺陷 2（百分比口径错）**：`memory_save` 用 `注入字符 / CHAR_BUDGET`；真正的准入上限是 `max(CHAR_BUDGET, 5/5 占用 + 4/5 保底)`。5/5 超过预算时上限会跟着涨，旧口径会算出 >100% 却一条没丢。另：分子含表头/尾行固定开销，会让 62,189 字符对 62,080 上限算出越界。
- **缺陷 3（默认值永远取不到，我自己写的）**：`FOURS_MIN_ALLOWANCE` 写成 `env >= 0 ? env : 20000`——未设环境变量时 `Number("")` = 0，`0 >= 0` 成立 → 返回 **0**，默认 20,000 永远取不到。后果：5/5 一旦超过预算，4/5 被静默饿成 0 条。改成 `env > 0`。
- 四处改动：
  1. 抽出 `computeInjection(ordered)` 作**唯一口径**：分别算 5/5（全注入）、4/5（上限内尽量注入）、3/5 及以下（按设计不注入），返回 `report{chars, bodyChars, limit, budget, fives, fours{count,shown,chars,hidden}, belowThreshold, hiddenIds}`。
  2. `renderInjection()` 尾行改成三分法：`5/5 N 条全部注入；4/5 注入 a/b 条；另有 K 条 4/5 因超准入上限（L 字符）整条缺席：id…；另有 M 条 3/5 及以下按设计不注入`。
  3. `memory_save` 改报 `当前注入 X 字符；正文 B/L，P%；准入上限 L = max(预算, 5/5 占用 + 4/5 保底)；4/5 注入 a/b 条…`，百分比 = round(正文/上限)，80% 报警线按新口径。
  4. 新增 `injectionReport()`，缓存里连同 text 一起存 report，避免重复计算。
- 新回归 `iterate/test-injection-counting.mjs`（**31 条断言**，三阶段）：A 基线（三类条数各归各位、尾行不再把 3/5 说成缺席）；B 5/5 撑到 62,314 字符（超裸预算 60,000）→ 上限自动涨到 82,128、4/5 仍不被饿死、百分比 76% 不越界；C 20,000 字的 4/5 塞不下 → 缺席数与真实出现条数一致、上限与仪表盘一致。核心不变式：**仪表盘报的字符数 == 真正注入 prompt 的文本长度**。
- 全量回归：`test-injection 19 + test-injection-budget 6 + test-dedupe-search 14 + test-memory-to-skill 10 + test-injection-counting 31` 全绿；`check-plugin.mjs` → `SELFCHECK OK exports=apply,inject,name`；src 与 profile 副本 SHA256 `53D138BE4B0A3CA5B59A884EBD48EB955183FCD16B5E44472EA7C057DD3ED373` 一致。
- 生效条件：**重启 DSH**（host 缓存插件代码）。

## v0.4.7（2026-10-29）注入语义改为「整条完整、绝不截断」，预算 30,000 → 60,000

- 用户要求（原话）：「我要的就是你注入的每一条记忆都是完整的，不是要你完全注入。」同时「直接扩到6万翻倍」。
- **根因**：`fmtInjected()` 会把超过 480 字的 4/5 截成 `前 480 字…（详情 memory_search）`——实测 8 行被切。这不是容量不够，是程序主动截断：当时全库正文才 33,800 字符。
- 三处改动：
  1. `fmtInjected()` **不再截断**：一律整条全文；`SNIPPET_CHARS` 保留常量但不再参与截断。
  2. `renderInjection()`：装不下时**整条缺席**（不是局部截断），尾行写明「另有 N 条整条缺席（不是截断）：id 列表，memory_search 可查全文」——缺席可见、可检索。
  3. `CHAR_BUDGET` 默认 **30,000 → 60,000**；`FOURS_MIN_ALLOWANCE` **12,000 → 20,000**。
- 另：`memory_save` 返回值附带**实时注入占用**（`当前注入 31,180/60000 字符，52%`），≥80% 时警告，不用等定时体检。
- 实测（`measure-injection.mjs`，线上库渲染）：注入 **31,180 字符**、活跃 84 条（5/5 31、4/5 33）、**4/5 33/33 全进**、**被截断的行 0**、5/5 零截断。
- 语义保证：**在场 = 完整原文；缺席 = 明确报数 + 可检索**，不再有"半条"。
- 备份 `lib/index.js.bak-20261029-nosnippet`；`node --check` 通过；需重启 DSH 生效（host 进程会缓存插件代码）。

## v0.4.6（2026-10-29）注入预算 18,000 → 30,000，并给 4/5 加保底

- 用户要求"把记忆库本身动一下、扩一下注入量"。按数据定档，不拍脑袋：
  - 线上库实测：**5/5 = 31 条 / 16,300 字符**（v0.4.5 起全文注入）；4/5 = 28 条 / 约 11,599 字符。
  - 旧预算 18,000 下实测 **4/5 只挤进去 4/28 条**（`measure-injection.mjs` 对照跑出来的）。
- 三处改动：
  1. `CHAR_BUDGET` 默认 **18,000 → 30,000**（`DSH_MEMORY_CHAR_BUDGET` 覆盖仍生效，短会话仍 6,000）；
  2. 新增 `FOURS_MIN_ALLOWANCE`（默认 **12,000**，`DSH_MEMORY_FOURS_MIN` 可覆盖）：注入上限取 `max(预算, 5/5实际占用 + 12,000)`——**5/5 再膨胀也不会静默把 4/5 饿死**（这是 18,000 时代真踩到的坑）；
  3. `SNIPPET_CHARS` **260 → 480**：260 字恰好切在"什么时候用"之后、"关键参数"之前，28 条 4/5 里 22 条现在能全文进注入。
- 实测（线上库渲染，不碰数据）：注入 **26,373 字符**、**4/5 28/28 全进**、5/5 零截断、7 行 4/5 走 480 字摘要。旧配置对照 17,723 字符 / 4/5 只有 4 条。
- 成本：约 1 万 token。缓存命中价下每请求 <¥0.001，每会话首轮未命中约 ¥0.02；按每天 300–600 轮算，边际 **约 ¥1–3/月**。钱不是约束，真正的约束是"别把没用的常驻"——所以后面仍按 `记忆库优化规则.md` 定期净化。
- 新单测 `iterate/test-injection-budget.mjs`（6 条）：预算被压到 2500 时 4/5 仍按保底注入、超长 4/5 截断在 480+开销、5/5 永远全文。
- `test-injection.mjs` 补 1 条断言（4/5 确实被切）→ **ALL PASS (19)**。
- 备份 `lib/index.js.bak-20261029-133051`；`node --check` 通过；`check-plugin.mjs` SELFCHECK OK。

## v0.4.5（2026-10-29）修复：5/5 关键记忆在注入里被截断成 260 字摘要

- **bug**：`fmtInjected()` 只让「免疫标签」或 ≤260 字的行放行全文，其余一律切成 `前 260 字…（详情 memory_search）`。5/5 只是"必定注入"，**不等于"不截断"**——结果 5/5 的红线条目在系统提示里只剩半句。实测踩到：GPU 显存红线那条到了 `…②nu…（详情 memory_search）` 就断了，四层护栏和模型落位数字全看不见。
- **修**：`fmtInjected()` 增加 `importance >= 5 → 全文放行`；`IMMUNE_TAGS` 增加 `"red-line"`（此前写了 `red-line` 标签但白名单不认，白写）。
- **代价**：5/5 现在真的全文注入，实测 31 条 5/5 占约 16,300 字符，18,000 预算下 4/5 只剩约 119 字符（6 条截断行）。这是刻意取舍：**红线/铁律必须完整**，运维细节本该靠 memory_search 拿，不该常驻。
- 新工具 `iterate/measure-injection.mjs`：把真实 `memories.json` 拷到临时 DSH_HOME 后渲染，输出注入总字符 / 5/5 条数 / 被截断行数 / **5/5 被误截清单**，不碰线上库。
- `iterate/test-injection.mjs` 增加 3 条回归断言（超长 5/5 全文、超长 4/5 仍截断、`red-line` 标签免疫）。
- 备份 `lib/index.js.bak-20261029-133051`；`node --check` 通过；`test-injection.mjs` **ALL PASS (18)**。

## v0.4.4（2026-10-28）memory_search 第四级兜底：查编程知识库

- `memory_search` 原有三级兜底（AND → OR → 中文 2-gram）之后新增**第四级**：记忆库零命中时，自动查 `D:\work\学习计划\01-编程\知识库` 下的 `*.md`（排除 INDEX.md），用同一套 `queryGrams` 打分，命中 ≥2 个 gram 才列，输出「文件名 + 最相关行片段」（最多 5 条）；知识库也没有才回原来的「没有找到」。
- 为什么：记忆库放「长期规则/结论」，知识库放「踩坑细节/课程笔记」。搜不中记忆不代表知识库里没有——两边都问一遍，知识不活在一处。
- 备份 `lib/index.js.bak-20261028-kb`；`node --check` 通过。
- 另：`package.json` 版本此前落后 CHANGELOG 一格（0.4.2 vs 0.4.3），本次一并对齐到 0.4.4。

## v0.4.3（2026-10-28）注入预算 14,000 → 18,000 字符

- `CHAR_BUDGET` 默认 14000 → **18000**（`DSH_MEMORY_SHORT_SESSION=1` 时仍是 6000；`DSH_MEMORY_CHAR_BUDGET` 可覆盖，下限 2000）。
- 背景：实测 5/5 共 27 条 / 11,708 字符，已占 14,000 预算的 83.6%，4/5 只剩约 2,292 字符兜底空间——5/5 再涨一点，4/5 就被挤成 0。
- 扩到 18,000 后：4/5 留约 6,292 字符空间，5/5 也还有约 6,300 字符成长余量。
- 成本：注入从约 14,000 → 18,000 字符（≈ +2,700 token/轮）。缓存命中价下每轮 +0.0001 元，每天 400 轮约 +¥0.04/天，**每月约 +¥1**；新建会话首轮未命中多约 +¥0.003。
- 生效：`CHAR_BUDGET` 在模块加载时求值，**需重启 DSH**。
- 备份：`lib/index.js.bak-20261028-inject`。语法校验 `node --check` exit 0。

## v0.4.2（2026-10-27）注入预算 9,000 → 14,000 字符

- `CHAR_BUDGET` 默认 9000 → **14000**（`DSH_MEMORY_SHORT_SESSION=1` 时 6000；`DSH_MEMORY_CHAR_BUDGET` 可覆盖，下限 2000）。
- 背景：5/5 曾 23 条 / 8,957 字符吃满 9,000 预算，4/5 兜底失效；扩到 14,000 后 5/5 上限 12,000，4/5 仍留约 2,000 字符。
- 成本实测：+5,000 字符 ≈ 每轮 +0.00014 元（缓存命中价），每天 300 轮约 +¥0.04。

## 2026-10-27 自我迭代（v0.4.0 → v0.4.1）：先量再决定——不做 embedding

用户把"方向一（语义检索）"全权交给我。我没直接上 embedding，先做了**召回评测**再决定：

**评测设计**：`iterate/eval-keyword-recall.mjs` —— 20 题，每题一个已知目标记忆，两种问法：
- 「自然语言问法」（如"回复太贵了怎么省"）
- 「真实关键词问法」（如"省钱 花费"）
同一批目标，对比「现状 AND→OR」与「2-gram 打分」两种算法。结果：

| 算法 | 自然语言问法 | 关键词问法 |
|---|---|---|
| 现状（AND→OR） | **0/20（0%）** | **19/20（95%）** |
| 2-gram 打分 | 12/20（60%） | 17/20（85%） |
| **混合（关键词优先 + 2-gram 兜底）** | **12/20（60%）** | **19/20（95%）** |

**结论：不上 embedding。**
- 关键词检索本身**已经有 95% 召回**，真正的缺口是"用户敲整句话"（0%），而不是语义理解；
- 用 **中文 2-gram 兜底**就把整句召回从 0% 拉到 60%，零依赖、零模型下载、零额外延迟；
- embedding 只能再多救剩下 40% 的一部分，却要背模型体积 + 启动 + 向量存储 + 未来维护成本，**不划算**。

**代码变更（v0.4.1）**：
1. 新增 `queryGrams()`（中文 2-gram + ASCII 词元）与 `ngramRecall()`（命中 ≥2 个词元才算候选，按命中数排序）。
2. `memory_search` 改为**三级召回**：AND → OR → 2-gram 打分兜底。关键词路径行为不变（保证 95% 那档不掉）。

**验证**：`node --check` OK；`SELFCHECK OK exports=apply,inject,name`；`test-injection.mjs` 15/15；`test-dedupe-search.mjs` 14/14；混合策略复测 自然语言 12/20、关键词 19/20。
**生效**：Host 代码，需重启 DSH。

## 2026-10-27 自我迭代（v0.3.6 → v0.4.0）：记忆的遗忘、冲突与注入瘦身

用户给了四个升级方向，我按「指令吸收原则」做了取舍（不是全盘照做）：
- **采纳并合并**：方向三（冲突/版本）+ 方向二（遗忘衰减）→ 见下
- **改造**：方向四（动态组装）→ 拒绝"按用户第一句话路由"（注入发生在会话创建时，且每轮改动会摧毁前缀缓存），改为**静态分层 + 超长条目截断**
- **缓议**：方向一（本地 embedding 语义检索）→ 当前 200KB 笔记 grep 毫秒级，收益/复杂度不划算，先做关键词→语义兜底的小实验再说

**代码变更（4 处）**：
1. **`supersedes` 参数（方向三）**：`memory_save` 可传旧记忆 id 列表 → 旧条目标记 `deprecated` + `supersededBy` + `deprecatedAt`，**不再注入、不再参与冲突**；新条目记 `supersedes`。注入指纹 `injectionSignature` 加入 deprecated 字段，废弃后立即刷新。
2. **冲突提示（方向三）**：保存时按"关键词重叠 ≥4 个"找近邻旧记忆，返回 `⚠ 可能与下列旧记忆冲突…请带 supersedes`（只提示、不自动覆盖，避免误杀）。
3. **遗忘衰减（方向二）**：`applyDecay()` —— **只降级不删除**：非免疫类型、重要度 5/5、**180 天未使用** → 降为 4/5 并记 `decayedAt`；免疫标签 `identity/preference/rule(s)/authorization/user/safety` 永不衰减。
4. **注入瘦身（方向四改造）**：`fmtInjected()` —— 非免疫条目超过 260 字符时截断为摘要 +「详情 memory_search」；免疫类型始终全文。配合既有 `CHAR_BUDGET=9000` 字符预算。
5. `memory_search` 新增 `includeDeprecated`（默认排除废弃条目）；`fmtOne` 输出废弃标记。

**验证**：`SELFCHECK OK exports=apply,inject,name`；`test-injection.mjs` **15/15**；`test-dedupe-search.mjs` **14/14**；`node --check` 通过。
**生效**：Host 端代码改动，需重启 DSH。

## 2026-10-26 自主迭代（v0.3.5 → v0.3.6）

- **新增工具 memory_to_skill**：把流程性/操作性记忆转成 DSH 技能文件（`$DSH_HOME/skills/<slug>/SKILL.md`，带 name/description frontmatter 与「步骤/要点」正文）。原记忆保留，只追加 `skill:<slug>` 标签；支持按 id 或 query 指定。灵感来自 memsearch / dsh-unified-agent-memory 的 memory-to-skill（方式一：抄思路自己实现，未装任何外部插件）。
- **注入预算可调**：`CHAR_BUDGET` 从写死 9000 改为可配置——`DSH_MEMORY_CHAR_BUDGET` 直接指定（下限 2000），`DSH_MEMORY_SHORT_SESSION=1` 时降到 6000（短会话更省 token）。对应候选 ev-1793019698274「注入体量按会话类型微调」。
- **验证**：SELFCHECK OK；`test-injection.mjs` 15/15（工具数断言 5→6）；`test-dedupe-search.mjs` 14/14；新增 `test-memory-to-skill.mjs` **10/10**（生成 SKILL.md、frontmatter、正文、原记忆保留与标签、找不到时提示）。
- **生效**：代码需重启 DSH 加载。
# dsh-memory 变更日志

## 2026-10-26 自主迭代（v0.3.4 → v0.3.5）

- **代码（2 处，低风险）**：
  1. **注入按字符预算**：`renderInjection` 改为「5/5 全量优先 + 4/5 在 `CHAR_BUDGET=9000` 字符内尽量补」。为什么：上一轮已知待办——注入体量已达 9,640 字符/次且 5/5 只增不减，需要给个上限。
  2. **搜索退化 OR**：`memory_search` 在 AND 命中为零时，自动退化为「任一关键词命中」（中文无分词，多词 AND 常零命中），命中结果仍按相关度排序。为什么：上一轮已知待办。
- **验证**：`SELFCHECK OK exports=apply,inject,name`；`test-injection.mjs` **15/15**；`test-dedupe-search.mjs` **14/14**。
- **未改**：工具名/参数、去重逻辑、原子写、注入缓存指纹。
- **说明**：`MAX_INJECT` 常量保留（未被引用，后续可清）；代码需热加载或重启 DSH 生效。

## 2026-10-26 周迭代第 2 轮（v0.3.3 → v0.3.4，15:51 补跑）

- **数据来源**：`weekly-digest.md`（2026-10-26 15:51 生成，最近 7 天 33 个会话 / 341 条消息，80 个候选；同日 03:00 那轮用的是 35 会话版本）。本轮由 `iterate/iterate.ps1` 在 **15:51:29** 拉起（stamp=20261026-155129），不在 03:00 计划时点，属手动/补跑。
- **记忆库 51 → 50 条**（新增 1、合并删除 2、更新 7；备份 `memories.json.bak-20261026-155129`，旧备份一个未删）：
  1. 新增「20 元学习经费」约定：只用于必须真实付费接口的实验（地图/翻译/支付沙箱/短信等），花前说明用途和金额、事后记账，日常学习不花；
  2. 合并删除：第 4 批项目记录（`mem_mvnupfu7`）+ ai/web 子项目记录（`mem_mvo758j3_r7uzuh`）并入「编程学习总账」，并补 10-26 的 Web 第 8~10 课（SQLite 共享限流 0 超发、楼内分页 HTML 75KB→17KB、双实例 401=20/429=60/0 个 5xx；`web/run_all.py` 10/10、pytest 24 passed、提交 `3770c25`）与下一步（Nginx+HTTPS、Redis 多机限流、异地备份）；
  3. 更新：dsh-memory 自述（v0.3.4 + 新去重/排序 + 判断一轮是否完成别只看 iterate-log）、插件生态（archify 半装损坏→重装修复、OpenDesign MCP 恢复）、插件升级经验（半装残留在 pnpm 临时目录、pnpm 旧包可清）、Open Design（登记文件/备份/必须重启 DSH）、交付验收教训（新增 ⑤：别用静态扫描代替实跑，VS Code 误判实例）、token 习惯（不再自建用量统计脚本）、学习总账（见上）。
- **代码 v0.3.4（2 处，均低风险）**：
  1. **`memory_save` 归一化去重**：先按「小写 + 去空白/标点」比对，完全重复或一条被另一条完整包含（短者 ≥20 字）时不再新增，返回已有 id 并提示用 `memory_update`。为什么：连续两轮周迭代都在手工合并重复记忆（表情包两条、学习节奏两条），说明重复是常态；库越小，每次注入越省 token。
  2. **`memory_search` 相关度排序**：按词频（封顶 20 次）+ 标签精确匹配（+6）/标签包含（+2）打分，同分再按重要度、最近使用。为什么：原来只按重要度排，内容更贴题的条目会排在后面。多关键词 AND 命中语义不变（是否命中仍由 `matchQuery` 决定）。
  - 未改工具名/参数、未改注入策略、未引入任何依赖、未重构结构。
- **验证**：`SELFCHECK OK exports=apply,inject,name`（exit 0）；`iterate/test-injection.mjs` **15/15**（v0.3.3 回归：注入缓存/搜索排序/原子写）；新增 `iterate/test-dedupe-search.mjs` **14/14**（相同/相似/包含去重、短内容不误拦、相关度排序、AND 语义、无 .tmp 残留）；真实库副本：注入 20 条 / 9,640 字符（改前 8,974）、`memory_list` 50 条、三组搜索正常；`memories.json` 原子写后 `JSON.parse` 通过、50 条、id 与归一化内容均唯一、无 `.tmp-*` 残留。
- **同步**：`package.json` 0.3.4；`lib/index.js.bak-20261026-155129` 为本轮 `iterate.ps1` 启动时备份，SHA256 与改前文件一致。代码需重启 DSH 才加载；记忆库改动下次渲染即生效。
- **已知待办（下轮）**：注入体量已到 9,640 字符/次且 5/5 只增不减，建议评估「按字符预算注入」（如 6K 上限 + 5/5 优先）或把已完结项目细节降为 3/5；中文无分词导致「学习 进度」这类多词查询零命中，可考虑 AND 无结果时退化 OR + 相关度排序。

## 2026-10-26 周迭代（v0.3.2 → v0.3.3）

- **数据来源**：`weekly-digest.md`（2026-10-26 03:00 生成，最近 7 天 35 个会话 / 340 条消息，覆盖 10-21～10-25）。
- **记忆库 50 → 50 条**（新增 2、合并删除 2、更新 8；备份 `memories.json.bak-20261026-030412`）：
  1. 新增「编程学习 ai/ + web/ 子项目」：AI 应用 16 课、Web 全栈 7 课、各自 `run_all.py` 验证入口、学习规范新增项、下一步方向；
  2. 新增「交付验收教训」：测试全绿 ≠ 界面正确（22 项没抓到常量写反，截图才发现）、断言不凭印象数、入口异常统一处理、waitress 模板要重启；
  3. 合并去重：表情包偏好的两条（4/5）并入 5/5 那条并补全图库数量；学习节奏两条（5/5）合并，保留「吃白饭」教训原文；
  4. 更新：学习总进度（补 AI/Web 与 118 项测试）、dsh-memory 自述（v0.3.3 + 注入缓存 + 必须同步 CHANGELOG/version）、工作方式（补第 ⑤ 条：汇报后自主接续，不等指示）、本机插件生态（20+ bundle，新增 dsh-pocket 等待验证清单）、表情包库数量、手机接入备忘（先看 dsh-pocket，别重搭穿透）。
- **代码 v0.3.3（2 处）**：
  1. **注入文本按内容指纹缓存**：signature 只含 id/内容/标签/重要度/创建时间，不含 `lastUsedAt`。为什么：`memory_search` 每次都会更新 `lastUsedAt`，原来每次搜索后系统提示文字/顺序都可能变，导致整段前缀缓存失效（用户最在意 token/命中率）；现在只有记忆内容/标签/重要度/增删才重算，外部直接改库也能通过指纹自动刷新。
  2. **`memory_search` 结果按重要性排序**：原来按库内插入顺序输出，重要记忆可能排在后面；先 `sortMemories` 再展示，排序在写回 `lastUsedAt` 之前计算。
  - 补记：2026-10-25 21:19 曾把注入策略改成「5/5 全量 + 4/5 至少补 8 条」，当时未写 CHANGELOG、package.json 仍是 0.3.2；本轮一并记入并升到 0.3.3。
- **验证**：`SELFCHECK OK exports=apply,inject,name`（exit 0）；新增 `iterate/test-injection.mjs` 回归测试 **15/15**（注入/缓存命中/保存失效/更新失效/外部改库刷新/搜索排序/无 .tmp 残留）；真实库 50 条原子写后 `JSON.parse` 通过、无 `.tmp-*` 残留。
- **同步**：`package.json` 0.3.3；备份 `lib/index.js.bak-20261026-030421`、`package.json.bak-20261026-030421`。代码需重启 DSH 才加载。

## 2026-10-23 周迭代（v0.3.1 → v0.3.2）

- **数据来源**：`weekly-digest.md`（22:04:58 生成，最近 7 天 12 个会话 / 220 条消息）。
- **记忆库 21 → 22 条**：新增「桌上宠物」项目背景（@dsh-pet/bridge v0.2.0、桥接日志清理规则、241 张 WebP/24fps 的 CPU 成本、优先级 BelowNormal、用户决定保留现状、开机自启）；更新 5 条：
  1. 远程聊天两条路（Tailscale、同 Wi-Fi 网页 + 二维码）均已按要求彻底删除，现阶段不再折腾；
  2. 计划任务要查 LastTaskResult（267011 = 注册后从未运行，DSH-Plugin-Check 曾长期空转）；
  3. bili 折叠经济学补实测 miss 构成（新增 45% / 压缩重付 33% / 上游 TTL 22%）；
  4. DSH 技术事实补「会话日志可统计实时用量与命中率」；
  5. dsh-memory 自身描述同步到 v0.3.2。
  无删除、无合并（经检查无重复、无过时）；备份 `memories.json.bak-20261023-220640`。
- **代码 v0.3.2（1 处）**：`renderInjection()` 在记忆数超过 `MAX_INJECT=30` 时明确提示「另有 N 条因超出上限未显示，用 memory_search 检索」，不再静默丢弃。为什么：上轮周报遗留项 3；当前 22 条不触发，属防患。
- **验证**：`SELFCHECK OK exports=apply,inject,name`（exit 0）；注入单测 35 条 → 注入 30 条 + 「另有 5 条」，真实库 22 条 → 全量注入、结语不变；`memories.json` 原子写后 `JSON.parse` 通过、无 `.tmp-*` 残留。
- **同步**：`package.json` 升到 0.3.2（避免插件市场显示旧版本）；备份 `lib/index.js.bak-20261023-220640`；`iterate.ps1` 等脚本本轮未改。

## 2026-10-23 验证轮（周迭代第 2 次运行，无代码变更）

- **背景**：上一轮（21:34 启动）记忆库与 v0.3.1 改动均已完成，但 `iterate.ps1` 在 `$ErrorActionPreference='Stop'` 下把 `dsh` 退出时打印的非致命 stderr（`dsh: reasoning:`）当成终止错误，脚本在自检前中断。已改为调用原生 exe 时局部 `Continue` + `2>&1 | Out-String` 收流，再按 `$LASTEXITCODE` 判断（改的是 `iterate/iterate.ps1`，备份 `iterate.ps1.bak-20261023-213657`）。
- **本轮重跑**：验证 collect → headless agent → selfcheck 全链路；`SELFCHECK OK exports=apply,inject,name`（exit 0）。
- **代码不变**：`lib/index.js` 保持 v0.3.1，未升版本号。理由：本轮是验证轮，自检必须证明上一轮交付的代码；不为改而改。
- **记忆库**：21 条不变，更新 3 条——① 检查/汇报先报预算、只列异常项；② 用户授权自主判断、该修就修；③ PS 5.1 原生 stderr 终止错误的坑。备份 `memories.json.bak-20261023-214455`。
- **遗留已修**（同轮收尾）：自检分支也在 `Stop` 下调原生 exe，`check-plugin.mjs` 失败写 stderr 时会跳过回滚。已同样改为局部 `Continue` + `$LASTEXITCODE` 判断，回滚真的会触发；顺带修掉 `"$checkExit:"` 被 PowerShell 当成 drive-qualified 变量的语法错（改 `${checkExit}`）。语法复检 `SYNTAX OK`，`check-plugin.mjs` 实跑 exit 0 + `SELFCHECK OK`。

## v0.3.1（2026-10-23，每周自迭代）

- **损坏记忆保护**：`loadDb()` 解析失败时先把原始内容另存为 `memories.json.corrupt-<时间戳>`，再返回空库；避免下一次 `memory_save` 把损坏的整库静默覆盖。为什么：原实现 catch 后返回空库，写回时会丢光所有记忆。
- **周迭代脚本传参修复**：`iterate/iterate.ps1` 不再把多行 prompt 压成一行传给 `dsh.cmd`，改为传一句「读取 prompt-iterate.txt 并执行」的短指令，由 agent 自己读完整任务书。为什么：dsh.cmd 是批处理壳，多行参数会在第一个换行处截断；压成一行虽能跑，但会丢失结构和长度余量。
- **prompt 补充兜底**：headless profile 未加载 dsh-memory 时，明确要求先备份再原子写 memories.json，避免周迭代因没有 memory_save 工具而跳过记忆库更新。
- 同步把 `package.json` 升到 0.3.1，避免插件市场显示旧版本。
- 自检：`check-plugin.mjs` → `SELFCHECK OK`；另跑了损坏存储单测（5 个工具、corrupt 备份、写入正常）。

## v0.3.0（2026-10-23，补记）

- 新增侧边栏「记忆库」页面与 `lib/client.js`。
- 新增 `/dsh-memory/list`、`/dsh-memory/delete` 两个 web 路由（只允许本机页面访问）。
- `package.json` 升到 0.3.0。

## v0.2.0（2026-10-23，第一次自迭代）

- **原子写**：`memories.json` 先写临时文件再改名，避免并发/崩溃留下半截 JSON。
- **去重**：`memory_save` 内容完全相同的记忆不重复保存，直接返回已有 id。
- **搜索增强**：`memory_search` 支持空格分隔多关键词 AND 匹配（内容 + 标签）。
- **最近使用记录**：搜索命中时更新 `lastUsedAt`，注入排序改为 importance 优先、最近使用次之。
- **新增 `memory_update`**：按 id 修改内容、标签、重要性，形成完整闭环。
- **自检脚本**：`iterate/check-plugin.mjs` 校验导出/工具数，安装后自动跑一遍。

## v0.1.0（2026-10-23）

- 首个版本：`memory_save` / `memory_search` / `memory_list` / `memory_forget` 四个工具 + 系统提示注入。
- 零依赖实现（不 import `@deepseek-ai/dsh-tools`，手写 ToolDefinition），数据存 JSON 文件。
- 初始化 3 条基础记忆（用户偏好、工作区环境、游戏）。

