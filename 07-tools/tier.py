#!/usr/bin/env python3
"""开工前报数：这活有多少、手里有什么能用。

**不猜档位**——档位是报数的副产品：
  报不出数 → 说明还没看够，先去查
  数出来了 → 数量 × 单件 摆在那儿，档位自己会说话

用法：
  py lab.py tier "把这 4,545 个插件全过一遍"
  py lab.py tier "修 DSH-Ledger-Collect 失败" --no-assets

判据全部来自任务描述里的**字面信息**，不是我脑补的规模。

2026-11-11 第 0 步拆成四个文件（每步都跑过契约基准 + 188 tests + selfcheck）：
  tier_domains.py  域数据 PATH_OPTIONS
  tier_matcher.py  域匹配 / 跨域组合 / 清单体检
  tier_judge.py    数量词 / 档位判定
  tier.py（本文件）facade 重导出 + 渲染层 + main
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from tier_domains import PATH_OPTIONS  # noqa: F401  （facade：名字必须留在本模块）
# 只重导出**有人用**的名字（tests / lab.py / SKILL.md 会点名的）；
# 其余词表留在各自模块里，需要时直接 import 那个模块。
from tier_matcher import (  # noqa: F401
    AUX_MAP,  # 契约基准脚本 tier-baseline.py 会读它
    CHAINS,
    COMBOS,
    REST_THRESHOLD,
    RULE_CLOSING,
    RULE_OPENING,
    RULE_SIGNALS,
    cap_hints,
    chain_deviate,
    chain_hygiene,
    chains_for,
    combo_hits,
    load_chains,
    path_options,
    record_chain,
    route_hygiene,
    rule_hits,
    verify_evidence,
)
from tier_judge import (  # noqa: F401
    VISUAL,
    extract,
    judge,
)

# matcher 读 PATH_OPTIONS 一律经本模块取 → monkeypatch.setattr(tier, 'PATH_OPTIONS', fake) 才生效。
# 用注册而不是 `import tier`：测试会用 importlib 以别的模块名加载 tier.py。
import tier_matcher as _matcher  # noqa: E402

_matcher.set_lib(globals())

# 每次 lab tier 调用记一行——**不靠我记得写**，这是「自然而然更新」的数据底座。
# 与 ~/.dsh/lab-calls.log 同目录同格式（jsonl），多两个字段：命中哪些域、共几条路线。
TIER_CALLS = Path.home() / '.dsh' / 'tier-calls.jsonl'
# 2026-11-15 用户 m04361 定：先准、再稳、最后快，且不许把机制做臃肿。
# tier-calls 记「哪句话命中了哪个域」，但不知道我最后选了哪条——所以
# 「哪条路线从没被用过」判不了。这里只加一个极小的回写口：
#   lab tier --used 3D/P   → 往 tier-picks.jsonl 追加一行，不碰历史记录。
TIER_PICKS = Path(r'D:\work\架构文档\路线库配套\选路记录.jsonl')
# 每个任务域会用到的「元操作 / 附属工具」——它们不构成「同一任务的几条路」
# （present 不是一条路，是「怎么把结果给你看」），但少了它们同样会「想不起来」。
# 2026-11-07 用户 m11658：「我真的想要它包含你的一切，因为只有基于你自身的一切，
# 才能得出当前的最优解。」→ 主线归 routes，配角归 aux，两者合起来才是完整的能力图。
# ══════════════════════════════════════════════════════════════════════════
# 知识索引：这个任务该去翻哪份东西
# ══════════════════════════════════════════════════════════════════════════
# 用户 2026-11-07 m13259：「一个解决方案里面，往往可能就会涉及到多个能力，
# 域，技能，知识，这样都有的。」——能力和工具回答「我能做什么」，
# 知识回答「我以前学到过什么、别人踩过什么坑、该抄哪个模板」。
#
# **路径必须真实存在**：这里只写已经在磁盘上验证过的文件。
# 记忆里写着但磁盘上没有的，不许写进来（2026-11-07 实测 `架构文档\长板收据规则.md`
# 在记忆里有、磁盘上 28 个 md 里没有——那条记忆是错的，不能当知识源）。
# 值的格式：(说明, 相对 D:\work 的路径 或 None)，None 表示用命令现查。
_KNOWLEDGE = {
    "编码 / 乱码": (
        ("速查表 15 条最痛坑（第 ① ② 条就是编码/BOM）", "学习计划/01-编程/知识库/00-速查表.md"),
        ("`lab encoding --list` 的已知坑表", None),
    ),
    "排查 / 长日志归因": (
        ("坏了从哪查：按症状查故障表", "架构文档/坏了从哪查.md"),
        ("本质问题清单：15 个层面的根因与判据", "架构文档/本质问题清单.md"),
    ),
    "改插件 / 部署 / 装东西": (
        ("坏了从哪查 §2.4 已装插件故障表", "架构文档/坏了从哪查.md"),
        ("外来插件掌控表：cc-safety-net / dsh-ops / bili 的实测判据", "架构文档/外来插件掌控表.md"),
    ),
    "视觉 / 界面 / 截图验收": (
        ("rainy-store 的 verify.mjs：CDP + 契约钩子的视觉验证器模板", "实验/rainy-store/verify.mjs"),
    ),
    "3D / 建模 / 渲染": (
        ("同上：verify.mjs 是视觉交付的验证器模板（别一张一张看图）", "实验/rainy-store/verify.mjs"),
    ),
    "长期机制 / 制度建设": (
        ("我的路线图：三阶段 会读 / 会扛 / 有用", "自进化/路线图.md"),
        ("迭代章程：§0.5 指令吸收 / §0.7 L4 自觉与留痕", "自进化/迭代章程.md"),
    ),
    "记忆管理": (
        ("记忆库优化规则：字符才是硬指标，条数只是近似", "自进化/记忆库优化规则.md"),
        ("记忆与流程的分工：能写成流程的绝不只写记忆（A/B/C 三档）", "架构文档/记忆与流程的分工.md"),
    ),
    "成本 / 预算 / 上下文": (
        ("API 计费时段：四个价档边界 9/12/14/18 点", "自进化/API计费时段.md"),
    ),
    "写代码 / 改代码": (
        ("知识库 INDEX：踩过的坑、速查表、读码笔记入口", "学习计划/01-编程/知识库/INDEX.md"),
        ("学习路线图：第 3 批工程实践 / 第 4 批综合项目待开始", "学习计划/01-编程/学习路线图.md"),
    ),
    "找资料 / 调研": (
        ("插件库 4,545 条一句话摘要（造轮子前先搜）", "插件库/one_liner.json"),
    ),
    "自我体检": (
        ("能力快照：`lab capsnap` 从真值生成（子命令 / 插件版本 / 路线域条数 / 记忆条数），"
         "文档里不写死数字、写「见快照」", "架构文档/能力快照.json"),
    ),
    # 2026-11-07 第二轮补：这 12 个域原来一句知识源都没有。
    # 原则不变——只写磁盘上真有的；没有静态文档的就写 None，并说清用哪条命令现查。
    "图片 / OCR / 看图理解": (
        ("先 `lab ocr`（本地免费 0.6 秒）再 `vision_describe`；精确数小图标/小字直接 `read_image`（vision 会看漏）", None),
    ),
    "测试 / 回归 / 交付验收": (
        ("`_mutation_check.py`：回滚验证模板——把修复注释掉，对应测试必须变红才算真测试", "tools/lab/tests/_mutation_check.py"),
        ("速查表 ⑬⑮：断言别凭印象数、改前备份改后独立验证", "学习计划/01-编程/知识库/00-速查表.md"),
    ),
    "写文档 / 报告 / 笔记": (
        ("知识库 INDEX：踩过的坑、速查表、读码笔记的入口", "学习计划/01-编程/知识库/INDEX.md"),
    ),
    "会话检索 / 找以前的对话": (
        ("`session_grep.py`：zstd 必须 stream_reader 流式解（decompress 只处理单帧，会读出 193 B 假象）；--raw 是绕过索引的基准线", "tools/lab/session_grep.py"),
    ),
    "开发协作 / 拆活": (
        ("Agent Teams 容量是**整棵树合计**不是每层一份（现 10 并发 / 深度 1），满了直接拒绝不排队", None),
    ),
    "备份 / 恢复 / 回滚": (
        ("备份按类分目录（`E:\\DS公作区\\备份\\`）；改插件前 `lab deploy` 必留备份", "备份"),
    ),
    "桌面 / 浏览器操作": (
        ("`lab cdp` 走 CDP 不抢焦点；`lab desktop` 坐标按物理分辨率（本机 2560×1440，逻辑 1707×960）", None),
    ),
    "音频 / 视频": (
        ("剪映自带 ffmpeg 可抽帧/转码/取时长（`E:\\JianyingPro\\11.6.0.14552\\ffmpeg.exe`）", None),
    ),
    "安全 / 拦截": (
        ("外来插件掌控表 §4：cc-safety-net 五族规则、三档 standard/strict/paranoid、跑前用 `explain` 自查", "架构文档/外来插件掌控表.md"),
    ),
    "GitHub / 对外发布": (
        ("`release-plan.txt`：发布清单 + 三层脱敏 + 8 类凭证扫描必须 0 命中", "tools/lab/release-plan.txt"),
    ),
    "本地模型": (
        ("edge-lab README：3B 是**形状识别器不是语义判断器**（长日志归因 8/8、判断语义对应 60%）；GPU 90% 红线 = 7369 MiB", "tools/edge-lab/README.md"),
        ("本机 RTX 4060 Laptop **8GB**：1B 级 LoRA/QLoRA 可跑（`dsh-fine-tune` 门槛 6GB）；7B 全量/QLoRA 需 16-24GB，本机做不了；训练前先算显存账（2026-11-11 实测 nvidia-smi 8188 MiB + 插件市场描述）", None),
    ),
    "科学计算 / 数值模拟 / 数据分析": (
        ("第 25 域 2026-11-07 新加（起因：量子纠缠态蒙特卡洛 3 次空命中），暂无静态文档", None),
    ),
    "Git / 版本控制 / 仓库管理": (
        ("第 26 域 2026-11-08 新加（起因：判断「读码笔记不在版本控制里」判错——只查 .gitignore，"
         "实际在嵌套仓库；用户 m15594 点破「有没有加进候选路线库」），暂无静态文档", None),
    ),
    # 2026-11-07 补：这两个域其实是同一天 54 分钟里最该翻的两本书，
    # 但原来一句知识源都没写——所以「知识源」这张表第一版就漏了最关键的两个。
    "自动化 / 定时 / 无人值守": (
        ("计划任务现状用 `env_doctor only=all` 现查（静态盘点已退场：任务全在 env_doctor 的检查里，"
         "再留一份快照只会在某次 grep 里冒充真相）", None),
        ("坏了从哪查：静默失败 / 结果码含义 / 8 个经典形状", "架构文档/坏了从哪查.md"),
    ),
    "下载 / 网络 / 换源": (
        ("`lab nettest` 现测各源（GitHub / npmmirror / 官方站）的吞吐再决定", None),
        ("没有静态文档，但铁律在速查表：先测三个源再下载", "学习计划/01-编程/知识库/00-速查表.md"),
    ),
    "开源社区协作": (
        ("第 27 域 2026-11-08 新加（起因：用户 m15707 让我进 GitHub 开源社区，"
         "盘点发现没有一个域是「在别人的社区里生活」）——三家上游 PR 的实操记录见 fatfish-lab 的 08-oss-contribution/", None),
        ("ollama-python / python-docx 的 CONTRIBUTING 与测试约定", "repos/python-docx/pyproject.toml"),
    ),
    "代码考古 / 理解陌生仓库": (
        ("读码笔记四篇：httpx / CPython dict / ollama-python / python-docx BDD 遗产",
         "学习计划/01-编程/读码笔记/"),
        ("第 28 域 2026-11-08 新加（同上），暂无专门的「半小时看懂仓库」文档", None),
    ),
    "系统建模 / 结构化理解": (
        ("C4 model 官方站（四层抽象 + review checklist）https://c4model.com/ ； "
         "OLAF 的从代码反推 DFD 四阶段 https://github.com/AmadeusITGroup/olaf/blob/main/docs/dfd-from-code.md",
         None),
        ("自己画过的样例：lab pre 链路数据流", "学习计划/01-编程/读码笔记/2026-11-10-lab-pre-数据流.md"),
    ),
    "长期跟踪 / 外部反馈": (
        ("第 29 域 2026-11-08 新加（同上），暂无静态文档——"
         "被拒原因要归档成盲区清单，见学习计划/01-编程/读码笔记/", None),
    ),
}
def knowledge_for(domains) -> list[tuple[str, str, str | None]]:
    """把命中的域翻成「该去看哪份知识」。返回 [(域, 说明, 绝对路径或 None)]。"""
    root = Path(__file__).resolve().parent.parent.parent
    out = []
    for d in domains:
        for desc, rel in _KNOWLEDGE.get(d, ()):
            out.append((d, desc, str(root / rel) if rel else None))
    return out
# ── 不构成路线的资产 ──
# 2026-11-08 用户 m15911 问「所有插件（外来/自造/官方内置/实验性）有没有都在路线库里」，
# 查完（见 D:\work\架构文档\插件能力上限.md）的结论：
# **不是所有东西都该是「路」**——路线库回答「这件事有几种做法」，而换背景图、启动动画、
# 桌宠、守卫这类东西没有第二种做法，塞进去会让域开始注水（看起来全，实际不管用）。
# 但「我有什么」也不能散——所以留这张表，`lab tier --inventory` 打印。
NON_ROUTE_ASSETS = [
    # (插件, 类型, 为什么不构成路线)
    ("@local/dsh-workflow-skill", "规则层", "提供 SKILL.md（§0 主规则 + 工具表）；规则的位置在 §0，不在路线库"),
    ("@tt-a1i/archify-dsh", "技能包", "archify 已作为 08 域 E 路线在库里；包本身是 skill-only"),
    ("dsh-chat-background", "界面", "换背景没有第二种做法，不是「路」"),
    ("dsh-stickers", "界面", "表情选择不是任务路；08 域 AUX 已收它"),
    ("dsh-startup-screen", "界面", "启动动画不是任务"),
    ("dsh-session-delete", "危险动作", "只删不恢复，没有第二种做法；且是不可逆动作，路线库不该鼓励"),
    ("dsh-pocket", "界面+网络", "用户已停用"),
    ("@dsh-pet/bridge", "界面", "桌宠不是任务"),
    ("dsh-context", "展示", "回答「现在装了多少」，不回答「该走哪条路」"),
    ("dsh-fail-guard", "守卫", "连续失败才停手，是行为约束不是可选路线；和 dsh-self-guard 同类（后者在 20 域）"),
]
REPORT = Path(r"D:\work\架构文档\路线库体检报告.md")
HINT_WINDOW_S = 12 * 3600
def health_hint() -> None:
    """有新体检报告时打一行。只读 mtime，不写 state——零副作用，绝不拖慢开工。"""
    try:
        if not REPORT.exists():
            return
        age = datetime.now().timestamp() - REPORT.stat().st_mtime
        if age > HINT_WINDOW_S:
            return
        hours = max(1, int(age // 3600))
        print(f"📋 路线库体检报告 {hours} 小时前生成过：`lab health --force` 重看（假域/空命中/高频低权）")
        print()
    except Exception:
        pass
def record_call(text: str, opts: list[dict]) -> None:
    """每次 lab tier 调用记一行——**不靠我记得写**，这是「自然而然更新」的数据底座。

    `lab tier` 是开工第一步、必然跑到，所以它记的东西不依赖我的注意力。
    失败绝不能影响开工，整个函数吞掉异常。
    """
    try:
        rec = {
            'at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            # 会话 id 让「开工闸」能按会话判断跑没跑过（dsh-self-guard 的 tierGate 读它）。
            # 拿不到就写空串——闸那边对空串一律放行，宁可漏拦也不误伤。
            'sessionId': os.environ.get('DSH_SESSION_ID', ''),
            'task': text[:80],
            'domains': [o['domain'] for o in opts],
            'routes_n': sum(len(o['routes']) for o in opts),
        }
        with TIER_CALLS.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001
        pass
def count_subcommands() -> int:
    """数顶层子命令：优先运行时取 build_parser() 的 choices。

    2026-11-17 修：原来只扫 lab.py 源码里的 set_defaults(func=cmd_xxx)，
    看不见外部模块（如 img.py）register(sub) 注册的子命令 —— lab img 就是这么漏的（数出 48 实际 49）。
    和 selfcheck.lab_subcommands() 同一个病，同一个修法。"""
    try:
        import argparse  # noqa: PLC0415
        import lab as _lab  # noqa: PLC0415
        for act in _lab.build_parser()._actions:
            if isinstance(act, argparse._SubParsersAction):
                return len(act.choices)
    except Exception:  # noqa: BLE001
        pass
    try:
        src = (Path(__file__).resolve().parent / 'lab.py').read_text(encoding='utf-8')
    except Exception:  # noqa: BLE001
        return 0
    return len(re.findall(r"set_defaults\(\s*func=cmd_", src))
def related_assets(text: str, top: int = 5):
    """从 assets 扫描结果里挑名字出现在任务描述里的（或体积最大的几个）。

    **2026-11-19 加缓存**：cProfile 实测 `lab tier` 2.3 秒里有 **1.84 秒**是
    `assets.scan()` 在扫 59 个目录（`nt.scandir` 25,882 次）——`dir_size()` 和
    `newest_mtime()` 各占 0.9 秒。而 `lab tier` 是**开工第一步最常跑的命令**
    （705 次调用），每次白扫 1.8 秒。
    资产状态变化很慢（目录大小、文件数），所以缓存 1 小时；命中缓存时这条路径
    从 1.8 秒降到 ~5 毫秒。缓存坏了/过期了自动重扫，不影响正确性。
    """
    cache = Path(__file__).resolve().parent / ".cache" / "assets-scan.json"
    rows = None
    try:
        if cache.exists() and (time.time() - cache.stat().st_mtime) < 3600:
            rows = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 缓存坏了就当没有，重新扫
        rows = None
    if rows is None:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import assets as assets_mod  # noqa: PLC0415
            rows, _total = assets_mod.scan(1.0)
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            except Exception:  # noqa: BLE001 — 写缓存失败不该影响结果
                pass
        except Exception:  # noqa: BLE001
            return []
    hits = []
    for row in rows:
        name = row.get("name") or ""
        if name and name in text:
            hits.append(row)
    if hits:
        return hits[:top]
    # 没命中就退回"最大的几个"——至少让用户知道手边有哪些大件
    rows_sorted = sorted(rows, key=lambda r: -(r.get("size") or 0))
    return rows_sorted[:top]
def fmt_bytes(n):
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
def now_line() -> str:
    """一行时间：日期 + 星期 + 现在几点 + 当前价档 + 距下一个价档边界多久。

    用户 2026-11-08 m14102 原话：「你对时间。关键还是太差了。把对时间观念。的验证写进流程里吧。」

    为什么写在这里、不写进记忆：
    我一天内错了两次——把周日说成「14:00 转高峰价」（周日全天半价、没有高峰），
    把 18 天说成「这三个月」。`mem_mvq9ru22_9jiphv` 那条「说时间先核时间戳」早就在库里，
    但它要我先想起来去查。`lab tier` 是每轮开工必跑的命令，把时间印在它的第一屏，
    就变成「不看也能看到」的副产品——这是流程，不是记忆。

    价档规则（官方口径，2026-10-27 抓取）：
    高峰 = 周一至周五 9:00–12:00、14:00–18:00（不含法定节假日）；
    其余全部空闲（半价）：18:00–次日 9:00、12:00–14:00、周末全天、节假日全天。
    """
    n = datetime.now()
    wd = "一二三四五六日"[n.weekday()]
    weekend = n.weekday() >= 5
    peak = (not weekend) and (9 <= n.hour < 12 or 14 <= n.hour < 18)

    if weekend:
        state = "周末·全天空闲价（半价）"
        # 周末没有价档边界，不用提示「还剩多久到高峰」
        tail = ""
    else:
        state = "高峰价" if peak else "空闲价（半价）"
        nxt = None
        for bh, kind in ((9, "高峰"), (12, "空闲"), (14, "高峰"), (18, "空闲")):
            if bh > n.hour:
                nxt = (bh, kind)
                break
        if nxt:
            bh, kind = nxt
            mins = (bh - n.hour) * 60 - n.minute
            tail = f" · 距 {bh:02d}:00 转{kind}还有 {mins // 60}h{mins % 60:02d}m"
        else:
            tail = " · 今天已无价档边界"

    return f"现在 {n:%Y-%m-%d} 周{wd} {n:%H:%M} · {state}{tail}"
def _writeback_reminder() -> None:
  """查了 665 次只回写 15 条——没有那一行逼我回答。

  2026-11-18 加：`lab tier` 原来把候选列完就结束，我顺手就忘了回写。
  这里在输出末尾补一行：距上次 pick 超过 24 小时（或从没 pick 过）就提醒一次。
  不阻塞、不强制，但必须出现在输出里——否则又是「有动作、无出口」。
  """
  import json as _json
  from datetime import datetime as _dt
  path = Path(r'D:\work\架构文档\路线库配套\选路记录.jsonl')
  if not path.exists():
    return
  try:
    raw = path.read_text(encoding='utf-8')
  except Exception:
    return
  last_at = None
  for line in raw.splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      rec = _json.loads(line)
    except Exception:
      continue
    if rec.get('event') == 'pick' and rec.get('at'):
      last_at = rec['at']
  hours = None
  if last_at:
    try:
      hours = (_dt.now() - _dt.fromisoformat(last_at)).total_seconds() / 3600.0
    except Exception:
      hours = None
  if hours is not None and hours < 24:
    return
  if hours is None:
    print("【提醒】选路记录里还没有任何一条 pick —— 这次选了哪条？")
  else:
    print("【提醒】上次回写路线是 {0:.0f} 小时前 —— 这次选了哪条？".format(hours))
  print("    lab tier --used <域>/<代号> --note \"一句心得\"")
  print("    都不合适：lab tier --used none --note \"这次按常规走，无新判据\"")
  print()


def _chain_cmd(a) -> int:
    """`lab tier --chain record|deviate …`：经验链的写入口（闸门在这，打印在【5a】）。"""
    if a.chain == "deviate":
        if not a.chain_name:
            print("deviate 需要 --chain-name（要偏离的是哪条链）")
            return 1
        ok, msg = chain_deviate(a.chain_name, a.chain_reason)
        print(("✓ " if ok else "✗ ") + msg)
        return 0 if ok else 1
    tags = [t.strip() for t in a.chain_tags.split(",") if t.strip()]
    ok, msg = record_chain(name=a.chain_name, tags=tags, how=a.chain_how,
                           crit=a.chain_crit, chain_tier=a.chain_tier,
                           task=a.task, commit=a.chain_commit or None,
                           file=a.chain_file or None)
    if ok:
        print(f"✓ 链「{a.chain_name}」已回写（证据核验过：{msg}）→ 下次同域任务在【5a】里看得到")
        return 0
    print(f"✗ 闸门拒绝：{msg}")
    print("  这不是小工具坏了，是设计如此：**没验证过的路不许进库**（案底 mem_mw24413n）。")
    print("  真验证过了就带证据来：--chain-commit <sha> 或 --chain-file <证据文件路径>")
    return 1


def main() -> int:
    # Windows 默认 GBK 控制台：`lab tier` 输出里的 ⚠️ 之类字符会直接崩
    # （2026-11-11 实测 UnicodeEncodeError: 'gbk' codec can't encode '\u26a0'
    #  at print("  ⚠️ 缺的：")，位置 :2171 附近）。
    # 在入口处统一改成 UTF-8，别让调用方靠 PYTHONIOENCODING 环境变量绕过去。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="开工前报数：这活有多少、手里有什么能用")
    ap.add_argument("task", nargs="?", default="", help="任务描述（一句话）；用 --inventory 时可不给")
    ap.add_argument("--no-assets", action="store_true", help="跳过资产扫描（快 1 秒，但没推荐）")
    ap.add_argument("--inventory", action="store_true", help="打印「不构成路线的资产」清单（不是路，但也别丢）")
    ap.add_argument("--full", action="store_true",
                    help="路线每条都展开（默认每域前 3 条展开，其余只列标题——2026-11-17 改成默认短，因为一次任务常命中 2-3 个域、每条 4 行，全展开超 200 行没人读得完）")
    ap.add_argument("--audit", action="store_true", help="路线清单体检：重复/死路径/空壳/代号，以及哪些域该休整了")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--used", default="", metavar="域/代号",
                    help="事后回写：这次实际选了哪条路线（如 3D/P 或 P），只追加一行到 tier-picks.jsonl")
    ap.add_argument("--note", default="", metavar="一句心得",
                    help="配合 --used：这条路让我意外的地方（好在哪/坑在哪）。只在意外时写，不用每次")
    # 经验链回写（2026-11-13）：链只有过了证据闸门才能进库——账本我手写，
    # 而我有「把打算写成已完成」的案底（mem_mw24413n），所以自述不收，让 git/磁盘替我验。
    ap.add_argument("--chain", choices=["record", "deviate"],
                    help="经验链：record=验证过的组装回写进库（必带证据）；deviate=某条链被更好的组装打穿，记一票")
    ap.add_argument("--chain-name", default="", help="链名（record 必填 / deviate 要一致）")
    ap.add_argument("--chain-tags", default="", help="域短标签，逗号分隔（匹配规则同 COMBOS：子串即中）")
    ap.add_argument("--chain-how", default="", help="串法：哪步先行、哪步让哪步不用做")
    ap.add_argument("--chain-crit", default="", help="怎么算成了（判据）")
    ap.add_argument("--chain-tier", default="", help="验证时的档位（T1/T2/T3），不同档位别照搬")
    ap.add_argument("--chain-commit", default="", help="证据①：git 里查得到的 commit 号（git cat-file 核验）")
    ap.add_argument("--chain-file", default="", help="证据②：磁盘上真实存在的证据文件路径")
    ap.add_argument("--chain-reason", default="", help="deviate 时写清这次的替代组装好在哪")
    a = ap.parse_args()
    if a.used or a.note:
        # 一次只写一行，除格式外的校验一概不做——回写口越蠢越不会坏。
        try:
            rec = {
                "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "event": ("pick" if a.used.strip() else "review"),
                "sessionId": os.environ.get("DSH_SESSION_ID", ""),
                "used": a.used.strip(),
                "note": (a.note or "").strip()[:200],
                "task": (a.task or "")[:80],
            }
            with TIER_PICKS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            _label = rec["used"] if rec["event"] == "pick" else "阶段认知"
            print(f"已记：{_label}（{TIER_PICKS}）")
        except Exception as e:  # noqa: BLE001
            print(f"记录失败：{e}")
        # 2026-11-19 修（盲审第 4 条）：原来这里无条件 return 0，把后面的
        # --audit / --inventory / --chain 全挡掉了——`lab tier --chain record --note "..."`
        # 只写一条 review 记录、链根本不落盘，却打印「已记」并退出 0。
        # 回写和「查/建链」是两件独立的事，只有「这次只做回写」才该在这里结束。
        if not (a.audit or a.inventory or a.chain or a.task):
            return 0

    if a.audit:
        items = route_hygiene()
        errs = [i for i in items if i["level"] == "error"]
        infos = [i for i in items if i["level"] == "info"]
        total = sum(len(o.get("routes") or []) for o in PATH_OPTIONS)
        print("=" * 68)
        print(f"路线清单体检：{len(PATH_OPTIONS)} 个域 / {total} 条路线")
        print("=" * 68)
        print()
        print("判据（用户 2026-11-08 m16336 定）：")
        print("  条数不是问题——「就算它线路再多，只要运行的够流畅、不臃肿都是可以接受的」。")
        print("  所以这里报的是「臃肿」，不是「太多」：重复长处 / 死路径 / 空壳 / 代号不合规。")
        print()
        if not items:
            print("  ✅ 没有发现问题。")
        for i in infos:
            print(f"  💬 [{i['domain']}] {i['detail']}")
        for i in errs:
            print(f"  ❌ [{i['domain']}] {i['code']}. {i['detail']}")
        print()
        if errs:
            print(f"→ {len(errs)} 处要改（会进 lab selfcheck 第 14 组，跑它就红）")
            return 1
        print("→ 无 error；条数提醒不是必须处理的。")
        return 0

    if a.inventory:
        print(f"不构成路线的资产 {len(NON_ROUTE_ASSETS)} 个（它们是能力，但不是「选择」）：")
        print()
        for name, kind, why in NON_ROUTE_ASSETS:
            print(f"  [{kind}] {name}")
            print(f"      {why}")
        print()
        print(r"对照：D:\work\架构文档\插件能力上限.md（每个插件的能力与上限，代码扫描所得）")
        return 0

    if a.chain:
        return _chain_cmd(a)

    if not a.task:
        ap.error("要么给任务描述，要么用 --inventory")

    text = a.task
    qtys, ranges, heavy, light, visual = extract(text)
    tier, reasons, missing = judge(qtys, ranges, heavy, light, visual)

    # 2026-11-10：--json 原来是「先打一整屏人读文本，末尾再附一段 JSON」，
    # 调用方（cmd_pre）拿到的不是纯 JSON，只能再去正则匹配人读文本。
    # 现在改成纯 JSON 提前返回：人读文本走另一条分支，两边的计算是同一份。
    if a.json:
        _opts = path_options(text)
        record_call(text, _opts)
        _combos = combo_hits(_opts)
        _kn = knowledge_for([o["domain"] for o in _opts])
        print(json.dumps({
            "task": text,
            "now": now_line(),
            "tier": tier,
            "reasons": reasons,
            "missing": missing,
            "quantities": [{"n": q, "raw": raw} for q, raw in qtys],
            "ranges": ranges,
            "heavy": heavy,
            "light": light,
            "cap_hints": cap_hints(text),
            "opts": [{"domain": o["domain"],
                      "routes": [{"code": c, "name": nm, "good": g,
                                  "cost": co, "how": how}
                                 for c, nm, g, co, how in o["routes"]],
                      "aux": o.get("aux") or []} for o in _opts],
            "combos": [{"name": nm, "tags": tg, "how": how, "crit": cr,
                        "hit": hit, "missing": miss}
                       for nm, tg, how, cr, hit, miss in _combos],
            "chains": chains_for([o["domain"] for o in _opts]),
            "knowledge": [{"domain": d, "desc": de, "path": p}
                          for d, de, p in _kn],
        }, ensure_ascii=False, indent=2))
        return 0

    health_hint()

    print("=" * 68)
    print(f"任务：{text}")
    print("=" * 68)
    # 用户 m14102：把时间观念写进流程——每轮开工必跑的命令里印时间，不靠我想起来。
    if not a.json:
        print(f"〔{now_line()}〕")
        print()
    # 用户 m13257/m13259 定：这是每次开工看到的第一个前提，必须先于一切出现。
    print("【前提】一个最优解 = 跨类别的组合（能力 + 工具 + 技能 + 知识 + 判断），")
    print("        不是「选一个域的一条路线」。下面的路线是零件，不是菜单。")
    print()

    n_sub = count_subcommands()
    print("【0】能力盘点（开工先过一遍——别只用顺手的那个）")
    print()
    print(f"  手·命令    {n_sub or '?'} 个 lab 子命令（`lab --help` 现查）")
    print("  手·文件    ops_read_files / ops_grep / ops_glob / ops_inspect_local_file")
    print("  手·执行    pwsh（Windows 上唯一稳定的）；ops_bash 在 standard 预设下不发布")
    print("  手·看图    vision_describe / lab ocr / read_image（精确看小字用 read_image）")
    print("  手·3D      lab blender（要厚度/倒角/打光渲染）；Three.js 手写只适合示意图")
    print("  分身       Agent Teams 8 个（spawn_teammate/wait_agent/team_task_*）+ workflow fan-out")
    print("  本地模型   qwen2.5-coder:3b（文本·代码向）/ qwen2.5vl:3b·7b（视觉）——零边际成本，Ollama 不是常驻，用前先启动")
    print("  记忆       lab recall（开工必跑）/ lab sessions（找旧对话）/ user.md+assets.md 注入")
    print("  外网       web_search / web_fetch（核实外部事实）")
    print("  资产       插件索引 / 架构文档 / 知识库 / 我的仓库（数量用 `lab assets` 现查，写死必过期）")
    print("  插件       bundle 清单（`lab plugins` 现查）：注册工具的 8 个 / 事件钩子的 5 个 / 界面的 6 个 / Skill 包 2 个 / 官方实验 2 个")
    print("             每个「能做什么 / 上限在哪 / 证据第几行」见 `架构文档\\插件能力上限.md`——规划路线前先读它，别凭印象说某个插件能干什么")
    print("             不是所有插件都有「路」（换背景、启动动画、桌宠没有第二种做法）→ `lab tier --inventory` 看哪 10 个不构成路线")
    print()
    hints = cap_hints(text)
    if hints:
        print("  → 这次的任务词命中了这些，优先考虑：")
        for h in hints:
            print(f"    · {h}")
    else:
        # 2026-11-07 修：原来只写「没有关键词命中」，用户看到会以为「什么都没命中」，
        # 但候选路线【5】可能照样命中（CAP_HINTS 查的是「该调哪件能力」，不是任务域）。
        print("  → CAP_HINTS（任务词→该调哪件能力）没命中；这不代表没有候选路线，")
        print(f"    往下看【5】——{len(PATH_OPTIONS)} 个任务域是按任务域匹配的，两件事不是一回事。")
    print()

    print("【1】从字面数出来的")
    print()
    if qtys:
        for q, raw in qtys:
            print(f"  · 数量 {q:>6,}  ← 「{raw}」")
    else:
        print("  · 没数到任何数量")
    if ranges:
        print(f"  · 范围词：{'、'.join(ranges)}")
    if heavy:
        print(f"  · 重活动词：{'、'.join(heavy)}")
    if light:
        print(f"  · 轻活动词：{'、'.join(light)}")
    print()

    print("【2】规模判断")
    print()
    for r in reasons:
        print(f"  → {r}")
    if missing:
        print()
        print("  ⚠️ 还缺的：")
        for m in missing:
            print(f"    · {m}")
    print()

    print(f"【3】档位建议：{tier}")
    print()
    print(f"  （档位是上面报数的副产品，不是先说「我该几档」再去凑数）")
    print()

    if not a.no_assets:
        print("【4】手边可能用得上的")
        print()
        rows = related_assets(text)
        if rows:
            for row in rows:
                print(f"  · {row.get('name', '?'):32s} {fmt_bytes(row.get('size')):>10s}  {row.get('judge', '')}")
        else:
            print("  （资产扫描没结果）")
        print()

    opts = path_options(text)
    record_call(text, opts)          # 不靠我记得——每次调用自动落一行
    if opts:
        combos = combo_hits(opts)
        chains = chains_for([o["domain"] for o in opts])
        if combos or chains:
            # 2026-11-07 用户 m13257(m13259) 两层纠正：
            # ①「不是以其中一个域为前提，要以整个候选路线库为前提」——所以链要放最前；
            # ②「一个解决方案里面，往往可能就会涉及到多个能力，域，技能，知识」——
            #    所以下面这几条**只是参考样例，不是穷举**。真正的组装由我做，
            #    工具的责任是「把原料摊全、别让我漏」，不是替我拍板。
            # 2026-11-13 加经验链（◆【经验】那几条）：静态链是样例，经验链是战绩；
            # 两条都是参考——零件照旧全列，链不替我拍板，偏离另记一票（探索信号）。
            print("【5a】已知的常见组合（参考样例，不是穷举——◆【经验】= 验证过并回写的真实战绩）")
            print()
            for name, tags, how, crit, hit, miss in combos:
                print(f"  ◆ {name}")
                if miss:
                    print(f"     命中：{' / '.join(hit)}　→ 这条链还要补：{' / '.join(miss)}"
                          f"（不是我提的，是交付本身要求的）")
                print(f"     链：{how}")
                print(f"     判据：{crit}")
            for c in chains:
                votes = f"采用 {c.get('used', 1)} 次"
                if c.get("deviated"):
                    votes += f" · 偏离 {c['deviated']} 次"
                print(f"  ◆【经验 · {str(c.get('at', ''))[:10]} 验证 · {votes}】{c['name']}")
                print(f"     证据：{c.get('evidence', '')}")
                if c.get("tier"):
                    print(f"     验证时档位：{c['tier']}（不同档位规模差很多，链未必照搬）")
                print(f"     链：{c.get('how', '')}")
                print(f"     判据：{c.get('crit', '')}")
                print(f"     ⚠️ 链是捷径不是牢房：重新组装得出一样的结论才叫复现；"
                      f"不一样就用 `lab tier --chain-deviate \"{c['name']}\"` 记一票")
            print()
        print("【5】原料清单——这是能力，不是方案")
        print("     ① 一次任务的最优解 = 多个能力/域/技能/知识的组合，不是「选一个域的一条路线」。")
        print("     ② 下面按域列出可用的手和脚；aux 里是顺手但容易漏的配角。")
        print("     ③ 组装三步：挑能力 → 排顺序 → 标出「这步结论能让后面几步不用做」。")
        print("     ④ 动笔前写一行组合理由：选 A（因为…）+ B（因为…）；不选 C 因为…；A 的结论让 D 不用做")
        print("        ⚠️ 写「选 A」一个字母是错的——它默认这题只有一个答案，而任务通常是几条路线排顺序配合出来的。")
        if len(opts) > 1:
            doms = " / ".join(o["domain"] for o in opts)
            print(f"     ⑤ 这次横跨 {len(opts)} 个域：{doms}——跨域是常态，不是异常。")
        print()
        for opt in opts:
            print(f"  [{opt['domain']}]")
            _tools = opt.get("tools")
            if _tools:
                print(f"    惯用工具（参考，不是清单——实际按任务挑）：{_tools}")
            _rs = opt["routes"]
            _shown = len(_rs) if a.full else 3
            for _i, (code, name, good, cost, how) in enumerate(_rs):
                print(f"    {code}. {name}")
                if _i < _shown:
                    print(f"       长处：{good}")
                    print(f"       代价：{cost}")
                    print(f"       怎么验：{how}")
            if _shown < len(_rs):
                # 把没展开的代号列出来：读输出的人即使只看到前几行，也知道后面有哪几条
                _rest = " / ".join(str(_r[0]) for _r in _rs[_shown:])
                print(f"    …还有 {len(_rs) - _shown} 条只列了标题：{_rest}"
                      f"（`lab tier \"...\" --full` 展开全部；也可以只问那一条："
                      f"`lab tier \"...\" --full | grep -A3 \"^    X\\.\"`）")
            aux = opt.get("aux") or []
            if aux:
                # 主线归 routes、配角归 aux——两者合起来才是这个域的完整能力图
                print(f"    + 辅助（不构成路，但你没想起来就会漏）：{' / '.join(aux)}")
            print()
        # 【5b】知识源——能力和工具回答「我能做什么」，知识回答「该翻哪本书」。
        # 用户 m13259 特意点了「知识」这一类：它不在任何域的 routes 里。
        # 编号用 5b 不用 6：【6】已经是「规则触发」，不能让两段重名。
        kn = knowledge_for([o["domain"] for o in opts])
        if kn:
            print("【5b】该翻的知识（不在路线里，漏了就会重踩同一个坑）")
            print()
            for dom, desc, path in kn:
                if path:
                    print(f"  [{dom}] {desc}")
                    print(f"      → {path}")
                else:
                    print(f"  [{dom}] {desc}（用命令现查，没有静态文档）")
            print()
        print("  → 动笔前写一行：`选 X，因为…；不选 Y 因为…`")
        print("    判法：准 > 稳 > 快。答不出「怎么算成了」的那条，再快也是白跑。")
        print()
    else:
        print(f"【5】⚠️ {len(PATH_OPTIONS)} 个域里没有匹配的")
        print()
        print("  两种可能，都得管：")
        print("    a) 这活确实不在已知域里 → 可能是新一类任务，该加域")
        print("    b) 我描述它用的词，不在任何域的 words 里 → 该补词")
        print()
        print("  已自动记进 ~/.dsh/tier-calls.jsonl（domains 为空）——体检时集中报，不靠我记。")
        print()

    # 【6】规则触发：把 §0 主规则变成「到时候会被翻到」，而不是「列在文档里」
    # （2026-11-13 修：条数不写死——「23 条」当天就过期，第 24 条就是那天立的。
    #   判据 mem_mw3nbz8q：写「用什么查」比「有哪些」耐放。）
    opening, closing, rhits = rule_hits(text)
    print("【6】规则触发（SKILL.md §0 主规则，条数以 §0.1 索引表为准）")
    print()
    print("  开工必看：")
    for n, title, advice in opening:
        print(f"    第 {n} 条 {title} —— {advice}")
    if rhits:
        print("  本次命中（任务里出现了这些词）：")
        for n, title, advice, got in rhits:
            print(f"    第 {n} 条 {title} ← {'/'.join(got[:4])}")
            print(f"        {advice}")
    else:
        print("  本次命中：无（任务里没有明显触发词）")
    print("  收尾必看：")
    for n, title, advice in closing:
        print(f"    第 {n} 条 {title} —— {advice}")
    print()
    print("  记忆：跑 `lab recall \"<用户原话>\"` 找相关经验——记忆不是一个数，是一条命令。")
    print()

    _writeback_reminder()

    return 0


if __name__ == "__main__":
    sys.exit(main())
