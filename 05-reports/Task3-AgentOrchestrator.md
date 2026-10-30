# Task 3 · AgentOrchestrator（Dev / QA 双角色对抗）

> 2026-10-29 18:2x · `.\task3_orchestrator\`
> 状态：**mock 模式全绿**（17 用例 + 端到端演示 2 轮收敛）；live 模式未跑（需显式确认花费）

---

## 1. 结论

编排器跑通了，而且**判定权不在 LLM 手里**：

- Dev 改代码、QA 写测试，两个角色各自是**独立子进程**（独立家目录、独立环境变量、互不可见）；
- "做完了没有"只由 **pytest 退出码**回答，QA 写不出通过就只能继续吵；
- 三重熔断（轮数 ≤6 / 墙钟 ≤15 min / token ≤200K）在**每一轮开头和每次模型调用后**检查，超了立刻停并如实报状态（`rounds_exhausted` / `time_exhausted` / `budget_exhausted`），**不会把"预算耗尽"报成"成功"**；
- 连续 2 轮失败用例集一模一样 → 判 `stalled`（卡死），提前止损而不是烧满 6 轮。

演示是拿 Task 2 的 `BPlusTree` 当题目的：第 1 轮 Dev 只加了 `range_delete`，QA 的 5 条测试里 2 条要 `__iter__` → 红；第 2 轮补上 → 绿。**2 轮收敛，12,500 token，1.3 秒**（mock 不烧钱）。

## 2. 三条前提（不满足就不用往下看）

1. **"全绿"必须能被机器判定。** 让 LLM 自评"我觉得可以了"是真空话，也没法审计。这里把判定权收窄成 `pytest` 的 `returncode == 0`，附带解析出失败用例 ID 用于卡死判定。代价：题目必须可测；纯架构/风格类任务不适用。
2. **先跑假人再跑真人。** 编排逻辑的 bug（隔离没做好、熔断不触发、日志串味）和"模型水平"无关，用脚本化假人就能暴露，成本 0。真人模式只在假人全绿后才开，且要显式 `--i-know-the-cost`。
3. **子进程隔离要"物理"而不是"约定"。** 两个角色不能读到对方的 prompt，否则 QA 会照着 Dev 的思路写测试（自己考自己）。做法：各自 `tempfile.mkdtemp()` 家目录、只注入自己的环境变量、`cwd` 都指向同一工作区但只写自己的文件。

## 3. 结构

```
task3_orchestrator/
├── orchestrator/
│   ├── budget.py      # Caps（6 轮/900s/200K）+ Budget 记账与三种耗尽异常
│   ├── workspace.py   # 共享工作区：安全相对路径、快照、起始代码拷贝、清理
│   ├── judge.py       # 唯一裁判：跑 pytest、清 __pycache__、解析失败用例 ID
│   ├── agent.py       # 角色 = 子进程（AgentSpec/Agent/AgentResult），环境变量白名单
│   ├── loop.py        # 主循环：Dev → QA → 判决 → 记账 → 熔断/卡死判定
│   └── cli.py         # 命令行；live 模式三道闸
├── tests/
│   ├── test_orchestrator.py   # 17 个用例
│   └── agents/mock_agent.py   # 按 script.json 演戏的假人
└── demo/run_mock_demo.py      # 拿 Task 2 的 B+ 树当题目跑一遍
```

角色收到的环境变量只有六个：`DSH_AGENT_NAME` / `DSH_AGENT_HOME` / `DSH_WORKSPACE` / `DSH_ROUND` / `DSH_PROMPT_FILE` / `PYTHONIOENCODING`。**对方的家目录一个都不给**——测试里专门有一条 `test_agent_homes_are_separate_and_not_leaked` 去环境里翻，翻到就挂。

## 4. 实测

### 4.1 端到端演示（mock，0 成本）

题目：给 `BPlusTree` 加 `range_delete(lo, hi)` 闭区间批量删除 + 可 `for` 迭代（升序）。

| 轮 | Dev 做了什么 | pytest | 失败用例 |
|---|---|---|---|
| 1 | 只加 `range_delete` | 红（rc=1） | `test_iter_is_sorted`、`test_iter_after_delete` |
| 2 | 补 `__iter__` | 绿（rc=0，0.45s） | — |

```
状态：passed
  #1 dev=ok qa=ok pytest 红（rc=1）… tokens=6800
  #2 dev=ok qa=ok pytest 全绿（rc=0, 0.45s） tokens=5700
用量：12500 token / 1.3s / 2 轮
```

### 4.2 单测矩阵（17 个）

| 组 | 覆盖 |
|---|---|
| 预算 3 | 轮数耗尽、墙钟耗尽、token 耗尽（且异常里带 `reason`） |
| 工作区 1 | 拒绝绝对路径与 `..` 逃逸 |
| 裁判 3 | 全绿判通过、红判不通过且拿到失败 ID、**exit 5 无测试判红** |
| 主流程 6 | 1 轮收敛、多轮收敛、轮数耗尽、卡死判定、QA 崩了、Dev 崩了 |
| 隔离 1 | 两个角色家目录互不可见、环境变量不泄漏 |
| CLI 3 | live 无 `--i-know-the-cost` 拒启动、有开关但缺命令也拒、mock 能造出两个角色 |

另有一条 `test_judge_not_fooled_by_stale_bytecode`：故意造 `__pycache__` 再写"同大小"坏代码，断言判决必须变红（见踩坑 3）。

## 5. 验收对照（RFC §3.3 逐条）

| 要求 | 落点 | 证据 |
|---|---|---|
| 角色隔离、独立子进程、独立 prompt | `agent.py` + `loop.py` | 隔离用例 + 演示里 dev/qa 各自 home |
| ≤6 轮 | `Caps.max_rounds` | `test_max_rounds_exhausted` |
| ≤15 min | `Caps.wall_clock_s=900` | `test_wall_clock_exhausted` |
| ≤200K token | `Caps.token_budget=200_000` | `test_token_budget_exhausted` |
| 判定权只给 pytest 退出码 | `judge.py` + `RunReport.passed` | 裁判 3 条用例 |
| 连续 2 轮无变化判卡死 | `Orchestrator(stall_repeats=2)` | `test_stalled_when_failure_set_repeats` |
| mock 0 成本先全绿 | `tests/agents/mock_agent.py` | 17 用例 + 演示 |
| live 需显式确认花费 | `cli.py` 三道闸 | CLI 3 条用例 |

## 6. 踩坑（三个，第三个最值钱）

1. **Windows 反斜杠让快照对不上。** `Path.rglob` 给 `bplus\memory.py`，快照/日志两处按不同写法比较就永远"看起来变了"。统一 `as_posix()` 存键。
2. **测试剧本自己写错。** 想让"轮数耗尽"发生，结果三轮的坏代码挂的是同一组测试 → 被正确判成 `stalled`。这提醒我：卡死判据会和"测试题太窄"打架，写剧本时必须让每轮失败集真的不同。
3. **`.pyc` 会用旧字节码判决。** CPython 校验缓存只比 `(mtime 秒级, 文件大小)`。Dev 在同一秒内写出**大小相同**的新源码（`return 55` → `return -1`，都是 31 字节）时，解释器直接复用上一轮的字节码 —— **pytest 判的是旧代码**，表现为"我明明改对了却还是红"。修法：`run_pytest` 开头 `purge_bytecode(cwd)` 清 `__pycache__`，并留了回归用例锁住它。
4. **本机系统 Temp 目录对 Python 是坏的。** `%LOCALAPPDATA%\Temp` 能建目录，但 Python 在里面 `mkstemp()` **会挂住不返回**（用 PowerShell 建目录却正常，所以很容易误判成"测试慢"）。后果是 `tempfile.gettempdir()` 回落 cwd，pytest 的 `tmp_path` 和 Agent 家目录全建进仓库，`git add` 一不小心就把它们提交了（我这次就提交了一次，靠 `--amend` 清掉）。修法：`orchestrator/tmpdir.py` 统一指到项目内 `.tmp/`，三个 `conftest.py` 里连 `tempfile.tempdir` 缓存一起改（pytest 启动早期已经算过一次，只改环境变量不够）。

## 7. 能力边界（别把它当"能自己写软件"）

- mock 模式证明的是**编排正确**，不是"模型能用"。live 模式没跑过，跑之前没法承诺成功率。
- 卡死判据只看"失败用例集是否完全相同"。换了错法但同样错，会一直重试到轮数耗尽——这属于预期，靠预算兜底。
- Dev/QA 的 prompt 是通用的，没有针对具体语言/框架做特化；复杂题目应该由人拆题，而不是让它自己拆。
- 工作区是临时目录，跑完即删（`--keep` 保留）。**不碰真实仓库**，这是刻意的：让它在你的项目目录里自由改代码太危险。
- 临时目录一律在项目内 `.tmp/`（可用 `DSH_ORCH_TMP` 改），**不用系统 Temp** —— 本机那份对 Python 是坏的（见踩坑 4）。

## 8. 复跑

```powershell
cd .\task3_orchestrator
..\.venv\Scripts\python.exe -m pytest -q            # 17 passed
..\.venv\Scripts\python.exe demo/run_mock_demo.py   # 2 轮收敛
..\.venv\Scripts\python.exe -m orchestrator.cli --task "给 X 加 Y"   # mock 跑真 CLI
```

live（**会花钱，需显式确认**）：

```powershell
$env:DSH_LIVE_DEV_CMD = "<真正能调模型的命令行>"
$env:DSH_LIVE_QA_CMD  = "<同上>"
..\.venv\Scripts\python.exe -m orchestrator.cli --mode live --i-know-the-cost --task "..."
```
