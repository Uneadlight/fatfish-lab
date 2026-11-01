# 坏了从哪查

不是手册，是**排查顺序**。原则：先定位在哪一层，再决定看哪个文件；不猜，找证据。

---

## 〇、三层定位法

任何故障，第一句话先问：**它坏在哪一层？**

| 层 | 症状长什么样 | 第一动作 |
|---|---|---|
| **进程层** | 窗口打不开、白屏、闪退、431 错误 | 查进程 + 端口 + Cookies |
| **插件层** | 某个面板空白/显示"异常"、工具列表里没有它 | 查插件健康 + 组合配置 |
| **行为层** | 工具报错、结果不对、慢、卡住 | 查会话内事件 + 命令退出码 |

**不要一上来就读代码。** 80% 的故障在前两层就能定位。

---

## 一、进程层

### 1.1 打不开 / 白屏 / 431

```powershell
# ① 进程在不在
Get-Process -Name 'DeepSeek Harness' | Select-Object Id, StartTime

# ② GUI 端口有没有在听
Get-NetTCPConnection -State Listen | Where-Object LocalPort -gt 40000

# ③ Cookies 罐多大（431 的真凶）
Get-Item "$env:APPDATA\@deepseek-ai\dsh-desktop\Network\Cookies" | Select-Object Length
```

**431 的判断依据**：`Cookies` 文件 **超过 16 KB**（HTTP 请求头上限）就会 431。
**注意反直觉的地方**：**空罐本身就是 20,480 字节**（SQLite 预分配），所以"看大小永远判断不出清没清"，只能靠冷启动时无条件删。

**修法**：跑 `D:\work\tools\dsh-launcher\launch.vbs`（冷启动会先删 Cookies 再起 DSH）。**绝对不要杀 `node.exe`**——那是 bili sidecar，不是 DSH。

### 1.2 崩溃

```
%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-*.log     ← 崩溃栈
%APPDATA%\DSH Desktop\logs\dsh-YYYY-MM-DD.error.log     ← 10-29 之前的日常日志
```

**注意**：10-29 换安装目录后 userData 也换了，新位置（`@deepseek-ai\dsh-desktop`）只留崩溃日志，日常日志不落盘。所以"没有日志"不等于"没出错"。

### 1.3 端口被占 / bili 连不上

```powershell
Get-NetTCPConnection -LocalPort 18787 -State Listen   # bili sidecar
Get-NetTCPConnection -LocalPort 11434 -State Listen   # ollama
```

bili 是**独立 sidecar 进程，不随 DSH 退出**。重开 DSH 时新实例会复用活着的旧进程 → **改完 bili 配置必须杀掉旧 sidecar 才生效**。注册表在 `%USERPROFILE%\.local\state\billion-context\instances\*.json`。

---

## 二、插件层

### 2.1 插件面板空白 / 显示"异常"

```powershell
# 逐个验证插件入口能不能真的 import
env_doctor only=health
```

正常输出形如「**19 个本地插件，19 个能正常加载**」。
界面上"看起来装了"和"实际能加载"是两件事——**这是 `only=health` 存在的唯一理由**。

### 2.2 改了插件不生效

**两个必踩的坑，按顺序查**：

1. **profile 里的副本是独立目录，不是软链**
   ```
   %USERPROFILE%\.dsh\profiles\desktop\node_modules\<包名>\
   ```
   改源码目录 `D:\work\dsh-xxx\` **不会**自动同步过去 → 必须手动拷。

2. **必须彻底退出 DSH 进程再启动**（关窗口不够）
   主进程还在 → 模块缓存还在 → 跑的还是旧代码。

**验证改没改到**：比对两边文件的 sha256。

### 2.3 组合配置看不懂 / 怀疑某个 bundle 没生效

```powershell
dsh --profile web --dump-default-config    # 打印组合后的完整配置树（YAML）
```

**desktop 是例外**：
```
error: profile "desktop" is managed exclusively by the Electron application
```
→ desktop 的配置只能看 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml`。

### 2.4 21 个已装插件：谁负责什么、怎么验证它活着

**先记一条通则**：「怎么验证」比「坏了什么症状」有用——故障是无限的，验证方法是收敛的。每个插件我都要有一条**一分钟内能跑完的活体检查**。

标记：✅ 我实测验证过活着 · 🔧 有真实故障记录 · ❔ 按配置推断，没亲自验过

| 插件 | 负责什么 | 怎么验证活着 | 记录 |
|---|---|---|---|
| `dsh-memory` 0.4.9 | 长期记忆库 + 系统提示注入 | `memory_search 随便一个词` 有结果；侧边栏有「记忆库」入口 | ✅🔧 并发写丢 116 条（v0.4.8 前）；改完不生效（profile 副本 + host 复用） |
| `dsh-env-doctor` 0.6.12 | 大内总管：状态/插件/任务/工具链体检 | `env_doctor only=health` 报「19 个插件全过」 | ✅🔧 未知 `only` 值曾静默报"全部通过"（0.6.9 才拦） |
| `dsh-evolve` 0.1.5 | 自迭代候选队列 | 侧边栏「迭代」面板能开，`evolve_status` 有数 | ✅🔧 **缺 `exports["./client"]` 直接启动崩**；`client.js` 的 id 必须等于**包名**，写 row id 会静默不显示 |
| `dsh-vision` 0.2.0 | 识图（智谱 GLM-4V → 本地 Qwen2.5-VL 兜底） | `vision_describe <一张图>` 有输出并标引擎 | ✅🔧 默认模型改完**不热更新**（要重启）；模型删了报 `HTTP 404 model not found`；源码目录曾是空的（`pnpm install` 会装出空包） |
| `dsh-workflow-skill` 0.1.0 | 工作流 SOP 技能 | `skill workflow` 能加载出 SKILL.md | ✅🔧 改完要同步 profile 副本 |
| `dsh-worktree-tool` 0.1.0 | 给代码开 worktree 分身 | `worktree_list` 返回列表 | ✅🔧 报 `git not found on PATH`（本机 git 不在 PATH，只能给绝对路径） |
| `open-design-mcp` 1.0.0 | MCP 服务（设计资源） | `list_mcp_resources server=open_design` 有返回 | ✅ |
| `dsh-session-delete` 0.1.0 | 会话菜单补「删除」 | 会话右键菜单有这样一项 | ✅🔧 **我擅自清左侧会话列表那次就是它**，红线记忆的由来 |
| `dsh-stickers` 0.1.3 | 输入框 `/表情` 面板 | 输入框打 `/表情` 弹面板 | ✅🔧 改完面板仍发旧图（profile 副本是拷贝 + host 进程复用内存里的旧代码） |
| `billion-context` 0.1.209 | 上下文压缩（sidecar 进程，端口 18787） | `acp_status` 有输出；`Get-NetTCPConnection -LocalPort 18787` LISTEN | ✅🔧 431 请求头过大（Cookies 罐只增不减）；小范围折叠亏钱（要 ≥40K tok 才划算） |
| `cc-safety-net` 2.6.19 | 拦危险命令 / 凭据文件 | 它会**拦我**：dot-source `.ps1` 报 `analysis.dynamic-shell-source` | ✅ 不要试图绕过它 |
| `dsh-ops` 0.4.1 | Windows 原生工具（file/shell） | `ops_bash` 能跑 | 🔧 本机 `ops_bash` **stdout 恒空**（exit 0 但零输出）→ 跑命令改用 `pwsh` |
| `dsh-context` 0.62.1 | 上下文仪表盘 | 侧边栏上下文面板有数据 | ❔ |
| `dsh-community` 0.2.1-alpha.1 | 社区插件目录 | 插件市场页能列出条目 | ❔ 和 `dshmarket` 功能重叠，注意别两个都坏还以为是同一个 |
| `dshmarket` 1.70.2 | 可视化插件市场 | 市场页能搜索/装 | ❔ |
| `dsh-chat-background` 0.3.0 | 聊天界面背景 | 设置页有背景选项 | ❔ |
| `dsh-startup-screen` 1.1.1 | 启动动画与授权序列 | 启动时能看到 | ❔ |
| `dsh-pocket` 2.10.6 | 手机扫码访问本机 DSH | 设置页出二维码 | ❔ 已知教训：服务挂在 DSH 进程树下会随重启断 |
| `@tt-a1i/archify-dsh` 1.0.0 | 架构图技能（skill-only） | `skill` 列表里有 `archify` | ❔ |
| `@dsh-pet/bridge` 0.2.0 | 把 agent 状态写进 jsonl 给桌宠读 | `%APPDATA%\dsh-pet-bridge\dsh-<主进程PID>.jsonl` 的 mtime 在动 | ✅🔧 桌宠 `config.json` 里 `agent_link.dsh=false` 时整条链静默不动 |
| `@deepseek-ai/dsh-subagent-claude-code` 0.2.1-rc.3 | Claude Code 子智能体后端 | 要本机有 `claude` CLI，**大概率没配，等于没启用** | ❔ |

**坏了会影响谁（按类型）**：
- **有客户端 bundle 的**（12 个）坏了 → 界面项消失/面板空白，但底层工具可能还能用 → 先去界面找，再去日志找
- **纯工具类**坏了 → 我调用时报"工具不存在"，是**能力缺失**不是权限问题（别自己吓自己）
- **后台 sidecar 类**（`billion-context`、`@dsh-pet/bridge`）坏了 → **最危险，因为静默**：界面一切正常，只是压缩不生效/桌宠不动。这两条必须靠"主动验证"发现，不能等报错

---

## 三、行为层

### 3.1 工具报错

先分清是**哪一种失败**，别混着说：

| `[FAIL:...]` 标签 | 含义 | 下一步 |
|---|---|---|
| `能力缺失` | 工具压根不存在 | 查插件有没有装、有没有开 |
| `权限被拒` | 工具在，但沙箱/审批拦了 | 看 `cordis.patch.yml` 的沙箱档位，**不要绕过** |
| `执行失败` | 工具和权限都有，跑的时候炸了 | 看退出码 + stderr |

### 3.2 沙箱拒绝长什么样

```
[sandbox: file access denied under <mode> mode]
```

这是**策略拒绝**，不是路径错误。三条纪律：
1. 不要换 shell 重试同一件事（那是绕过）
2. 不要改沙箱档位来"解决"它
3. 先判断是**该被拒绝**（真越界）还是**配错了**（路径确实在工作区内）

### 3.3 输出被截断 / 找不到完整结果

工具返回里有 `spill paths`（溢写到文件）。机制是 `dsh-spill-policy`：超 token 预算的工具结果会留一段可恢复的正文 + 图片引用。

**找法**：看返回里给的路径；或按 `dsh-spill` 的存储位置找。

### 3.4 会话内追查某一步

```powershell
session_event_search "关键词"            # 搜当前会话的事件流
session_event_search "关键词" --seq_from 100 --seq_to 200
session_event_read --seq 13100 --before 3 --after 0
session_event_trace --seq 13100          # 看这个事件被谁替换/引用了
```

这是**比读记忆库更准的证据源**——记忆是提炼过的，事件流是原始的。

### 3.5 花钱多 / 某轮特别慢 / 命中率掉了

**不用造新日志——现成的账本比我自己的记的准。** 数据源是 bili sidecar 的逐请求账本（当前会话实测 2313 次请求）：

| 我想知道 | 怎么问 |
|---|---|
| 这轮花了多少 token | `acp_cache` → LINE ITEMS 按时间找那一行（`input` / `cached` / `hit%` / `new` / `comp` / `ttl`） |
| 为什么贵 | miss 三类：**new content**（新内容，不可避免，占约 45%）/ **compress re-pay**（压缩重付，占约 33%）/ **upstream TTL**（上游过期，管不了，占约 22%） |
| 折叠赚不赚 | FOLD ECONOMICS：`净收益 = 省下 - 重付 - 摘要成本`。实测 217 次折叠：**213 赚 / 3 亏**，总净 +5103.88M tok |
| 是不是重启导致的重复计费 | RESTART/REFORK：每次 daemon 重启会把整段前缀**重新计费一次**（实测 22 次重启 / 600.3K tok，最狠两次各 200K+） |
| 某个时刻到底发生了什么 | `acp_cache detail:"full"` + 时间戳过滤 |

**三条读账本的经验**：

1. **99.x% 命中率是常态，全天平均 96–98%** —— 别因为某天 96% 就去"优化"，miss 里有近一半是不可避免的新内容。
2. **重启比什么都贵**：一次重启 = 整段前缀重付。所以"为了改个小配置重启 DSH"要先算一下值不值（改插件那种必须重启的另说）。
3. **慢 ≠ 贵**：慢通常是 TTFT（长上下文要重新读一遍前缀），贵通常是 miss。两件事分开说，别混着诊断。

**还有一个反直觉的**：账本显示 **2290 对相邻请求里 0 个是字节相同的**（`BODY STABILITY`）——每次都至少有尾部追加。这不影响缓存（前缀照样命中），但意味着"发出去的东西每次都变"是正常的，不用慌。

---

## 四、数据层

### 4.1 记忆库

| 症状 | 检查 |
|---|---|
| 条数不对 | `memory_list`；105/106 是**总条数**，含废弃留档，活跃数是另一个 |
| 注入超限 | 看注入尾行（5/5 / 4/5 / 3/5 三分法）；到 80% 报警线才净化 |
| 怀疑丢数据 | 并发写会静默丢（实测 8 进程×20 条，旧版只剩 44）；v0.4.9 后有锁 + `conflicts.log` |
| 文件坏了 | `memories.json` 做 JSON 校验；`.bak-*` 有 13 个历史备份 |

**铁律：同一时刻只让一个会话写记忆库。**

### 4.2 会话

```
%USERPROFILE%\.dsh\sessions\--<工作区URI编码>--\*.zstd
```

是 zstd 压缩的，**没有明文**，也没有 sqlite 索引。
所以 `session_search`（跨会话）返回 0 时，**先确认是"索引还没建"还是"根本没有索引"**——两者修法完全不同，不要猜。

### 4.3 仓库

```powershell
git -C <仓库> status --short
git -C <仓库> log -1 --format='%h %ad %s' --date=format:'%m-%d %H:%M'
```

**"本地全绿"不是验收**。真正的验收是**换台机器还能跑**（10-31 的 CI 在 Ubuntu 上炸出 3 个本地测不出来的问题）。

---

## 五、定时任务

```powershell
schtasks /Query /TN "<任务名>" /FO LIST /V | Select-String "Status|Last Result|Next Run"
```

| Last Result | 含义 |
|---|---|
| `0` | 成功 |
| `3221225786`（`0xC000013A`） | **被中断**（`STATUS_CONTROL_C_EXIT`）——常见于重启 DSH 时正好在跑 |
| `267011`（`0x00041303`） | 从未运行 |
| 其它 | 真失败，看任务自己的日志 |

**已停用的任务是不是问题**：看 `D:\work\自进化\task-expectations.json` 白名单——只有"在清单里 + 状态 Disabled"才算正常静音。

---

## 六、我自己的工具

| 工具 | 坏了怎么查 |
|---|---|
| `py` / `lab`（`%USERPROFILE%\.local\bin\`） | `Get-Command py`；`.cmd` 必须是 **CRLF**，LF 会让 cmd 吃字符 |
| `ghctl.py` | 报错自带三类标签；`--dry-run` 先看会做什么 |
| `triage.py` | `--file` 单文件跑；`pick_model` 按行数分流（>150 用 coder） |
| `env_doctor` | `only=all` 一次看全；`only=health` 验插件；`only=ssot` 查文档与代码漂移 |

---

## 七、三条救命命令

| 命令 | 什么时候用 |
|---|---|
| `dsh rescue --from-default-profile web` | **profile 被自己改坏了**，从出厂模板重建一个 |
| `env_doctor only=health` | 怀疑插件装坏（界面正常但实际 import 不了） |
| `D:\work\tools\dsh-launcher\launch.vbs` | 431 / 白屏 / 打不开 |

**升级退路**：`%USERPROFILE%\AppData\Local\@deepseek-aidsh-desktop-updater\pending\` 里留着上一个版本的安装包。

---

## 八、排查纪律

1. **先证明抓得到，再宣布修好。** 检查脚本要能在"有问题时返回非 0"，否则就是写了个永远 OK 的假检查。
2. **连续 3 次失败就停**，回头找"为什么这条路走不通"，而不是换参数硬试（10-31 装 rc.5 试了 6 组参数全是 exit 2，真因是"我就跑在 DSH 里"）。
3. **失败必须报清是哪一类**：能力缺失 / 权限被拒 / 执行失败。不许糊成"出错了"。
4. **本地能跑 ≠ 交付**。三个 Linux-only bug 全是本地 71/51/29 全绿时炸出来的。

---

## 九、修复剧本（三条）

> 剧本和速查的区别：速查告诉你去哪看，剧本告诉你**按什么顺序做、每步的判据是什么、走错了会看到什么**。全是踩过 2 次以上的坑。

### 剧本 1：改了插件，界面/工具还是旧行为

**判据**：源码改了、文件时间戳是新的，但行为没变。

| 步 | 动作 | 判据 |
|---|---|---|
| 1 | 确认改的是**源码**还是 **profile 副本** | 源码 `D:\work\dsh-*`；生效的是 `%USERPROFILE%\.dsh\profiles\desktop\node_modules\<pkg>\`，**是独立拷贝不是软链** |
| 2 | 比对两处文件 sha256 | **必须一致**；不一致就是漏同步 |
| 3 | 同步（复制，别用 pnpm） | `pnpm` 会重算依赖树、把 `link:`/`file:` 包移进 `.ignored` |
| 4 | 彻底退出 DSH | 托盘退出 + `Get-Process -Name 'DeepSeek Harness'` 必须为空 |
| 5 | 重开，验证 | 用**具体功能**验证（打 `/表情`、调 `vision_describe`），不要看"插件列表里有名字" |

**走错的信号**：只关了窗口就重开 —— host 进程（`DeepSeek Harness.exe --profile headless`）还活着，内存里仍是旧代码。
**查证**：对比 App 启动时间 vs host 进程 `StartTime`，host 比 App 早就是复用了。

### 剧本 2：DSH 打不开 / 白屏 / 报 431

| 步 | 动作 | 说明 |
|---|---|---|
| 1 | 跑 `D:\work\tools\dsh-launcher\launch.vbs` | 冷启动会无条件删 Cookies，**431 的真因是 Cookies 罐超过 16KB 请求头上限** |
| 2 | 还不行 → 看 `%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-*.log` | 只有崩溃日志，日常日志不落盘 |
| 3 | 还不行 → `dsh rescue --from-default-profile <name>` | 从出厂模板重建 profile |
| 4 | 最后才是重装 | 装之前先确认 `~/.dsh` 里的 memory / sessions / profiles 不会被带走 |

**走错的信号**：
- 盯着 cookies 文件大小看 —— **空罐本身就是 20,480 字节**（SQLite 预分配），看大小永远判断不出清没清
- 以为是"中文路径导致白屏" —— 这条**从未被证实**（10-30 查了半天，真因是桌面上另一个非 DSH 的快捷方式）
- 想着"杀 node.exe 释放端口" —— 那可能是 bili sidecar

### 剧本 3：插件大面积消失 / 启动报找不到模块

**判据**：界面项成群消失，`env_doctor only=health` 报一批加载失败。

| 步 | 动作 | 说明 |
|---|---|---|
| 1 | **先备份** | `package.json` + `cordis.patch.yml` + lockfile，一个都别省 |
| 2 | `env_doctor only=bundles` | 看具体缺哪些 |
| 3 | 查 `node_modules\.ignored\` | pnpm 重建会把"它认为不在依赖树里"的包移进去 |
| 4 | 把"**顶层没有同名**"的包移回顶层 | 223 MB / 90 项那种量级，**别删** |
| 5 | 复验 | `env_doctor only=health` 全过 + 界面项回来 |

**走错的信号**：
- 删根目录 `pnpm-lock.yaml` —— **无效**，pnpm 信任的是 `node_modules\.pnpm\lock.yaml`（内层）
- 删内层 lockfile —— **更糟**，触发全量重建，会把更多包移进 `.ignored`
- 跑 `pnpm install` "修一下" —— 本 profile 有 9 个 `link:` + 5 个 `file:` 手工包，pnpm 算不准依赖图，必然再误移一次

**铁律**：desktop profile **不要用 pnpm 写操作修**。装/卸插件走「手改 `cordis.patch.yml` + 复制 `node_modules` + 重启」。
