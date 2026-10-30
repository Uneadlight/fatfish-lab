# Task 1 · 本地算力护栏与 ModelRouter

> 实测时间：2026-10-29 14:00–14:20（真实墙钟）
> 代码：`task1_local/guard/`、`task1_local/router/`；测试 38 条全绿；真机压测数据 `reports/gpu_bench.json`
> 硬件：RTX 4060 Laptop，8188 MiB，驱动 565.90

## 0. 一句话结论

把"不许烧显卡"从口号变成三条真会执行的闸门：**显存预检拒绝**（7b 直接不给起）、
**全局串行队列**（20 并发实测 max_active=1）、**失败熔断降级**（本地崩了自动转云端）。
实测 3b 推理峰值 **2982 MiB = 36.4%**，红线 5732 MiB，余量充足。

## 1. 三条前提（不写清楚就是没写规格）

| 前提 | 事实 | 结论 |
|---|---|---|
| 显存**能**硬拦 | 预检 + `num_ctx` + 单模型 + 串行，四道都能落在代码里 | 红线只管显存 |
| 算力利用率**拦不住** | Ollama / llama.cpp 无算力限速参数；实测一次对话就把 util 打到 **96%**，而显存只用了 36% | 「GPU 利用率压 70%」做不到，只能告警 |
| 并发会让两个请求都变慢且叠加显存 | 同一张卡上两个 3b 推理互相抢 SM | 必须串行，排队超时降级云端 |

**这一节的第 2 条是原指令最大的坑**：如果真按"util > 70% 就拒绝"去实现，
那么每一次正常推理都会被自己拦掉（96% > 70%），护栏变成永动机式的自锁。

## 2. 结构

```
task1_local/
├── guard/
│   ├── gpu.py         nvidia-smi 采样（不装 pynvml）
│   ├── policy.py      显存红线：5732 MiB，模型运行态估量表
│   ├── monitor.py     利用率告警（连续 3 采样）+ 温度冷却（>86℃ 停 60s）
│   ├── queue.py       全局串行队列（信号量=1，排队超时抛 QueueTimeout）
│   └── local_llm.py   Ollama 客户端 + 每次调用前预检
├── router/
│   ├── rules.py       规则打分分类（长文本/代码块/外部知识/高并发）
│   └── router.py      超时降级 + 熔断（3 次失败开 60s）+ 串行闸门 + 降级链
├── tests/             38 条（guard 24 + router 14）
└── bench/
    ├── bench_gpu.py   真机五步：基线→预检→采样→真推理→卸载
    └── demo_router.py 端到端：真 3b + 降级 + 20 并发
```

## 3. 实测数据

### 3.1 基线（14:0x）

| 项 | 值 |
|---|---|
| 显存 | 876 / 8188 MiB（10.7%） |
| 利用率 | 28%（**在我们什么都没跑的时候就已经 28%**） |
| 温度 | 44℃ |
| 70% 红线 | 5732 MiB |
| 模型余量 | 4856 MiB |

### 3.2 预检表

| 模型 | 运行态估算 | 预计总占用 | 占 8188 | 判定 |
|---|---|---|---|---|
| `qwen2.5:3b` | 2500 MiB | 3376 MiB | 41% | ✅ 放行 |
| `qwen2.5:7b` | 5500 MiB | 6376 MiB | 78% | ❌ 拒绝 |
| `qwen2.5vl:7b` | 6700 MiB | 7576 MiB | 93% | ❌ 拒绝 |

### 3.3 真推理（Qwen2.5-3B-Instruct Q4_K_M，num_ctx=2048）

提示词："用三句话解释 B+ 树为什么比红黑树更适合存磁盘索引。"

| 指标 | 实测 |
|---|---|
| 输出 / 输入 | 91 tok / 52 tok |
| 生成速度 | **92.42 tok/s** |
| 墙钟 | 3.00 s |
| **峰值显存** | **2982 MiB（36.4%）** |
| 峰值利用率 | **96%** |
| 峰值温度 | 61℃ |
| 红线判定 | **PASS**（2982 ≤ 5732，余 2750 MiB） |
| 卸载后 | 879 MiB（比基线 +3 MiB，回位干净） |

估算 3376 vs 实测 2982：**偏保守 12%**，方向对（宁高勿低）。

### 3.4 端到端演示（`bench/demo_router.py`）

| 场景 | 降级链 | 耗时 |
|---|---|---|
| 短问答 | `route:local(score=0)` → `local:ok` | 0.56 s（真 3b 回答） |
| 需外部知识 | `route:cloud(score=2)` → `cloud:ok` | 0.20 s（stub） |
| 本地故障 | `route:local` → `local:error:RuntimeError` → `cloud:ok` | 0.19 s |
| 20 并发 | 全部 `local:ok`，`max_active=1` | 墙钟 2.2 s，均 1.17 s/个 |
| **过热（模拟 20℃ 线）** | `route:local` → `guard:thermal_cooldown` → `local:thermal_blocked(60s)` → `cloud:ok` | 0.20 s |

### 3.5 温度闸门接进 router（2026-10-29 16:5x 补完）

`ModelRouter(..., guard=PressureGuard(), sampler=GpuSampler())`：每次**要跑本地**之前采样一次、
把样本喂给守卫；守卫说在冷却（>86℃ 触发 60s）就跳过本地、走云端，链路里留
`guard:thermal_cooldown` + `local:thermal_blocked(<剩余>s)`，统计里记 `blocked.local`。

- 采样失败按 **fail-open** 放行本地，只留 `guard:sample_error:<异常名>` —— 不让 nvidia-smi 抽风把推理链打死。
- 冷却到期 + 温度真降下来才恢复本地（测试里专门验证：只让时钟走 61s、温度还在 91℃ 时**仍继续拦**，这是对的）。
- 新增 5 条用例：冷却中跳本地、不冷却照常本地、本地被拦且云端也死时抛 `AllTargetsFailed`（消息含 `thermal_blocked`）、真守卫+采样器进出冷却、采样异常不影响主链。`45 passed in 0.58s`。

### 3.6 顺带修掉的误拒 bug：暖机时重复计算自身显存

补闸门时在真机上发现本地通道被自己拦住：`VramRefused 预估总占用 5787 MiB 超出红线 5732 MiB`。
根因 `VramPolicy.check` 把 `used_mib`（nvidia-smi 的总占用，**已经包含**驻留的 qwen2.5:3b 的 2500 MiB）
又加了一遍模型估算值 → 暖机状态下每次命中都被误判超线，`ollama ps` 显示 `qwen2.5:3b 2.1 GB` 就是证据。

修法：`check(model, used_mib, already_loaded_mib=0)`，投影改成 `used + max(0, 估算 - 已驻留)`；
`OllamaClient.generate` 调 `/api/ps` 拿该模型 `size_vram` 传进去（查不到按 0，保持 fail-closed）。
冷启动该拒还是拒（`test_vram_policy_still_refuses_when_cold_load_breaks_line`）。

## 4. 验收对照（RFC §3.1 的四条）

| 验收项 | 证据 |
|---|---|
| 显存超限拒绝 | `test_seven_b_refused_over_line`、`test_unknown_model_fails_closed`、`test_tight_ratio_refuses_three_b`、`test_vram_policy_does_not_double_count_already_loaded_model`；真机预检把 7b 判 78% 拒绝 |
| 超时熔断 | `test_local_timeout_falls_back_to_cloud`（0.05s 超时 → 云端接手，链路留 `local:timeout`） |
| 连续失败降级 | `test_three_failures_open_circuit_then_half_open`（3 次失败开闸；60s 后半开放探针；探针再失败重新打开） |
| 并发 20 全串行 | `test_twenty_concurrent_calls_run_serially` + 真机 20 并发 `max_active=1` |
| **温度冷却真正生效** | `test_router_skips_local_while_cooling`、`test_router_samples_gpu_before_local_and_enters_cooldown`、`test_router_hard_fails_when_local_blocked_and_cloud_down`、`test_router_survives_sampler_error` |

`45 passed in 0.58s`。

## 5. 踩坑（都是花钱/花时间换的）

1. **`threading.Semaphore.acquire(timeout=-1)` 不是无限等**：CPython 里 `remaining <= 0` 直接 `break` 返回 False，等于"立刻就超时"。表现是 20 并发全部 `QueueTimeout`、链路里出现 `local:circuit_open`。修法：无限等必须走不带 timeout 的那个分支。
2. **Ollama 官方 registry 在国内不稳**：`ollama pull qwen2.5:3b` 走到 93%（1.8/1.9 GB）卡住，速度从 772 KB/s 掉到 **1.8 KB/s**，ETA 从 3 分钟变成 2 小时。改走 `hf-mirror.com` 下官方 GGUF（**7.62 MB/s**），再用 `ollama create` 建点位，5 分钟到位。
3. **`ollama list` 显示"已装"不代表能跑**：manifest 写进去了、blob 没收全时也会出现在列表里，真正的判据是 `/api/generate` 返回是否带 `error`。
4. **Windows 上 `os.pread/os.pwrite` 不存在**（Task 2 已踩，这里复用同一套封装思路）。

## 6. 能力边界（别把"能跑"吹成"完备"）

- `num_ctx` 固定 2048：上下文越长 KV 越大，实测 2048 下峰值 36%，若将来要开到 8192 必须重跑预检表，不能沿用 2500 MiB 这个数。
- 云端通道目前是 stub：`demo_router.py` 里的 `cloud_stub` 只演示降级链，真实云端调用（token 计费、prompt 组装）留给 P4 的编排器统一做。
- ~~温度冷却只在 `guard` 层提供布尔闸，还没接进 router~~ → **已接**（见 3.5）：`ModelRouter(guard=, sampler=)`，冷却中本地被拦并自动降级云端。
- 温度闸门只拦 `local`：云端不过问（云端不占本机显存，拦它没意义）。
- Ollama 自身没有"限算力"参数，所以本报告里的"护栏"始终是**准入控制**，不是**运行时限速**。

## 7. 复跑命令

```powershell
cd .\task1_local
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python.exe -m pytest -q          # 45 passed
..\.venv\Scripts\python.exe -m bench.bench_gpu    # 真机五步，写 reports/gpu_bench.json
..\.venv\Scripts\python.exe -m bench.demo_router  # 端到端降级 + 20 并发 + 温度闸门
```
