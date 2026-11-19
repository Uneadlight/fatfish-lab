#!/usr/bin/env python3
"""候选路线库的判定：这条任务有多少活、该用什么档位。

从 tier.py 搬出来的（2026-11-11 第 0 步·搬家）。纯函数，只依赖本文件里的词表/正则。
"""

from __future__ import annotations

import re

# 数量词：数字 + 量词
QTY = re.compile(r"(\d[\d,]*)\s*(个|条|件|次|行|字|篇|张|KB|MB|GB|TB)")

# 范围词：出现这些说明"不是挑几个，是全都要"
RANGE_WORDS = ("全部", "所有", "每个", "每一个", "全量", "批量", "逐个", "挨个")

# 重活动词：这些词出现说明要动脑，不是机械操作
HEAVY = ("重写", "重新设计", "架构", "分析", "审计", "梳理", "精读", "推演", "对比")

# 轻活动词
LIGHT = ("改", "修", "加", "补", "删", "换", "更新", "重命名")

# 验收方式：这些词的交付物**没法用退出码判断**，只能靠眼睛看
# 2026-11-06 教训：雨夜便利店那活被判成 T1，实际花了 50 分钟、18 轮截图试错
# 2026-11-07 修：去掉「设计」——它太泛，「设计一个机制/设计一套规则」不是视觉交付，
# 却被判成「交付物是视觉性的 → 没有退出码能验」，把制度类任务也带偏。
VISUAL = ("截图", "预览", "渲染", "界面", "视觉", "美观", "好看", "配色", "布局",
          "动画", "3D", "场景", "UI", "样式", "排版", "画面", "效果",
          "设计图", "视觉设计", "UI 设计", "排版设计")

def extract(text: str):
    qtys = [(int(m.group(1).replace(",", "")), m.group(0)) for m in QTY.finditer(text)]
    ranges = [w for w in RANGE_WORDS if w in text]
    heavy = [w for w in HEAVY if w in text]
    light = [w for w in LIGHT if w in text]
    visual = [w for w in VISUAL if w in text]
    return qtys, ranges, heavy, light, visual

def judge(qtys, ranges, heavy, light, visual=()):
    """报规模 + 给档位建议。每条结论都要能指回原文里的哪个词。"""
    max_qty = max((q for q, _ in qtys), default=1)
    reasons: list[str] = []
    tier = "T1"

    if ranges and max_qty >= 100:
        tier = "T4"
        reasons.append(f"范围词「{ranges[0]}」+ 数量 {max_qty:,} → 一个人扛不完，够拆")
    elif max_qty >= 100:
        tier = "T3"
        reasons.append(f"数量 {max_qty:,} → 单次上下文装不下，要么拆要么换工具")
    elif max_qty >= 20:
        tier = "T2"
        reasons.append(f"数量 {max_qty:,} → 要逐条过，不能一眼扫完")
    elif heavy and not light:
        tier = "T2"
        reasons.append(f"动作词「{heavy[0]}」→ 要动脑，不是照做")
    elif max_qty <= 3 and light and not heavy:
        tier = "T1"
        reasons.append(f"数量 {max_qty} + 动作「{light[0]}」→ 小改")
    elif not qtys and not heavy:
        tier = "T1"
        reasons.append("没数出数量、也没重活动词 → 默认低档，先干着看")
    else:
        tier = "T2"
        reasons.append(f"数量 {max_qty}，动作词 {heavy or light} → 中等，边走边看")

    # 验收方式一票否决：交付物只能靠眼睛判断的任务，档位不能按「量」算
    if visual:
        if tier in ("T1", "T2"):
            if max_qty >= 20 or heavy:
                tier = "T3"
            else:
                tier = "T2"
        reasons.append(
            f"交付物是视觉性的（「{visual[0]}」等）→ **没有退出码能验**，"
            f"改一轮看不出对错，实际轮数取决于要试多少次"
        )

    missing = []
    if max_qty >= 20:
        missing.append("单件多大？（没写就算不出总规模）")
    if not qtys:
        missing.append("一共多少？（描述里没有数量，先数一遍再开工）")
    if visual:
        missing.append("验收指标是什么？（「好看」不能当判据，要先写死：构图占比/亮度/元素清单/几个角度）")

    return tier, reasons, missing
