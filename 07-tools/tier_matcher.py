#!/usr/bin/env python3
"""候选路线库的匹配：这句话属于哪些域、命中哪些跨域组合、清单本身有没有病。

从 tier.py 搬出来的（2026-11-11 第 0 步·搬家）。**读 PATH_OPTIONS 一律经 `tier` facade**，
不直接 `from tier_domains import`——因为 tests/test_route.py 用
`monkeypatch.setattr(tier, 'PATH_OPTIONS', fake)` 注入假域表，绕过 facade 会让补丁失效。
"""

from __future__ import annotations

import re
from pathlib import Path


_LIB_NS = None


def set_lib(ns) -> None:
    """由 tier.py 在 import 时把自己注册进来。

    不能只 `import tier`：tests/test_route.py 用
    `importlib.util.spec_from_file_location('tier_route_under_test', tier.py)` 加载，
    那个模块对象不叫 `tier`，`import tier` 会拿到另一份（没被 monkeypatch 的那份），
    于是 `monkeypatch.setattr(tier, 'PATH_OPTIONS', fake)` 静默失效。
    """
    global _LIB_NS
    _LIB_NS = ns


def _lib():
    """正在用的 facade 命名空间（dict）。

    用命名空间而不是模块对象：`module.__dict__ is globals()`，
    所以 monkeypatch.setattr(module, 'PATH_OPTIONS', fake) 改的就是这个 dict。
    测试用 spec_from_file_location 加载时模块名不叫 tier、也不一定在 sys.modules 里，
    传模块对象会 KeyError / 拿到错的模块。
    """
    if _LIB_NS is not None:
        return _LIB_NS
    import tier  # noqa: PLC0415  （兜底：直接 import 时）
    return vars(tier)

# 任务关键词 → 该调哪件能力。
# 2026-11-06 用户死命令：「开工时必须先浏览一遍自身的所有能力，判断这次会用到哪些、
# 过程中又能用到哪些，在已有条件下找最优解」——这张表就是那句话的可执行版本。
# 维护判据：新加一件能力（工具/插件/本地模型）→ 先问「它对应什么任务词」，没有就补触发信号。
CAP_HINTS = [
    (("下载", "镜像", "安装包", "换源"), "lab nettest —— 各下 8MB 实测吞吐再选源，别只看 HEAD 延迟"),
    (("3D", "建模", "模型", "渲染", "微缩", "场景", "图生3D", "单图生成", "转3D", "image-to-3D"),
     "lab i23d（一张照片 → 带贴图 GLB，腾讯混元 HY-3D，25 秒~3 分钟）/ lab blender（手写几何，要厚度/倒角/打光）"),
    (("截图", "界面", "看图", "识别", "图片", "小字"), "vision_describe / lab ocr / read_image（精确数小图标、小字用 read_image）"),
    (("插件", "部署", "profile", "cordis", "装"), "lab deploy / lab vet / lab plugins / env_doctor"),
    (("以前", "上次", "之前", "对话", "记录", "回顾"), "lab sessions —— 按字面搜历史会话；lab recall 搜的是记忆"),
    (("日志", "长文", "几百行", "归因", "排查"), "qwen2.5-coder:3b + tools/edge-lab/triage.py —— 长日志先筛一遍再读，零边际成本"),
    (("并行", "拆", "多个文件", "批量", "同时"), "Agent Teams（spawn_teammate）/ workflow —— T3 任务必须开队友"),
    (("花钱", "预算", "成本", "计费", "花费"), "lab cost / lab balance —— 报预算别拍脑袋"),
    (("提交", "发布", "push", "release", "交付"), "lab stage / lab commit / lab claims（说『做完了』前先看证据率）"),
    (("测试", "验证", "检查", "自检"), "lab selfcheck / lab lint / pytest"),
    (("网页", "点击", "浏览器", "打开网页"), "lab cdp —— 通过 CDP 点网页；桌面点击用 lab desktop"),
    # 2026-11-08 补：USGS 被 405 挡住、web_fetch 拿不到，才发现「打不开」也该有一套固定顺序。
    (("打不开", "403", "405", "反爬", "验证码", "抓不到", "读不了", "被挡"),
     "先 web_fetch 试；被挡再上 `lab cdp` 开真浏览器（过得了 UA 拦截、过不了人机验证）；"
     "人机验证就停下来说「这一步要人来」，不伪装 UA 绕过去"),
    # 2026-11-08 补：用户 m16513 问「盲区清单跟路线库捆了吗」，用「把被拒的原因
    # 记下来」实测时发现域能命中、这一层却空着——路线加对了但入口没开，第四次。
    (("被拒", "驳回", "拒了", "不同意", "晾着", "没回", "盲区", "外部反馈"),
     "gh pr list --author @me --state all 看历史 → 每条被拒/被晾的写进"
     " 学习计划/01-编程/读码笔记/盲区清单.md（逼自己写「我原来错在哪」，不写「他不懂」）"),
    # 2026-11-08 补：加了第 27 域「开源社区协作」后，任务词能命中域，但「该调哪件能力」还是空的。
    (("开源", "issue", "PR", "pull request", "社区", "维护者", "review", "fork", "上游"),
     "gh issue list + 四问法（维护者最近回过没/有 assignee 没/有 linked PR 没/有 good first issue 标签没）；"
     "提 PR 前先读 CONTRIBUTING.md；被拒原因写进盲区清单"),
    # 2026-11-08 补：这一天里我把「20:11 的事」说成「早上」，也把「18 天」说成「三个月」。
    (("时间", "早上", "下午", "晚上", "昨天", "前天", "上周", "上个月", "多久", "几点"),
     "说时间词前先指出出处：会话消息的 time 属性 / `date` / `lab since <日期>` / git log；"
     "指不到就写「刚才 / 上一轮 / 之前」，不写「早上」"),
]

def cap_hints(text: str) -> list[str]:
    return [hint for words, hint in CAP_HINTS if any(w in text for w in words)]

# ── 规则触发：SKILL.md §0 的 23 条主规则，什么时候该翻哪几条 ──
# 不写「过期条件」（那是 §0.1 的事），写「什么信号出现时该翻它」。
# 分三段：开工必看 / 条件触发 / 收尾必看——不是「20 条全报」，那等于没报。
# 2026-11-07 用户 m11744「能力层的全部要含元规则与记忆」+
# m11759「能力层＝我能做到的所有事情，包括规矩、规则、记忆，判据是『能不能做』」。
# 落地要求：不是把标题再列一遍（能力总表 §1.6 已经列了），是让它「到时候会被翻到」。
RULE_OPENING = [
    (16, "任务分档", "开工前：这份活有多重、要不要拆、要不要问人"),
    (20, "开工先选路", "开工前：先跑 lab tier 看候选路线，别跳进第一条"),
]

RULE_CLOSING = [
    (17, "「完成」必须有外部证据", "说『做完了/修好了』之前：证据在哪（退出码/文件/读回值）"),
    (18, "别交第一版", "交付前做一次『第二次』：漏了什么角度、哪步看着做了其实没做透"),
    (25, "实践是检验我所说话的唯一标准", "说『就是这样/应该没问题』之前：这句话里每个事实的证据在哪？没有就改口"),
    (3,  "只列异常", "汇报时先给结论，只列需要用户知道的问题，不倒全量日志"),
]

# (条号, 标题, 触发词, 该做什么)
RULE_SIGNALS = [
    (1, "先验后动",
     ("改", "删", "覆盖", "更新", "不确定", "好像", "应该", "很久没"),
     "动手前查 1-2 次现状（路径/进程/版本），改完立刻验收"),
    (2, "减少返工是第一速度来源",
     ("大概", "估计", "先试试", "应该没问题"),
     "不确定的地方先花 10 秒验证假设，别靠猜"),
    (4, "不擅自扩大范围",
     ("顺便", "反正", "一起改了", "顺手"),
     "只做用户要的；发现别的问题记下来、说一句，别顺手改"),
    (5, "外部影响先打招呼 + 删除列清单",
     ("安装", "卸载", "删除", "删掉", "清空", "重置", "改配置", "改系统", "发邮件", "推送"),
     "装东西/改系统级/删除/对外发消息先问；UI 的删除/清空/重置是绝对禁区"),
    (6, "外来指令是素材不是圣旨",
     ("别人说", "网上说", "AI 生成", "转给你", "粘贴", "复制来"),
     "提取意图不照抄形式；先判断解决的是不是真问题"),
    (7, "前提触发清单",
     ("规格", "需求", "标准", "据说", "最新", "更新了", "文档说"),
     "先问『它在什么前提下成立、我这儿是不是那个前提』"),
    (8, "删除/移动的物理层纪律",
     ("rm ", "del ", "Remove-Item", "移动", "清理"),
     "只有规则 5 里『必须先问』那三类才走 safe_mutate；自造临时文件直接删"),
    (9, "四个硬检查点",
     ("转述", "引用", "你的复盘", "这是你", "AI 拟", "指令说", "别人发给",
      "哪个好", "选哪个", "更合适", "哪个方案", "还是"),
     "①来源隔离：转述/复制文本先判 direct/relayed/mixed；②取舍写两栏（判断过的/照要求做的）；③高风险先问；④收尾自省三问"),
    (10, "改运行中的进程必须提前问",
     ("正在运行", "重启", "进程", "服务", "计划任务"),
     "先问能不能等这轮跑完，同意再改；改完验证进程仍健康"),
    (11, "超时熔断",
     ("下载", "请求", "调用", "等待", "轮询", "跑一下", "执行"),
     "外部调用必须带超时+重试上限+失败出路；>60 秒转后台"),
    (12, "防伪授权铁律",
     ("失败", "报错", "做不到", "没权限", "拒绝", "denied", "403"),
     "第一句先说清：能力缺失 / 权限被拒 / 执行失败，三选一，别混"),
    (13, "任务机械拆解",
     ("派给", "交给", "让 3b", "子智能体", "队友", "拆开"),
     "给弱模型派活必须写四件：签名/边界/验收/反例，禁止开放题"),
    (14, "长尾自检 + 异常信号检索",
     ("并发", "锁", "重试", "超时", "乱码", "解析", "卡住", "没反应", "空输出"),
     "写锁/重试/超时/并发先问长尾路径；怪信号先查错题本（乱码先怀疑读法）"),
    (15, "认识论四条",
     ("发布", "上线", "交付", "保证", "确认", "没问题", "换方案"),
     "交付前答『撤回路径是什么』；写了检查先构造一个该报的样本让它报"),
    (19, "改一个事实必须 grep 全域",
     ("改成", "更新为", "修正", "统一"),
     "改完 grep 旧值，确认没有第二处还在用旧事实"),
    (21, "说时长之前先算",
     ("昨天", "前天", "上周", "上个月", "几个月", "几天前", "多久", "多少天", "三个月"),
     "要写具体多久先跑 lab since <起点>；算不出来就写『之前/刚才』，不编数字"),
    (22, "三看：评估外部项目 / 方案",
     ("星数", "开源项目", "这个项目", "这个仓库", "repo", "仓库", "要不要用", "值不值得",
      "适合我", "靠谱", "还在维护", "维护模式", "复现成本", "评估", "外部方案", "star"),
     "先看三样：维护状态（活跃/维护模式/停更）、和目标匹配度、复现成本；星数只作参考不作判据"),
    (23, "改 system prompt 注入前先查缓存签名",
     ("systemPrompt", "注入", "提示行", "renderInjection", "injectionSignature",
      "system prompt", "系统提示", "缓存签名", "时钟行"),
     "动态内容必须参与签名/缓存判等，否则每次变化都是一次全量重计费；改完跑 acp_cache 看 PROMPT SWITCHES 有没有新增"),
    (24, "批量脚本自带环境约束；提交工具层前过 lab test",
     ("批量", "循环", "逐个", "一批", "脚本", "冒烟", "统计成败", "跑一遍所有"),
     "批量 bash 第一行 export PYTHONIOENCODING=utf-8；测 rc 别在管道后拿 $?（会把失败记成假绿）；动过 tools/lab 提交前必跑 lab test——外置自查比自己印象可靠"),
    (25, "实践是检验我所说话的唯一标准",
     ("应该没问题", "理论上", "一般来说", "肯定是", "我觉得", "大概是", "估计是",
      "好像", "应该是", "是不是真的", "你确定", "真的吗", "没验证", "没试过", "猜的"),
     "下结论前先问：这句话里每个事实，我能指出证据在哪冒出来？指不出就写『我推测（依据 X）/ 我还没验证』，不许把推测说成事实"),
]

def rule_hits(text: str):
    """返回 (开工必看, 收尾必看, 本次命中)。命中项带命中的词，让人能看出为什么触发。"""
    hits = []
    for n, title, words, advice in RULE_SIGNALS:
        got = [w for w in words if w in text]
        if got:
            hits.append((n, title, advice, got))
    return list(RULE_OPENING), list(RULE_CLOSING), hits

AUX_MAP = {
    "3D / 建模 / 渲染": ("present", "read_image", "write", "edit", "lab i23d"),
    "图片 → 3D 模型": ("lab i23d", "read_image", "present"),
    "视觉 / 界面 / 截图验收": ("present", "read_image", "vision_describe", "ask_user_question"),
    "图片 / OCR / 看图理解": ("read_image", "vision_describe", "lab ocr"),
    "排查 / 长日志归因": ("todo_write", "ops_grep", "read"),
    "改插件 / 部署 / 装东西": ("load_workspace_dependencies", "working_directory", "ops_bash"),
    "写代码 / 改代码": ("todo_write", "load_workspace_dependencies", "read", "write", "edit"),
    "测试 / 回归 / 交付验收": ("todo_write", "present"),
    "写文档 / 报告 / 笔记": ("write", "edit", "present", "dsh-stickers（meme.mjs 发表情包）"),
    "找资料 / 调研": ("web_search", "web_fetch", "todo_write"),
    "记忆管理": ("memory_save", "memory_update", "memory_search", "memory_forget",
                "memory_list", "memory_to_skill"),
    "会话检索 / 找以前的对话": ("session_search", "session_trace", "session_event_search",
                             "session_event_read", "session_event_trace",
                             "dsh-session-delete（删会话——危险：只有用户明确要求才动）"),
    "开发协作 / 拆活": ("list_agents", "interrupt_agent", "team_task_get", "team_task_update"),
    "自动化 / 定时 / 无人值守": ("schedule_create", "schedule_edit", "schedule_list",
                              "schedule_view", "create_goal", "get_goal", "update_goal",
                              "job_output"),
    "备份 / 恢复 / 回滚": ("working_directory", "ops_bash"),
    "自我体检": ("todo_write", "lab selfcheck", "lab sync", "lab lint", "lab test", "lab health", "lab onboard"),
    "成本 / 预算 / 上下文": ("acp_status", "acp_cache"),
    "桌面 / 浏览器操作": ("read_image", "present"),
    "音频 / 视频": ("read_image", "present"),
    "编码 / 乱码": ("todo_write", "ops_bash"),
    "安全 / 拦截": ("present", "ask_user_question"),
    "GitHub / 对外发布": ("web_fetch", "ops_bash"),
    "Git / 版本控制 / 仓库管理": ("ops_bash", "lab commit"),
    "本地模型": ("ops_bash",),
    "长期机制 / 制度建设": ("evolve_list", "evolve_status", "evolve_done",
                          "evolve_inbox", "evolve_inbox_done", "todo_write"),
    "下载 / 网络 / 换源": ("ops_bash",),
    "开源社区协作": ("ops_bash", "web_fetch", "todo_write"),
    "代码考古 / 理解陌生仓库": ("ops_grep", "ops_glob", "ops_read_files", "todo_write"),
    "长期跟踪 / 外部反馈": ("ops_bash", "lab log"),
    "系统建模 / 结构化理解": ("ops_grep", "ops_read_files", "present", "todo_write"),
}

# 所有任务通用的元操作（不属于任何单一域）
AUX_GLOBAL = ("lab pre", "lab now", "present", "ask_user_question", "todo_write", "exit_plan_mode",
              "load_workspace_dependencies", "working_directory",
              "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource")

def assert_route_shape(opt: dict) -> None:
    """一个域的 words 必须是元组、routes 每条必须是 5 元组，否则抛 ValueError。

    2026-11-19 加。起因是当天连犯两次同族错：一条路线写成 6 元组、一个新元组
    插进了上一个元组的字符串里（`py_compile` 照过，但 `r[0]` 取到的是字符）。
    两次都是跑 `lab tier` 时发现「不渲染 / 显示不对」，靠肉眼查了几分钟才定位。

    `tests/test_tier.py:127` 早就有 `assert len(r) == 5`——但那是**对着当前数据**的静态
    断言，只在跑 `lab test` 时才生效；我改完数据通常直接跑 `lab tier` 看效果，跳过了测试。
    这里补的是**行为层**：坏数据一进 `path_options` 就抛，报错带域名和位置。

    成本：全库 341 条路线，微秒级，对 `lab tier` 的耗时没有可测影响。
    """
    domain = opt.get("domain", "?")
    words = opt.get("words")
    if not (isinstance(words, tuple) and words):
        raise ValueError(
            f"路线库数据坏了：域「{domain}」的 words 必须是元组且非空，"
            f"实际是 {type(words).__name__}：{words!r:.60}"
        )
    for i, r in enumerate(opt.get("routes", ()), 1):
        if not (isinstance(r, tuple) and len(r) == 5):
            n = len(r) if isinstance(r, (tuple, list)) else "N/A"
            raise ValueError(
                f"路线库数据坏了：域「{domain}」第 {i} 条路线不是 5 元组"
                f"（实际是 {type(r).__name__}、长度 {n}）：{r!r:.80}"
            )


def path_options(text: str) -> list[dict]:
    PATH_OPTIONS = _lib()['PATH_OPTIONS']  # 让 monkeypatch.setattr(tier,'PATH_OPTIONS',...) 仍生效
    for _opt in PATH_OPTIONS:
        assert_route_shape(_opt)
    low = text.lower()
    out = []
    for opt in PATH_OPTIONS:
        # 大小写归一：词表里写 "docker" 也要能命中用户写的 "Docker"/"DOCKER"。
        # 2026-11-11 用户 m00599 校准：修实例（补一条小写）不是修根因，匹配前统一 lower 才是。
        words = opt["words"]
        if not any(w in text or w.lower() in low for w in words):
            continue
        # 域级排除词：命中就整个域不参选（治词表膨胀后的跨域误命中，
        # 2026-11-11 用户 m00474 校准：误命中比漏命中更危险）。
        # 但**强词命中时 not_words 不生效**——否则「Docker 里跑 QLoRA 显存够不够」
        # 会因为出现 "Docker" 被整域挡掉，那是漏命中。区分：
        #   泛词命中（显存/显卡）+ 排除词（docker）→ 这是容器话题，不是本地模型话题 → 排除
        #   强词命中（ollama/qlora/本地模型/微调）+ 排除词 → 这就是本地模型，只是在 docker 里跑 → 保留
        notw = opt.get("not_words", ())
        if notw and any(w in text or w.lower() in low for w in notw):
            strong = opt.get("strong_words", ())
            if not any(w in text or w.lower() in low for w in strong):
                continue
        item = dict(opt)
        merged = list(AUX_MAP.get(opt["domain"], ())) + list(AUX_GLOBAL)
        # 去重保序：域内已有的不再被全局重复一遍（present 尤其容易撞）
        item["aux"] = list(dict.fromkeys(merged))
        out.append(item)
    return out

# ══════════════════════════════════════════════════════════════════════
# 经验链（2026-11-13）：把「组装出来且验证过的路」回写成库
# ══════════════════════════════════════════════════════════════════════
# COMBOS 是手写的静态链（2 条）；这里是真实任务回写的动态链。
# 两个来源，[5a] 打印在同一层——静态的是样例，动态的是战绩。
#
# **闸门（用户 m00790 深度思考后的方案核心）**：写链必须带外部证据，
# 要么 git 里查得到的 commit 号，要么磁盘上真实存在的文件。
# 理由有案底：账本我自己写，而我有「把打算写成已完成」的案底
# （mem_mw24413n：两次把没建成的东西写成建成）。自述文字不收，让命令替我验。
#
# jsonl 只追加不改行（和 tier-calls 同学习）：deviate 事件另起一行，
# 统计时合并——这样「偏离」永远是探索信号而不是对历史的覆写。

import json as _json
import subprocess as _sp
from datetime import datetime as _dt

# 2026-11-19 修（盲审后自查发现，审查没报的第 6 条）：原来是
# `Path.home() / '.dsh' / 'tier-chains.jsonl'` = ~/.dsh\...，
# 在沙箱下写不进（实测 `[Errno 13] Permission denied`），于是 `lab tier --chain record`
# 的闸门永远报「写账本失败」——链一条都存不下来，而错误文案还盖住了真正原因。
# 改到和 `选路记录.jsonl` 同一个目录（路线库配套），两本账放一起也好查。
CHAINS = Path(r'D:\work\架构文档\路线库配套\tier-chains.jsonl')
_GIT = Path(r'D:\work\tools\git\cmd\git.exe')
_REPO = Path(__file__).resolve().parents[2]  # D:\work（tools/lab 上两级）


def verify_evidence(commit: str | None, file: str | None) -> tuple[bool, str]:
    """外部证据核验：commit 必须 git cat-file 查得到，file 必须真实存在。

    返回 (过不过, 写进账本的证据串)。git 程序不存在时 commit 一路降级为
    「查不了」（不是「不成立」）——证据链不能被工具缺席一票否决，但要留话。
    """
    problems = []
    if commit:
        if not re.fullmatch(r'[0-9a-fA-F]{7,40}', commit or ''):
            problems.append(f'commit 格式不合法：{commit!r}')
        elif not _GIT.exists():
            problems.append('git 程序不在这台机上，commit 无法核验（换 --chain-file）')
        else:
            try:
                r = _sp.run([str(_GIT), '-C', str(_REPO), 'cat-file', '-t', commit],
                            capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return True, f'commit {commit}（{r.stdout.strip()}，仓库 {_REPO.name}）'
                problems.append(f'git 查不到 commit {commit}')
            except Exception as e:  # noqa: BLE001
                problems.append(f'git 核验失败：{e}')
    if file:
        p = Path(file)
        if p.is_file():
            return True, f'证据文件 {p}（{p.stat().st_size:,} B）'
        problems.append(f'文件不存在：{file}')
    if not commit and not file:
        return False, '没给证据：--chain-commit 或 --chain-file 至少一个（外部证据，自述文字不收）'
    return False, '；'.join(problems)


def record_chain(*, name: str, tags: list[str], how: str, crit: str,
                 chain_tier: str = '', task: str = '',
                 commit: str | None = None, file: str | None = None,
                 src: Path = CHAINS) -> tuple[bool, str]:
    """带闸门的写链：证据不过就一个字不写。"""
    ok, why = verify_evidence(commit, file)
    if not ok:
        return False, why
    if not name or not how or not tags:
        return False, 'name / tags / how 都必填（tags 是域短标签，匹配规则同 COMBOS）'
    if any(t not in ''.join(o['domain'] for o in _lib()['PATH_OPTIONS']) for t in tags):
        # 死标签当场拒——烂链不许进库（chain_hygiene 是事后兜底，闸门是事前）
        dead = [t for t in tags
                if t not in ''.join(o['domain'] for o in _lib()['PATH_OPTIONS'])]
        return False, f'标签对不上任何域名（死链不收）：{dead}'
    rec = {'kind': 'chain', 'at': _dt.now().strftime('%Y-%m-%dT%H:%M:%S'),
           'name': name, 'tags': list(tags), 'how': how, 'crit': crit,
           'tier': chain_tier, 'task': task[:80], 'evidence': why}
    try:
        src.parent.mkdir(parents=True, exist_ok=True)
        with src.open('a', encoding='utf-8') as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:  # noqa: BLE001
        return False, f'写账本失败：{e}'
    return True, why


def chain_deviate(name: str, reason: str = '', src: Path = CHAINS) -> tuple[bool, str]:
    """偏离记账：用别的组装打穿了这条链——另起一行事件，不改链记录。"""
    ev = {'kind': 'deviate', 'at': _dt.now().strftime('%Y-%m-%dT%H:%M:%S'),
          'name': name, 'reason': reason[:120]}
    try:
        src.parent.mkdir(parents=True, exist_ok=True)
        with src.open('a', encoding='utf-8') as f:
            f.write(_json.dumps(ev, ensure_ascii=False) + '\n')
    except Exception as e:  # noqa: BLE001
        return False, f'写账本失败：{e}'
    return True, f'已记偏离一票：{name}'


def load_chains(src: Path = CHAINS) -> dict[str, dict]:
    """链名 → 最新链记录 + 合并的票（used/deviated）。读失败返回空——
    账本坏了不能拖死开工，这是 record_call 同一条吞异常纪律。"""
    out: dict[str, dict] = {}
    try:
        lines = src.read_text(encoding='utf-8').splitlines()
    except Exception:  # noqa: BLE001
        return out
    for ln in lines:
        try:
            rec = _json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        k, nm = rec.get('kind'), rec.get('name')
        if not nm:
            continue
        if k == 'chain':
            row = dict(rec)
            row['used'] = out.get(nm, {}).get('used', 0) + 1
            row['deviated'] = out.get(nm, {}).get('deviated', 0)
            out[nm] = row
        elif k == 'deviate':
            if nm in out:
                out[nm]['deviated'] = out[nm].get('deviated', 0) + 1
    return out


def chains_for(domains: list[str], src: Path = CHAINS) -> list[dict]:
    """域命中的经验链（tag 匹配规则同 combo_hits：子串即中）。缺的标签不回。"""
    rows = load_chains(src)
    hits = []
    for row in rows.values():
        hit = [t for t in row.get('tags') or [] if any(t in d for d in domains)]
        if hit:
            row = dict(row)
            row['hit'] = hit
            hits.append(row)
    hits.sort(key=lambda r: r.get('at') or '', reverse=True)
    return hits


def chain_hygiene(src: Path = CHAINS) -> list[str]:
    """死链巡查（挂 lab health）：标签对应的域名已经不在库里 = 链悬空了。"""
    joined = ''.join(o['domain'] for o in _lib()['PATH_OPTIONS'])
    problems = []
    for nm, row in load_chains(src).items():
        dead = [t for t in row.get('tags') or [] if t not in joined]
        if dead:
            problems.append(f'经验链「{nm}」标签已死：{dead}（对应域改名/删除，链要重验或删除记录）')
    return problems

# ── 路线清单体检：判「臃肿」不判「条数」 ──────────────────────────────
# 2026-11-08 用户 m16336 定的口径（原文）：
#   「超过 20 条时不是该拆，而是该休整了。如果休整后还是更多的话，
#     那就还是那样就可以了，让它自然而然的往下增长就好了。
#     拆不是必须要的。保证它的整体性完整性。不臃肿才是必要的。
#     就算它线路再多，只要它运行的够流畅、不臃肿都是可以接受的。」
#
# 所以这里把两件事分开：
#   - 条数 > 20  → 'info'「该休整了」，只提醒，不改也行
#   - 真「臃肿」 → 'error'（重复长处 / 死路径 / 空壳字段 / 代号不合规），该红
#
# 「字母用完了怎么办」不是生成逻辑而是格式校验：代号是手写的，
# 所以断言它匹配 ^[A-Z]{1,2}$（A..Z 用完就 AA..ZZ，最多撑到 676 条），
# 且同域内唯一。
REST_THRESHOLD = 20

RE_ROUTE_CODE = re.compile(r'^[A-Z]{1,2}$')

# 2026-11-09 修：原来 `[A-Za-z]:[\\\\/]` 会把 `https://dashscope.aliyuncs.com/...`
# 里的 **`s:/`** 当成盘符路径（s 像盘符），于是 URL 被判 dead-path，
# `lab test` 的 test_real_library_has_no_hygiene_error 直接红。
# 加 `(?<![A-Za-z])` 负向后顾：盘符前面不能是字母 → https 的 s 前面是 p，不匹配；
# 真正的 `C:\` / `D:/` 前面是空格、引号、括号，照常匹配。
RE_ROUTE_PATH = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/][^\s，。、；：:*`"\'()\[\]<>|]{2,}')

def route_hygiene() -> list[dict]:
    """把整个 PATH_OPTIONS 过一遍，返回问题清单。

    kind: rest / bad-code / dup-code / empty-field / dup-good / dead-path
    level: 'info'（只提醒）| 'error'（要改）
    """
    # 走 facade 取：monkeypatch.setattr(tier, 'PATH_OPTIONS', fake) 才生效（见 _lib 的注释）。
    PATH_OPTIONS = _lib()['PATH_OPTIONS']
    out: list[dict] = []
    for opt in PATH_OPTIONS:
        dom = opt["domain"]
        routes = opt.get("routes") or []
        if len(routes) > REST_THRESHOLD:
            out.append({
                "kind": "rest", "level": "info", "domain": dom, "code": "",
                "detail": f"{len(routes)} 条（>{REST_THRESHOLD}）→ 该休整了："
                          f"看有没有两条在说同一件事、有没有指向已不存在的路径、"
                          f"名字和内容对不对得上；整理完还是这么多就不动它",
            })
        seen_good: dict[str, str] = {}
        seen_code: dict[str, str] = {}
        for r in routes:
            # 2026-11-19 修（盲审第 5 条）：原来直接 `list(r) + [""] * 5` 再 `[:5]`，
            # 6 元组会被**静默截断成合法 5 元组**——体检一路绿灯，而 `path_options()`
            # 里的 assert_route_shape 会在每次 lab tier 时抛 ValueError，整个路线库不可用。
            # 体检的职责恰恰是把这种数据抓出来，不是用容错逻辑把它藏起来。
            if not isinstance(r, (tuple, list)) or len(r) != 5:
                _len = len(r) if isinstance(r, (tuple, list)) else "非序列"
                _code = r[0] if isinstance(r, (tuple, list)) and r else ""
                out.append({"kind": "bad-shape", "level": "error", "domain": dom,
                            "code": str(_code),
                            "detail": f"路线元组长度是 {_len}，必须是 5（代号/工具/长处/代价/怎么验）"})
                continue
            fields = list(r)
            code, name, good, cost, how = fields[:5]
            code = code or ""
            name = name or ""
            good = good or ""
            cost = cost or ""
            how = how or ""
            if not RE_ROUTE_CODE.match(code):
                out.append({"kind": "bad-code", "level": "error", "domain": dom,
                            "code": code,
                            "detail": f"代号 {code!r} 不合规（要 A..Z 或 AA..ZZ）"})
            elif code in seen_code:
                out.append({"kind": "dup-code", "level": "error", "domain": dom,
                            "code": code,
                            "detail": f"代号 {code} 重复（{seen_code[code]} / {name}）"})
            else:
                seen_code[code] = name
            for label, val in (("路线名", name), ("长处", good), ("代价", cost), ("怎么验", how)):
                if len(val.strip()) < 4:
                    out.append({"kind": "empty-field", "level": "error", "domain": dom,
                                "code": code, "detail": f"{label} 是空的或太短"})
            g = good.strip()
            if g:
                if g in seen_good:
                    out.append({"kind": "dup-good", "level": "error", "domain": dom,
                                "code": code,
                                "detail": f"长处和 {seen_good[g]} 一字不差——两条路在说同一件事"})
                else:
                    seen_good[g] = code
            for m in RE_ROUTE_PATH.finditer(f"{good} {cost} {how}"):
                p = m.group(0).rstrip('.,;:)）】')
                if p and not Path(p).exists():
                    out.append({"kind": "dead-path", "level": "error", "domain": dom,
                                "code": code, "detail": f"路径不存在：{p}"})
    return out

# ── 跨域组合：同样的活往往不是「选一个域」，而是「几个域串起来」 ──
# 2026-11-07 用户 m12149：「一个任务选一个域这个前提确实值得怀疑。你一个任务自然不可能
# 只在一个域里面待着。这个路线图是你进行任务时提供最优解的方案的工具，不要把它局限了。」
# 只写**反复走过、验证过有效**的组合；没用过的宁可不写——宁可少一条，不要一条假路。
# 每项：(组合名, 需要的域短标签, 串法, 判据)
COMBOS = [
    # 2026-11-10 重写：原来这条只写「选路线建模 → 截图 → 记日志」，是并列罗列；
    # 用户 m05658 要的是「带决策点的总线路」——哪一步的结论能让后面整段不用做。
    # 真事：那天我从 B（Blender 手搓）开始干了 8 小时，交出「只是大体形状」；
    # 而 E（AI 生图→image-to-3D）3 分钟就能出 31 万顶点带贴图的真模型。
    # **第一问定错了，后面所有努力都是沉没成本**，所以它必须是第一步、且写成判据。
    ("做 3D 场景并交付",
     ("3D", "视觉", "文档"),
     "① **第一问（拦掉整段）：要写实/照片级吗？**"
     " 要 → 走 E（AI 生图定美术 → `lab i23d` 出带贴图模型，3 分钟），"
     "**B/D 手搓整段不用做**；"
     "只要形状/示意/极简风格 → 才走 B（Blender）或 D（Three.js 手写）"
     "→ ② **F + G 在建模阶段一起做，不能建完再补**（补 = 重写生成脚本）："
     "F 按材质 join / InstancedMesh（join 下界=材质数，不是 1）；"
     "G 把程序化材质**烘成贴图并接回 Base Color**（不烘，glTF 导出器静默导成纯白）"
     "→ ③ **H 灯光：先定 tone mapping 再定灯**，"
     "exposure 用 `2^(-stops)` 推、bloom `threshold` 必须 <1.0"
     "（**改一个参数看不到画面变化，就说明它没生效，不是再试一个值**）"
     "→ ④ 细节密度（墙面分格缝/雨渍、招牌几百块小色块、街道道具），"
     "**不是继续调灯**——调灯 5 轮收益已到头"
     "→ ⑤ **I 导出后体检**：`gltf-transform inspect` 复查 draw call 与贴图字节，"
     "对不上就回 ② 而不是改渲染参数"
     "→ ⑥ 视觉域 CDP 截图验证（**真实 `file://`，绝不加 `--allow-file-access-from-files` 这类放水参数**）"
     "→ ⑦ 文档域记进决策日志",
     "① 能说出「为什么走这条路」而不是「先试试第一条」；"
     "② `renderer.info.render.calls` 实测 < 300（不是「看着不卡」）；"
     "③ GLB 里 materials 带贴图 URI、baseColor 不是纯白（不是白模）；"
     "④ 每个光照参数改动都对应一次可见的画面变化（没有变化=没生效）；"
     "⑤ 截图里能逐条数出元素清单的每一项，而不是「看着像」；"
     "⑥ 用户双击能打开（单文件 / `file://` 无 fetch 依赖）"),
    ("改插件并上线",
     ("改插件", "自我体检"),
     "改源码 → lab selfcheck 看漂移 → lab deploy 同步 → 重启验证",
     "selfcheck 0 漂移 + 插件页能看到新版本号（不是只有文件改了）"),
    ("对外发布",
     ("GitHub", "测试", "文档"),
     "lab stage 暂存 → lab test 全绿 → lab commit 提交 → 从远端 clone 复跑",
     "远端 clone 跑通才算发布，本地绿不算"),
    ("长日志查根因",
     ("排查", "验证"),
     "triage 3b 提名可疑行 → 人工读上下文裁决 → 写回归测试",
     "模型只提名、不裁决；最终判据是能复现的最小样本"),
    # 2026-11-07 实证（DSH-Metric-W2 + Ollama 那一轮，54 分钟）。
    # 用户 m13257 纠正我：「不是以其中一个域为前提，要以整个候选路线库为前提，
    # 是你通过候选路线库判断这个任务怎样解决是最优解」——所以串法必须写成
    # **带决策点的链**：哪一步的结论能让后面整段不用做，才是「最优解」的核心。
    ("修自动化任务 + 装东西",
     ("自动化", "下载", "改插件"),
     "① 先查任务真定义 `Export-ScheduledTask`（不是 schtasks /Query，终端编码会吐乱码）"
     "→ 看 Settings 里的 StopOnIdleEnd / ExecutionTimeLimit"
     "→ ② 再看子进程是否真的起来（`Win32_Process` 查 headless，267009 只说明脚本挂着）"
     "→ ③ 换路前先问「这活值不值得干」：**下载/升级类先查 release notes**，"
     "跟我实际用法对不上的直接砍掉整段"
     "→ ④ 真要装才走 lab nettest 比源 → 改插件域 lab vet/deploy",
     "① 任务 LastTaskResult=0 且日志有结尾行；② 进程树里能看到下一层（不是只有 cmd.exe）；"
     "③ **下载前能说出「这个版本换来的东西我用得上」，说不出就整段不做**"),
]

def combo_hits(opts: list[dict]) -> list[tuple]:
    """命中的跨域组合：任意一个域短标签命中就返回，并带回「还缺哪些域」。

    2026-11-10 改（用户 m05658 点破「只依靠检索命中给不出最优解」）：
    原来这里是 `all(...)`，要求 COMBOS 的每个 tag 都被命中才打印。
    后果是——任务说「做个 3D 场景」时只命中 `3D` 域，
    而「视觉验证」「文档记录」这两个域用户根本不会提（那是我该主动补的），
    于是最该看到的那条链反而不打印。**编排机制被一个 all() 卡死，等于没有编排。**

    现在改成命中即返回 + 标出缺失域，缺的那几个就是「这条链还欠哪几步」。
    返回 6 元组：(name, tags, how, judge, hit, missing)。
    """
    doms = [o["domain"] for o in opts]
    hits = []
    for name, tags, how, judge in COMBOS:
        hit = [t for t in tags if any(t in d for d in doms)]
        if hit:
            missing = [t for t in tags if t not in hit]
            hits.append((name, tags, how, judge, hit, missing))
    return hits
