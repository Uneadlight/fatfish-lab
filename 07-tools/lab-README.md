# tools/lab

把「每遇到一次就写一个一次性脚本」改成「每遇到一类就收成一个子命令」。

## 为什么有这个目录

2026-10-31 清点 `tools/gh-login/`：

| 事实 | 数字 |
|---|---|
| 积压的一次性文件 | **68 个**（63 脚本 + 5 数据） |
| 其中「往决策日志追加一段」 | 6 个，做同一件事 |
| 其中「读 app.asar」 | 4 个，做同一件事 |
| 每条命令里手写的 Python 解释器路径 | **106 字符** |
| `$env:PYTHONIOENCODING='utf-8'` 出现次数 | **100+（搜索打满上限）** |

正式工具只有 4 个（`ghctl.py`、`gh_api.py`、`github_device_login.py`、`push_fork.py`）。

**判断标准**：一次性脚本解决「这一次」，工具解决「这一类」。会不会再跑第二次，是唯一的分界线。

## 装在哪

两个 `.cmd` 放在 `~\.local\bin\`（这个目录**本来就在用户 PATH 里**，ruff 和 uv 也装在这儿）。

| 命令 | 作用 |
|---|---|
| `py <脚本> [参数...]` | 用 DSH runtime python 跑，自动 `PYTHONIOENCODING=utf-8` |
| `lab <子命令>` | 工作区小工具集合 |

切项目 venv：

```powershell
$env:PYEXE = 'D:\work\repos\ollama-python\.venv\Scripts\python.exe'
py -m pytest -q
Remove-Item Env:PYEXE
```

不设 `PYEXE` 时用 DSH runtime python。

## lab 子命令

### `lab log` —— 决策日志追加（替代 6 个 `_log_*.py`）

```powershell
# 从文件读正文（推荐：正文含中文，走文件不会有命令行编码问题）
lab log --mark "2026-11-01 09:0x" --title "标题" --body-file body.md

# 只看最后几段
lab log --tail 3

# 只打印不写
lab log --mark "..." --title "..." --body-file body.md --dry
```

- `--mark` 是**幂等依据**：日志里已有这个字符串就直接 `SKIP`，不会重复写。
- 正文缺 `**做了什么**` / `**为什么**` / `**取舍**` / `**教训**` 时给 `[WARN]`，但不阻止写入。
- 写入用 append 模式，不会读改写整份文件。

### `lab stage` —— 按清单发布到公开仓库（脱敏 + 凭证扫描）

```powershell
lab stage --dry          # 先看会拷哪些、扫描命中什么
lab stage                # 真拷
```

- 清单在 `release-plan.txt`，一行 `源路径 -> 目标路径`。
- 三层脱敏（`~`→`%USERPROFILE%`、`D:\work`→`D:\work`、主机名→`<host>`，顺序敏感）。
- 8 类凭证正则扫描，**命中非 0 就 `[STOP]` 不许发布**。扫描时豁免含 `re.compile(` 的行，否则扫描器自己抓自己。

### `lab asar` —— 读 `app.asar`（替代 4 个 `_asar_*.cjs`）

```powershell
lab asar list session        # 列出名字含 session 的包
lab asar desc worktree       # 带 description
lab asar read 'dsh/node_modules/@deepseek-ai/dsh-experimental-session-search/package.json' --max 0
```

- 不解包，按 header 里的 offset/size 直接读。
- asar 头格式：offset 0/4/8/12 四个 uint32，`jsonSize` 在 offset 12，JSON 从 **16** 起，数据区起点 `16 + jsonSize` 再按 4 字节对齐。
  **之前的 4 个脚本里有一个算错了偏移**（`16 + headerSize - jsonSize`），吐了 14KB 垃圾后 `SyntaxError`。

### `lab ci` —— 查某个 commit 的 CI 状态（替代 `_check_ci.py`）

```powershell
lab ci                   # 查 HEAD
lab ci 57456d0           # 查指定 commit
lab ci --wait 20         # 先等 20 秒让 CI 起来
lab ci --repo owner/name # 换仓库
```

退出码：`0` 全过 / `1` 有失败 / `2` 还有没跑完的（方便脚本判断）。

### `lab plugins` —— 列已装插件的元数据（替代 `_plugin_meta.py`）

```powershell
lab plugins
```

三列：版本、是否有客户端 bundle（`Y`/`-`）、描述。**`MISSING` 表示 package.json 里声明了但 node_modules 里没有**——这个正是环境坏掉的第一信号。

### `lab issue` —— 看 / 评论 / 关 issue（替代 `_close_issue2.py` 这类）

```powershell
lab issue 2                                        # 看
lab issue 2 --comment-file comment.md              # 评论
lab issue 2 --comment-file comment.md --close      # 评论并关闭
```

### `lab journal` —— 先落盘再执行留下的动作记录

`lab stage` 会在动发布仓库之前先记一条 `start`，成功记 `done`，扫描拦下记 `aborted`。中途崩了就会留下「有 start 没 done」。

```powershell
lab journal            # 最近 20 条，标出未完成的动作
lab journal --limit 0  # 全部
```

```
2026-11-02 07:07:25  stage.start       files=16
2026-11-02 07:07:25  stage.done        files=16

[AUDIT] 没有未完成的动作
```

有未完成的会返回退出码 1，并打印「上次可能中途崩了，核对现场再重跑」。

**`--dry` 不写记录**——试跑不该留痕。

### `lab observe` —— 只记录「我会做什么」，不执行

来源：`dsh-superagent-prototype` 的 observe 档。我一直在「直接做+事后汇报」和「先问一句」之间二选一，中间那档从来没实现过。

```powershell
lab observe add --kind cleanup --what "把 gh-login 剩下的 _* 收编" --why "同类已收编过" --estimate "15 分钟"
lab observe list
lab observe ack --id 1102-070818-cleanup
lab observe promote --kind cleanup        # 需要连续 3 条被认可
lab observe demote --kind cleanup --reason "..."   # 一次误执行就退回
lab observe stamp                         # 看当前规则版本
```

三条自制门槛（原文没写死，我补的）：

1. **升级**：同一类连续 `PROMOTE_AFTER = 3` 条被认可、零误执行，才能 `promote` 到 auto
2. **降级**：auto 下一次误执行就 `demote` 回 observe，**误执行计数不清零**——想再升必须先查清那次为什么错
3. **记录字段**：每条带 `policy` 版本（`SKILL.md+memories.json@<sha256 前 8 位>`）。规则一变哈希就变，旧的 "would accept" 能看出是旧规则下的

数据落在 `自进化/observe.jsonl` 与 `observe-mode.json`。

### `lab commit` —— 提交并推送（替代 5 个 `_commit_*.py` / `_push.py`）

来源：2026-11-02 那天光"上传到仓库"就手写了 5 个一次性脚本，每个都在重填同样四个坑。

```powershell
lab commit -m "docs: 补 lab commit 说明" --repo D:\work\repos\dafeiyu-lab
lab commit --msg-file msg.txt --files a.py b.py --no-push
lab commit -m "..." --all --dry          # 只看会提交什么
```

它一次绕开四个坑：

1. **中文 message**——写临时文件 + `git -c i18n.commitEncoding=utf-8 commit -F`，提交后回读 `git log -1 --pretty=%B` 比对首行，对不上就报错（不看终端长相）
2. **token 不落盘**——走 `http.extraheader`，`.git/config` 里没有凭据
3. **只对临时性失败重试**——连接重置/超时/HTTP 5xx 才重试，认证失败/非快进立即报错
4. **暂存区为空不等于做完了**——先问 `git rev-list --count @{u}..HEAD`，有未推送提交就跳过提交直接推送

**退避是 2/5/10/20 秒（约 37 秒），不是 2/4/8。** 这是第一次真用就撞出来的：原配置三次共 14 秒，连挂三次报 `Failed to connect to github.com:443 after 21065 ms`，隔一分钟手动重推就成功了——**「临时性」不等于「几十秒内会好」**，网络抖动恢复常在 30–60 秒量级。改成 37 秒窗口后同样的网络状况下第 3 次（退避 10s）就推成功了。

#### 提交说明的排版自检（2026-11-03 加，只提示不阻断）

```text
[lint] 提交说明有几处读起来费劲（只提示，不阻断）：
   · 首行 90 字，超过 72（git log 会被截断）
   · 有一段连续 6 行以上没留白，读起来会挤
   → 觉得无所谓就继续；下次不想看到加 --no-lint
```

**为什么只提示不拦**：lint 要解决的是「人读不下去」，一旦拦下来就会变成「为了过检查而改文档」，那就反了。所以这里只挑两种最硬的毛病——首行 >72 字、连续 6 行以上没留白；不评判文风。

**跳过**：`--no-lint`。

#### 未跟踪文件会拦下来（2026-11-02 真事故之后加的）

**默认模式遇到未跟踪文件会直接 `[FAIL:用途错误]`，不管暂存区是不是空的。**

起因：发 `lab ocr` 那天，`lab stage` 拷了 20 个文件进发布仓库，`lab commit` 只提交了 **2 个**——新写的 `07-tools/ocr_run.py` 因为是未跟踪文件（默认 `git add -u` 不含新文件）没进提交，而 `lab.py` 已经在 import 它。**远端直接断**，靠验证才发现，补了 `7be5e4e` 才修好。

所以现在三种情况要分清：

| 你想要的 | 用哪个 |
|---|---|
| 提交全部改动（含新文件） | `--all` |
| 只提交指定的几个文件 | `--files <路径…>` |
| 本来就不该进版本库的 | 加进 `.gitignore`，不算未跟踪 |

**`lab stage` 之后请用 `--all`** —— stage 会把新文件拷进发布仓库，默认模式会拦住你。

判据不是"暂存区空不空"，是**"这次提交会漏掉什么"**——空的时候要查，不空的时候更要查。

### `lab reconcile` —— 记录对账：日志 / 账本 / git 摆在一起

来源：2026-11-02 想明白的一件事——**我的记录之间从来不对话**。记忆库和日志、日志和账本、工具和工具，每一块都挺真，合起来还是个单点。

```powershell
lab reconcile                    # 对全部日志
lab reconcile --days 3           # 只看最近 3 天
lab reconcile --selftest         # 先证明检查抓得到
lab reconcile --md report.md     # 另存
```

**它做的不是「自动判错」。** 三份记录对不上，绝大多数情况不是"有一个错了"，是"有一个没解释"。所以输出是一张表：

| 类 | 检查 | 不匹配时该补什么 |
|---|---|---|
| A | 日志明确写着的提交号，在登记的仓库里都找不到 | 号记错了 / 提交在没登记的仓库 |
| B | 日志把某提交记在 X 日，git 显示是 Y 日 | 当天写日志、事是前一天做的？还是时间写错？ |
| C | 某天日志很活跃，账本却没数据 / 花 0 元 | 纯本地活（正常）？还是账本缺了？ |

**不许自动改任何东西，只报告。** 改不改是人的判断。

**为什么必须有 `--selftest`**：按 SKILL.md 第 15 条，一个永远返回 OK 的判据不是判据，是装饰。自检造三种假差异（假提交号 / 2020 年的日志里写 2026 年的提交 / 3 段日志但账本没这天），跑一遍看抓不抓得到——三种都抓到才算数。

**第一版的三次翻车**（都是真问题，不是代码写错）：
1. 把 `safe_mutate` 的审核 token `8e99d8c16c3cd4b7` 当成提交号 → 后来分强/弱上下文两档，孤立的 hex 找不到就不报
2. 段落正则要求 `HH:MM`，可日志里真实存在 `## 2026-10-30 20:2x`（手写没记准）→ 那一段没被切成新段，**后面的 22 段全被并进来**，把 11 月的提交号算到 10-30 头上，骗出 6 条假差异
3. 账本的 `ts` 是 Unix 时间戳，我 `str(ts)[:10]` 当日期用了 → 12 条记录被当成 12 个"日子"，又骗出 3 条假差异

**这三条合起来说明一件事**：对账工具自己也得先对账——**报出来的差异，先核对原文再信**。

**已知局限**：只做结构化核对（提交号、日期、金额），读不懂"日志说做了三件事"这种自然语言；账本 2026-11-01 才有数据，之前的日期只能报"账本没这天"。

**它是体检，不是报警器。** 大多数时候跑出来是「没有发现需要解释的差异」——这是正常的，不是它没用。就像 pytest 大部分时候全绿，坏了才抓得到。**判断它有没有用，看 `--selftest`，不看某一次的输出。**

**两类被刻意过滤掉的噪音**（都是自己踩出来的）：
- **同一行里出现 `token` 的，整行不当提交号**。起因：我在决策日志里写「把 safe_mutate 的审核 token 当提交号。`8e99d8c1…` 是 16 位 hex」——**这句本身是在解释这个坑，结果被自己的工具抓成了新差异**。
- **账本覆盖范围之前的日期不报**。账本 11-01 才有数据，10-27~10-30 每次跑都报同样 4 条，会把真差异淹掉。

宁可漏报一行，也不能天天喊狼来了。

### `lab ocr` —— 图片转文字（本地离线，0 元）

```bash
lab ocr 截图.png                  # 纯文本，一行一条
lab ocr 截图.png --layout         # 带坐标和置信度，保留版面位置
lab ocr 截图.png --json           # 完整 JSON（给脚本消费）
lab ocr 截图.png --min-score 0.5  # 过滤低置信度的行
```

**为什么是「转发」而不是「直接 import」**：`rapidocr_onnxruntime` 只装在 `D:\work\tools\ocr-venv312`（Python 3.12），而 `lab.py` 跑在 DSH 的 runtime python 里。所以 `lab ocr` 是把任务转给 `ocr_run.py`，由它在那个 venv 里跑——**换机器时两个路径都要带走**。

**实测**（640×240 的中英混排图，三行）：置信度 0.96 / 1.00 / 0.99，**耗时 0.62 秒**，本地 CPU，不花钱、不联网。

**和 `vision_describe` 的分工**：

| | `lab ocr` | `vision_describe` |
|---|---|---|
| 干什么 | **只认字**，给出文字和坐标 | 描述画面内容、回答关于图片的问题 |
| 跑在哪 | 本地 CPU（RapidOCR） | 智谱 GLM-4V（云端，有缓存）或本地 Ollama |
| 花钱 | **0** | 云端按次，本地 0 |
| 什么时候用 | 截图转文字、表格转文本、批量提取 | 看不懂图里是什么、要理解场景 |

**先试 ocr**：如果只是"把图里的字抠出来"，本地 0.6 秒就够，不必花云端的钱。

### lab correction

**纠正日志**：每次用户纠正我，记下「**原话 / 我原来的想法 / 改成了什么**」。

```bash
lab correction add --said "用户原话" --was "我原来的想法" --now "改成了什么" --tags 判断权 完成标准
lab correction list [--limit 5]
lab correction stats      # 按标签统计
```

存在 `D:\work\自进化\corrections.jsonl`（append-only，写后回读校验）。

**为什么需要它**（起因是读社区插件 `dsh-run2skill` 那句「把对话里的纠正变成可复用的东西」）：

记忆库存的是**结论**（"乱码先怀疑读法"），**没有一处记「我原来错在哪」**。
缺了 `was` 这一栏，纠正就退化成一条新规矩——你知道该怎么做，但不知道自己犯的是哪**一类**毛病。

**首日 5 条真实数据的发现**：按标签统计，「**判断权**」出现 2 次，是最高频的一类——而那天我口头上以为自己在处理的是"乱码、锁、退避窗口"这些技术问题。数据说：被纠正最多的不是技术，是**接受得太快、用别人的判断代替自己的判断**。

| 标签 | 次数 | 代表性一条 |
|---|---|---|
| 判断权 | 2 | 评审说得有理，我四条全接受了 |
| 方向 / 完成标准 | 各 1 | 只读了 6 个插件就说"全量搜索做完了" |
| 事实 / 表达 | 各 1 | 把「很慢」说成「没有」 |
| 时间 / 拖延 | 各 1 | 给自己划一条「明天」的线 |

**判据**：这个工具只在「我被纠正」时写一条——**不写我本来就做对的事**，否则它就是流水账。

---

## 2026-11-03/04 新增的 11 个（按「什么时候用」组织）

前 13 个是「我要做某事时去用它」；这 11 个不一样——**它们挂在某个高频动作上，到那个点才该触发**。所以先写触发信号，再写用法。

| 子命令 | 触发信号（什么时候该想到它） | 一句话 |
|---|---|---|
| `tier` | **开工第一件事**（每个新任务） | 从任务描述里数规模、报档位，顺带推手边可能用得上的资产 |
| `selfcheck` | 刚装/卸插件、刚给 lab 加子命令、刚改 profile、或隐约觉得"文档说的跟实际不一样" | 查文档里的子命令/路径/计数跟磁盘对不对得上 |
| `fact` | **要说任何数字/版本号/文件大小/条目数/路径之前** | 验这句话里的数有没有出处 |
| `balance` | **报预算/说"这轮大概花多少"之前** | 真实余额 + 今日花费 |
| `snapshot` | **改重要文件之前** | 拍快照，改坏了能退 |
| `sessions` | 想说"上次/之前/以前做过吗"、用户提到具体日期、要判断"这事是不是已经做过" | 列会话清单 / 搜关键词 / 读原文 |
| `claims` | 收尾说自己"做完了"之前 | 完成声明对账：日志/提交/文件接不接得住 |
| `encoding` | 出现乱码、或要读非 UTF-8 的老文件 | 判编码 / 解码 / 修乱码 |
| `config` | 改 DSH 配置之前 | 配置备份（白名单，不含 secrets） |
| `tools` | 怀疑"某个能力白装了"、或想复盘"我到底用了哪些" | 从全部会话里数工具调用次数，列出零使用的 |
| `assets` | 想不起来"这个目录/文件是干什么的"、或要清理又怕删错 | 扫工作区每项的体积、最后修改、有没有说明、被谁引用，判"在用/停用/垃圾" |
| `skill` | 想说自己"会用什么"、或觉得"我好像有本事没用上" | 能力熟练度：真熟 / 用得费劲 / 还没用上（只分两层，不分时间跨度） |
| `lint` | 写完文档/长回复之后，或觉得"这段人读不下去" | 排版检查：标题过长 / 一行多事实 / 长段落 / 超长行（只提示不阻断） |

### `lab tools` —— 装了不等于用了

```bash
lab tools            # 全量排行 + 零使用分组
lab tools --never    # 只看零使用
```

从所有会话的 `tool-call` 事件里数，对照 `tool_stats.py` 里手写的 `KNOWN` 清单找缺口。

**2026-11-03 首跑的真实结果**（28 个会话）：**76 个已知工具里 30 个一次都没调用过，使用率 60%**。

零使用集中在四族：

| 族 | 零使用的工具 | 我的判断 |
|---|---|---|
| 智能体团队 | `spawn_teammate` / `wait_agent` / `interrupt_agent` / `team_task_*`（7 个） | **该用未用**——`workflow` 用了 27 次，`spawn_teammate` 0 次。同一个能力的两条路，我只走了一条 |
| 持久终端 | `terminal_*`（7 个） | **该用未用**——`pwsh` 被调了 2,932 次，每次都是新进程，`cd`/venv/变量全丢 |
| MCP 资源 | `list_mcp_resources` / `read_mcp_resource` / `list_mcp_resource_templates` | 场景少（OpenDesign 不常开） |
| 目标 / worktree | `create_goal` / `get_goal` / `update_goal` / `worktree_create` / `worktree_remove` | 场景少（长任务、并行开发） |

**这个工具的价值不是"催我把 30 个都用上"**——大部分场景本来就用不上。价值是**把"该用未用"和"本来就用不上"分开**，前者才是真缺口。

**2026-11-03 逐族判完的结论（27 个零使用）**：

| 族 | 判定 | 依据 |
|---|---|---|
| 智能体团队（7 个） | **场景少，不硬用** | `list_agents` 实测只有我自己；用户对话是串行的，没有长期并行需求。`workflow` 27 次已覆盖"一次跑完的并行" |
| 持久终端（6 个） | **该用未用 → 已修** | `pwsh` 2,932 次全是新进程，`cd`/venv/变量全丢。已把触发信号写进 SKILL §5（"连跑 ≥3 条且共享状态"），并实测状态保持有效 |
| worktree（2 个） | 场景少 | 我没有并行开发需求 |
| 目标（3 个） | 场景少 | `create_goal` 是给"跨轮次自动继续"用的；我目前的长任务都能在一次会话里收尾 |
| MCP 资源（3 个） | 场景少 | OpenDesign 不常开 |
| 会话检索（2 个） | 场景少 | `session_search` / `session_event_search` 已够用，读原文和追谱系还没遇到需要 |
| `memory_to_skill`（1 个） | **场景少（查过才敢说）** | 用 `memory_search` 搜了"流程/步骤/SOP/每次都要"，9 条命中全是知识/教训/偏好，**没有一条是"每次都要按步骤做"的**——我的记忆里还没长出那种形状 |
| `decompress`（1 个） | 场景少 | 压缩后确实没回头查过原文；但这本身值得留意——如果哪天压缩丢了关键信息又找不回来，就是它的场景 |
| `acp_read_original_image`（1 个） | 场景少 | 只在看不清小字时用 |
| `exit_plan_mode` / `skill`（2 个） | 场景少 | 我没进过 plan mode；技能靠系统提示自动加载，不需要主动 `skill` |
| `dsh-memory`（1 个） | **误报** | 那是插件名不是工具名，`KNOWN` 清单该删 |

**判完之后的结论反而不悲观**：27 个里 24 个是真场景少，2 个该用未用（已修 1 个），1 个误报。**"40% 没用过"听起来吓人，拆开看大部分是合理的。**

**清单外但用过的**（如 `evolve_inbox_done`）会单独列出——那说明 `KNOWN` 该更新了。**清单会过期，但过期本身有用。**

### `lab selfcheck` —— 机制跟能力对不对得上

```bash
lab selfcheck            # 四组检查，返回码 0=一致 1=有漂移
lab selfcheck --only 3   # 只跑第 3 组（计数断言）
lab selfcheck --json
```

四组：①`lab <子命令>` 引用是否存在 ②绝对路径引用 ③计数断言（"N 个子命令" / "N 个 bundle"）④文档互引断链。

**为什么需要它**：能力涨了、文档没跟上，我就按一个不存在的世界行动——**这比没有机制更坏**。2026-11-03 第一次跑就抓到 2 处真漂移：`架构文档/README.md` 写「25 个 bundle」实际 31、`我的能力清单.md` 写「13 个子命令」实际 24。

**它区分「真漂移」和「提案/历史」**：`SOFT_MARKERS` 命中的行（"→ 不写死"、"已改"、"曾经"、"如果一周内"、"抄："…）降级成 💬 提示、不计入失败。**不这么分，误报会把真信号淹掉**——第一版 15 处里只有 2 处是真的。

**有意思的自指**：我写这条 SKILL 行时又带上了那两个过期数字当例子，**被它自己抓到了**。写在文档里的数字一定会过期，哪怕写它的目的是提醒数字会过期。

### `lab fact` —— 说数字之前先查

```bash
lab fact "SKILL.md 45,930 B，见 E:\...\SKILL.md:147（实测）"   # 全绿
lab fact "我改了 SKILL.md，43 条规矩，13 个 lab 子命令"          # 两条 ⚠️，退出码 1
```

**它验的是「有没有出处」，不是「对不对」**——机器不知道"什么算一条规矩"，所以判不了真值。它只回答一个问题：**这个数字旁边有没有引用、行号、实测记录**。

⚠️ 的含义是"这句话里的事实没有出处"，不是"这句话是假的"。补出处，或者改说"我没查，这是印象"。

**为什么需要它**：2026-11-03 一天里 8 次违规，**5 次是数字编错**（"43 条规矩"、"13 个子命令"、"28,000 报警线"…）。写完才发现——**说数字是每分钟都在发生的高频动作，而第 17 条只管"完成"这个低频大节点**，所以拦不住。

**第一版设计是错的**：想自动验证数字对不对，实测只验出 1 个路径、其余全 ❓、抓不到任何错。改成"验出处"之后 7/7。

### `lab snapshot` —— 改重要文件前拍一张

```bash
lab snapshot now <path>          # 拍快照
lab snapshot list --path <path>  # 列这张文件的历史快照
lab snapshot restore <id>        # 恢复到某条（恢复前会再拍一次，所以恢复本身可撤）
lab snapshot undo <path>         # 回退上一次，可连调：v3→v2→v1
```

存在 `~/.dsh\devkit\checkpoints\`，**跟 `dsh-self-guard` 插件共享同一份存储**——插件自动拍的、我手动拍的，在同一个地方能查到。

**存储逻辑抄自 `dsh-local-devkit` 的 `CheckpointStore`**：文件不存在时记 `existed:false`（恢复时删除）；超过 4 MB 记 `skipped:'too-large'`；只留最近 500 条。

**为什么需要手动版**：插件只在 `write`/`edit` 工具上生效，**我用 PowerShell `Set-Content` 改文件它抓不到**——改重要文件时要主动补一刀。

### `lab sessions` —— 找以前的对话

```bash
lab sessions                              # 列全部：时间 / id / 条数 / 大小 / 首句
lab sessions 关键词 --days 7              # 搜（--all 也搜我的回复）
lab sessions --show <id> [--head]         # 读原文（默认末 40 条）
```

实测：30 会话 / 1,367 条消息，索引重建 1.9 秒，之后搜 0.01 秒。

**核心判断**：**能力本来就有，缺的是「看得见的入口」**——搜索只在你记得关键词时才管用；不记得关键词时，只有清单能救。

**读了 `dsh-manage-session`（792 KB）之后决定不抄**：它是 `inject = ["webServer","webStartup"]`、直接读磁盘 `.zstd`，主体是 GUI 面板 + webServer 路由。核心能力我这边早就有，只缺 `--list` / `--show` 两个模式。

### `lab balance` —— 真实余额 + 今日花费

```bash
lab balance          # 余额 CNY 37.67 / 今日 0.06 元
lab balance --json
```

走 `https://api.deepseek.com/user/balance`，key 从 `~/.dsh\.credentials.yaml` 的 `DEEPSEEK_API_KEY` 读。今日花费**用余额差值估算**（首日只记基线、记 0），因为平台账单接口要另一个 token。

**为什么需要它**：报预算时我在猜。2026-11-03 估 2.5 元、实际 14 元，**差 5.6 倍**。

### `lab encoding` / `lab claims` / `lab config`

```bash
lab encoding detect <file> [--explain]   # 判编码，--explain 说依据
lab encoding read <file>                 # 按判出来的编码解
lab encoding fix <乱码文本>              # 试 latin1/gbk/utf-16le 恢复
lab claims [--date YYYY-MM-DD]           # 我说"做完了"，日志/提交/文件接不接得住
lab config                               # DSH 配置备份（白名单，不含 secrets）
```

`encoding` 抄 `dsh-encoding` 的判据：BOM → 奇数位零字节占比 → 严格 UTF-8 校验 → 高位字节占比 → gbk / binary。**它保住 BOM 信息**（不把 utf-16le 猜成 utf-8），恢复时给 `{ok, text, note}`；含 U+FFFD 时 `ok=False` 并明说"更早的误解码已销毁，救不回来"。回归 9/9。

## 两个硬坑（都踩过）

### 1. `.cmd` 必须是 CRLF

`write` 工具写出的是 **LF** 换行。cmd.exe 解析 LF-only 的批处理会错乱：

```
'-' is not recognized as an internal or external command
'ves' is not recognized as an internal or external command
'age:' is not recognized as an internal or external command
```

（`'age:'` 是 `Usage:` 被吃掉一半的结果 —— 字符会丢。）

修法：

```powershell
$c = [System.IO.File]::ReadAllText($f) -replace "`r?`n", "`r`n"
[System.IO.File]::WriteAllText($f, $c, (New-Object System.Text.UTF8Encoding $false))
```

### 2. 不能用 dot-source 定义函数

想做的本来是 PowerShell 函数（`. lab.ps1` 之后 `py xxx.py`），但 DSH 的 CC Safety Net 会拦：

```
BLOCKED by CC Safety Net
Rule: analysis.dynamic-shell-source
Segment: . D:\work\tools\lab\lab.ps1
```

字面路径和变量都拦。所以**只能走 PATH 上的 `.cmd`**，不能靠 profile/函数。

## 还没收的

**2026-11-01 收编结果**：`tools/lab` 从 **37 个文件降到 9 个**。28 个一次性脚本归档到 `D:\work\备份\_scratch\lab-20261101\`（**转移不删**，随时能拿回来）；`_count_tools.py` 改名成 `tool_stats.py` 与仓库里的版本对齐。剩下 9 个：`lab.py` / `lab.ps1` / `README.md` / `release-plan.txt` / `gen_pkg_index.py` / `git_commit.py` / `read_session.py` / `session_grep.py` / `tool_stats.py`。

判据不是「多久没跑过」，是**「下一次同类事情会不会再需要它」**——`lab ci` 和 `lab plugins` 是每次发版都会用，`_classify.py` 是一次性的 306 包分类、跑完就结束。

`gh-login` 里还有几类没动，因为它们的接口还没稳定：

- **发布流水线**（6 个）：`_stage_repo.py`、`_scrub_repo.py`、`_scrub_repo2.py`、`_stage2.py`、`_stage3.py`、`_sec_scan.py`
- **提交推送**（8 个）：`_commit_push*.py`、`_fix_commit.py`、`_sync_final.py` …（`ghctl sync` 已覆盖大部分）
- **Release**（3 个）：`_make_release.py`、`_rel_v130.py`、`_verify_tree.py`
- **补丁脚本**（7 个）：`_patch_*.py`、`_fix_*.py`

这些不急着收：先让它们跑几次，看清哪些参数是固定的、哪些是真变量，再定接口。**先有用法，再有工具**，反过来会设计出一个没人用的工具。
