# RFC-20261029：本地算力 + 底层基建 + 多智能体编排

- 状态：**待审批**
- 起草：大肥鱼（2026-10-29 13:0x，空闲计费时段）
- 来源：《终极冷启动与全栈架构演进指令》（由另一 AI 起草，我按自己判断复核前提后执行）
- 本文件的作用：Task 2 之后的实现、验收全部以本文件为准；后续会话（含「任务接单」对话）读这一个文件即可接续

---

## 0. 前置声明：来源与前提审查

指令属 relayed（外部拟稿）。按「知识只有前提」铁律，我逐条核了它的前提，结论：

| 指令条目 | 前提是否成立 | 处理 |
|---|---|---|
| 记忆/铁律已在线，无需再读 | ✅ 成立 | 跳过「读 memories.json」，记忆已自动注入 |
| 工作区是 clean 的 git 仓库 | ❌ **不成立** | `D:\work` 是**容器目录不是仓库**；下面有 9 个独立 git 仓库 |
| git 命令可用 | ❌ **不成立** | 当前 PATH 无 git，`Program Files`/`D:\Program Files` 都没有 git.exe，需先定位修复（见 P4） |
| GPU 是 RTX 4060 8G | ✅ 成立（记忆确认） | — |
| 「GPU 利用率压制在 70% 以下」可代码硬拦 | ⚠️ **半成立** | 显存能硬拦，**算力利用率无法硬拦**（Ollama/llama.cpp 无算力限速参数）。见 §4 |
| 拉取 qwen2.5:7b | ⚠️ **需要改** | 当前只有 `qwen2.5vl:7b`（5.56GB，在 `D:\work\cache\ollama\models`）；7b 文本版运行约占 5.3GB 显存，贴着 70% 线。建议改 3b。见 §3.1 |
| B+ 树「相比红黑树磁盘 I/O 优势」 | ⚠️ **前提缺失** | 纯内存实现测不出磁盘 I/O。必须做页式落盘版才能实测。见 §3.2 |
| Task 3「对抗到 QA 全绿」 | ❌ **危险** | 无终止条件 = 烧钱黑洞。必须加预算/轮次/墙钟三重熔断，且 QA 判定必须是**可执行测试退出码**而非 LLM 主观评价。见 §3.3 |

**我的态度**：指令的方向（本地算力可控、底层脱离框架、多智能体编排）我认，是很好的三个维度；但按字面执行会踩上面 5 个坑，所以下面是修正后的方案。

---

## 1. 现状核实（实测，2026-10-29 12:56–13:10）

| 项 | 实测结果 |
|---|---|
| **GPU** | `NVIDIA GeForce RTX 4060 Laptop GPU`，驱动 565.90，**总显存 8188 MiB**；空闲时已用 **982 MiB**、剩余 6976 MiB、利用率 8%、温度 45℃ |
| **70% 红线换算** | 8188 × 70% = **5732 MiB**；扣掉系统已占 982 MiB → **模型可用余量 4750 MiB（≈4.64 GiB）** |
| Ollama 服务 | **未运行**（11434 不通）；client 版本 0.40.11；可执行文件 `ollama.exe` |
| Ollama 模型 | 仅 `qwen2.5vl:7b` 一个；模型目录 `D:\work\cache\ollama\models`（7 个 blob，5.56GB） |
| Python | **3.12.14**（`%LOCALAPPDATA%`，含 python-docx/openpyxl/Pillow/lxml 等） |
| Node | `C:\Program Files\nodejs\node.exe` v24.22.1 |
| uv | 0.11.1（`uv`） |
| **git** | **全盘找不到 git.exe**（Program Files / D: / E: / WinGet / scoop / choco 均无），PATH 也没有 |
| 工作区仓库 | `dsh-session-delete`、`Self-Opt`、`worktree-repo`、`底座实战`、`架构文档`、`规格书`、`费曼盲写-20261028`、`闭关`、`学习计划\01-编程` 共 9 个 |
| 计划任务 | `DSH-Auto-Learn`、`DSH-Closure-Loop`、`DSH-Metric-W0` 均处于禁用态（大内总管告警 5 条，与本任务无关，收尾单独看） |

### ✅ 前置阻塞 P1：已解除

12:56–13:10 期间本会话的沙箱把外部程序全拦了（`cmd.exe` / `python.exe` / `nvidia-smi.exe` / `ollama.exe` 全部 `Access is denied`，`ops_bash` 静默不执行）。**13:2x 把沙箱策略切到 danger-full-access 后复测全部通过**：nvidia-smi 出真数据、python 3.12.14 可跑、ollama client 0.40.11 可用。

留存一条经验：`workspace-write` 会话里「外部 exe 执行 + 管道捕获」可能被整体拦掉，**判断依据是"命令返回 Access is denied / 静默无输出无产物"**，不要误判成"程序没装"。

剩下的唯一环境缺口是 **git 不存在**（见 P4），不影响写码、只影响提交留痕。

### P4：git 缺失的补法

- 方案：装**便携版 MinGit**到 `D:\work\tools\git\`（约 50MB，解压即用，不写注册表、不改系统 PATH、不改环境变量），调用时用绝对路径 `D:\work\tools\git\cmd\git.exe`。
- 好处：完全可逆——不想要了删目录即卸载，不污染系统。
- 若不想装：这三份产物也可以不提交 git，只落盘（但会丢掉"每阶段一个提交"的可追溯性）。

---

## 2. 总体设计：三层同源，一条主轴

三个 Task 不是并列的，主轴是 **「本地/云端按能力与成本分流」**：

```
                   ┌──────────── Task 1: ModelRouter（路由与算力护栏）────────────┐
   任务 ──► 分类器 ─┤ 低智/高频 → 本地 Ollama（显存硬门 + 串行队列）              │
                   └ 复杂/长链 → 云端 API（超时熔断 + 重试 + 降级）                ┘
                                   ▲                         ▲
                     Task 2: 底层件（B+树页式存储 / RPC 传输）  │  Task 3: 编排器用它调度
                     B+树可当 Task 3 的「被开发产物」──────┘   Dev/QA 双角色对抗
```

- Task 2 的产物（B+ 树、RPC）**天然是 Task 3 的试验素材**：让 Dev 角色写"给 B+ 树加范围删除"，QA 角色用 pytest 验收。这样 Task 3 不需要另造题目，也不引入主观判定。
- Task 1 的 ModelRouter 是 Task 3 的成本闸门：QA 角色走本地、Dev 角色走云端。
- 因此顺序是 **T2 → T1 → T3**（依赖倒置），不是指令里 40/30/30 的权重视角。

---

## 3. 分任务方案

### 3.1 Task 1：本地算力护栏 + ModelRouter

**目录**：`.\task1_local\`

**A. 监控：零依赖优先**
- 库选型：**不装 pynvml**（多一个依赖 + nvml.dll 版本坑）。直接 subprocess 调 `nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits`，解析 CSV。每 200ms 采样一次。
- Tokens/s：**不从 GPU 猜**，从 Ollama 响应里取真值——`/api/generate` 返回 `eval_count` 与 `eval_duration`(ns)，`tok/s = eval_count / (eval_duration/1e9)`；流式则按首 token 时间算 TTFT。
- 显存真值：`/api/ps` 的 `size_vram` + nvidia-smi 的 used，两者交叉校验（差 >500MB 视为有别的进程在吃卡，直接拒跑）。
- 产物：`monitor.py`（采样+落 CSV）、`bench.py`（跑一次推理并出报告）→ `本地算力安全水位测试报告.md`（含图表数据、不同 ctx/并行度下的 VRAM、tok/s、温度曲线）。

**B. 70% 红线怎么"硬"拦（关键设计）**

| 层 | 手段 | 是否硬 |
|---|---|---|
| L0 预检 | 起跑前读 nvidia-smi：`used + 预估模型显存 > 5.6GB` 直接拒绝，抛 `VRAMBudgetExceeded` | ✅ 硬 |
| L1 加载 | 请求级 `num_gpu` 限制层数、`num_ctx` 压到 2048、`OLLAMA_MAX_LOADED_MODELS=1`、`OLLAMA_NUM_PARALLEL=1` | ✅ 硬（限制显存） |
| L2 调度 | **全局串行队列**（信号量=1）：同一时刻只有一个本地推理在跑；排队任务有超时，超时降级云端 | ✅ 硬（限并发） |
| L3 运行时 | 200ms 采样，`utilization.gpu > 70%` 连续 3 次 → 记录 `soft_violation`；`memory.used > 5.6GB` → 立即中止请求（abort）并清空队列 | ⚠️ 显存硬、**利用率只能告警+中止** |
| L4 兜底 | 温度 > 86℃ 或触发降频（sm clock 掉 20%）→ 冷却 60s 再放行 | ✅ 硬 |

**必须说清的实话**：`utilization.gpu` 是 NVML 的"过去采样窗口内有 kernel 在跑的时间比例"，单次推理一旦提交就是满 SM，**没有参数能把它压到 70%**。能控的是「一次只跑一个、每批小、跑完就停」，这在宏观上把**平均**占用压下来。所以红线我改成可交付的表述：

> 显存占用硬上限 5.6GB（8G×70%）；同一时刻只允许 1 个本地推理；连续 3 个采样窗口 GPU 利用率 >70% 视为软告警并记录；温度 >86℃ 强制冷却。违反 L0/L1/L2/L4 任一条 = 任务失败，不降级偷偷跑。

**C. ModelRouter**
```
class ModelRouter:
    def route(task) -> Decision            # 规则表 + 可插拔分类器（先规则，别上模型）
    def call(prompt, prefer='auto') -> Result
        # 超时(本地60s/云端120s) → 熔断(连续3次失败，60s半开) → 降级(本地↔云端)
        # 所有调用打点：model, latency, tok_in/out, cost_est, fallback_chain
```
- 分类规则先做**显式规则表**（长度、是否含代码块、是否需外部知识、是否高并发）而不是 LLM 分类——分类本身再调一次模型就是笑话。
- 验收：单测覆盖「显存超限拒绝」「超时熔断」「连续失败降级」「并发 20 个请求全部串行进本地」，全部 pytest 绿。

**D. 模型选型（用实测数字说话，需你拍板）**

红线换算：8188 MiB × 70% = **5732 MiB**，减去桌面当前占用 982 MiB → **模型可用余量 4750 MiB**。

| 模型 | 权重 | 估运行显存(2K ctx) | 落位后总占用 | 占 8188 的 | 判定 |
|---|---|---|---|---|---|
| `qwen2.5:3b` Q4_K_M | 1.9 GB | ≈ +0.4 GB | ≈ 3.3 GB | **40%** | ✅ 安全，tok/s 约 7B 的 2–2.5 倍 |
| `qwen2.5:7b` Q4_K_M | 4.4 GB | ≈ +0.9 GB | ≈ 6.3 GB | **77%** | ❌ **破线**，且只剩 4.75GB 余量装不下 |
| 已有 `qwen2.5vl:7b` | 5.56 GB | ≈ +0.9 GB | ≈ 7.5 GB | 92% | ⚠️ 只能短任务偶尔用，不能当主力 |

- **结论**：指令里的 `qwen2.5:7b` **在 70% 红线下物理上跑不了**（不是保守，是余量不够）。要么换 3b，要么把红线提到 80%（我不建议，笔记本 GPU 还要分给桌面合成和温度）。
- **我建议**：拉 `qwen2.5:3b`（1.9GB 下载）当"低智/高频"路由目标；7b 档留给已有的 vl 版跑短任务；不新装 7b 文本版。

### 3.2 Task 2：B+ 树 + RPC（纯标准库，零依赖）

**目录**：`进阶-20261029\task2_lowlevel\`

**A. B+ 树（两阶段，因为内存版测不出磁盘 I/O）**
- Phase A 内存版 `bplus_tree.py`：阶 t 可配（默认 64），key int/str，值任意；实现 查找/插入分裂/删除合并借位/范围扫描/有序遍历。压测 10 万条：`insert / search(hit,miss) / range scan / delete` 四组数字，输出表格。
- Phase B 页式落盘版 `paged_bplus_tree.py`：节点 = 固定 4KB 页，`os.pread/pwrite` 直接读写文件；带极简 buffer pool（LRU，可统计命中率）；页头带 checkpoint 标记（崩溃后能修）。
- **磁盘 I/O 实测对比**（这才是指令要的解释，用数据说话）：
  - 同一个 10 万 key 数据集：B+ 树（t=64，页=4KB）树高 3 → 每次查找约 3 次页读；
  - 对照组：每节点一页的朴素二叉搜索树，树高 ≈ 17 → 17 次页读；
  - 用真实 `pread` 计数（monkeypatch 计数 + `strace` 不可用则用计数包装）对比"随机 I/O 次数"和"总耗时"，再算 OS 页缓存命中前后的差异。
- 报告解释：为什么"页大小对齐 + 高扇出"能把 17 次 I/O 压成 3 次；为什么 SSD 时代 B+ 树仍然赢（I/O 次数 × 延迟 vs CPU 比较成本）；红黑树为什么适合内存不适合磁盘（扇出 2、树高 log2，写放大）。

**B. RPC（手写协议，禁止 json/pickle 走捷径）**
- 帧格式：`| 4B 大端长度 | 1B 类型 | payload |`。
- 序列化 `codec.py` 手写 TLV：支持 int(变长)/str(UTF-8)/list/dict/bool/null/bytes，禁止 `pickle`、禁止 `json.dumps`（自己写 encoder/decoder，测边界：空串、中文、10MB 大包、负数、嵌套 5 层）。
- 粘包/半包：服务端 `read_exact(n)` 循环；客户端测试必须**故意**做两件事——① 逐字节发（1 字节一 send，最坏分片）；② 一次 `sendall` 粘 100 帧。
- 并发：`threading` + `selectors` 实现多连接（每个连接一线程即可，验收要求 50 并发不停服）。
- 验收 pytest：`test_codec_roundtrip_1000`、`test_framing_byte_by_byte`、`test_framing_coalesced`、`test_concurrent_50`、`test_big_payload_10mb`、`test_half_close`（对端 0 字节读完就关 → 不崩溃不空转）。

### 3.3 Task 3：AgentOrchestrator（带三重熔断）

**目录**：`进阶-20261029\task3_orchestrator\`

**A. 角色隔离**：orchestrator 主进程不写文件；Dev / QA 各起独立 `subprocess`（独立 cwd、独立 prompt、独立日志），通过 orchestrator 转发的 `request/response` 文件交互；子进程禁止互相读对方的 prompt。

**B. 终止条件（硬，缺一不开跑）**
- `max_rounds = 6`（Dev 改一轮 + QA 判一轮 = 1 轮）
- `wall_clock = 15 min`
- `token_budget = 200_000`（累计超了立即停，报"预算耗尽"而非成功）
- 判定权归 **pytest 退出码**：QA 只负责"写/跑测试"，不许它用自然语言说"我觉得好了"。全绿 = `returncode == 0`。
- 连续 2 轮测试状态无变化（同失败用例集）→ 判"卡死"，提前终止并输出诊断报告。

**C. 双模式（控成本的关键）**
- `--mode mock`：LLM 用假响应（内置剧本），只验证编排、隔离、熔断、日志——**0 成本**，先让这个模式全绿。
- `--mode live`：真实调 API/本地模型，**需显式 `--i-know-the-cost` 才启动**，且总预算仍有硬上限。

**D. 演示题目**：用 Task 2 的 B+ 树「加范围删除 + 加迭代器」当 Dev 任务，QA 写 5 条 pytest 验收。不另造题目。

---

## 4. 执行顺序、依赖与时间窗

| 阶段 | 内容 | 依赖 | 预估墙钟 |
|---|---|---|---|
| ~~P1~~ | ~~修沙箱执行能力~~ | — | ✅ **已完成**（13:2x 复测通过） |
| P4a | 补 git（便携 MinGit 落到 `tools\git\`，不改 PATH/注册表） | — | 5 min |
| P2 | Task 2 A/B（B+树内存+页式+RPC）+ 报告 + git 提交 | P4a | 60–90 min |
| P3 | Task 1（起 Ollama、监控、护栏、Router）+ 报告 | P2 之后；模型下载待定 | 40–60 min |
| P4 | Task 3（编排器 mock 全绿 → live 跑一次对抗） | P2 的 B+树 + P3 的 Router | 60–90 min |
| P5 | 三份报告合并 + 记忆固化 + 收尾 | P2–P4 | 15 min |

**时间窗建议**：现在 13:1x 是**空闲价**（到 14:00），P1+P2 起步正合适；14:00–18:00 是高峰（单价 ×2），把重的调试/返工挪到 18:00 之后。如果一次连续干完，我估会多花 ¥1–2，不致命但没必要。

---

## 5. 成本

（本仓库不含费用数据——那是私事，不影响技术结论。）
## 6. 风险与人类闸门

| 风险 | 等级 | 处理 |
|---|---|---|
| ~~沙箱执行受限~~ | — | ✅ 已解除（danger-full-access 后复测通过） |
| git 缺失导致无法提交留痕 | 低 | 便携 MinGit 落 `tools\git\`，可删即卸载 |
| 下载模型占带宽/磁盘 | 低 | 3b 只有 1.9GB；用 `ollama pull` 断点续传 |
| Ollama 起服务占显存，影响你正常用电脑 | 中 | 只在跑任务时启动，`keep_alive=60s`，跑完 `ollama stop` |
| Task 3 live 对抗烧钱 | 中 | 三重熔断 + 需显式参数确认 + mock 先绿 |
| 中途被打断 | 低 | 每阶段结束提交 + 写 PROGRESS.md，新会话可续 |
| 与「聊天对话只聊天」分工冲突 | 低 | 建议：本会话做完一整条（P4a→P2），P3/P4 另开会话 |

---

> 说明：会话已切到 danger-full-access，P1 阻塞解除，原「升权」路线作废。

## 7. 需要你拍板的（其余我自己定）

1. **模型**（唯一真需要你点头的）：`qwen2.5:3b`（1.9GB，占 40% 显存）—— 我定的默认；若你坚持 7b，我就要把红线挪到 80%，或者接受"7b 只能小 ctx 短跑、随时可能被系统挤爆"。
2. **执行位置**：我定 **本会话做完 P4a→P2 整条链**（Task 2 是纯离线、零依赖、最好验收的），P3/P4 另开会话 —— 理由是长会话每轮重发大上下文最贵。
3. **git**：我定 **装便携 MinGit 到 `tools\git\`**，绝对路径调用，不碰系统 PATH/注册表，不用了删目录即消失。

## 8. 批准后我立刻做的

1. 显存红线写成 5/5 记忆（可执行表述：显存硬上限 5732MiB、模型余量 4750MiB、串行单推理、>86℃ 冷却）；
2. 建 `进阶-20261029/` 骨架 + PROGRESS.md，补便携 git；
3. 先跑一个 `print` 拿执行证据，再按 TDD 开写 Task 2；
4. 每完成一个可验收节点就更新 PROGRESS.md，本轮结束给真实数字（行数/用例数/耗时/成本）。
