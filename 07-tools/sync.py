# -*- coding: utf-8 -*-
"""lab sync —— 检查一次改动该留的痕迹有没有留下，并报出几处说法可能打架的地方。

判据（2026-11-18 用户定的「第二版」，当天下午再收窄一次）：

    **必写的面只有一个：记忆库。**
    它是唯一「不写就永久丢」的面——文档、路线库、日志都是「写了更好」，
    只有记忆是下一个我唯一能读到的地方。

    其余几面按**建议**列出：缺了会提示，但不影响退出码、不阻断提交。
    实测反例：上午还在按「capability 必须有 route+ledger+writeback」判，
    结果一次小改动就报三个红——那不是在报警，是在制造假警报，
    最后人只会学会无视它（这正是第一版被否掉的原因）。

它不查「你改了几面」，查的是「这几面之间有没有自相矛盾」：
同一个 subject 在多处出现时，把每处的首行和数字都列出来，让人一眼看到
「一处说 55K、另一处说 47K」。

回写面用专用判据，不搜关键词（2026-11-18 改）：
    原来扫 jsonl 整行文本，要求 note 里含主语。反例：回写了
    「计划任务报 Last Result 0 但队列 5 天没动…」，note 里没有「dsh-self-guard」，
    于是被判「没回写」。**工具要求 note 能被搜到，而不是真的回写了**——这是错的。
    现在改成：用 tier_matcher.path_options(subject) 把主语映射到相关域，
    再看 选路记录.jsonl 里有没有一条 event=pick 的 used 域落在这些域里。

用法：
    lab sync --type capability --subject "lab dl"
    lab sync --type config --subject "5/5 全文注入" --json
    lab sync --check --type capability --subject "lab dl"     # 给 lab commit 用，只输出一行结论
    lab sync --acknowledge writeback --subject "改写记忆注入" --reason "这次确实没用到路线库"
"""

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = r"D:\work"
ARCH = os.path.join(ROOT, "架构文档")
MEM_PATH = r"~/.dsh\memory\memories.json"

SURFACES = {
    "memory": ("记忆库", MEM_PATH, "json"),
    "route": ("路线库", os.path.join(ROOT, "tools", "lab", "tier_domains.py"), "text"),
    "mechdoc": ("机制文档", ARCH, "dir"),
    "ledger": ("索引台账", os.path.join(ARCH, "我的能力清单.md"), "text"),
    "decision": ("决策日志", os.path.join(ROOT, "自进化", "决策日志.md"), "text"),
    "writeback": ("回写", os.path.join(ARCH, "路线库配套", "选路记录.jsonl"), "jsonl"),
}

ORDER = ["memory", "route", "mechdoc", "ledger", "decision", "writeback"]

# 必写面：只有记忆（2026-11-18 收窄，理由见模块 docstring）
REQUIRED = {
    "config": ["memory"],
    "capability": ["memory"],
    "bugfix": ["memory"],
    "experiment-fail": ["memory"],
}

# 建议面：缺了只提示，不改退出码
SUGGESTED = {
    "config": ["mechdoc"],
    "capability": ["route", "ledger", "writeback"],
    "bugfix": ["decision"],
    "experiment-fail": ["ledger", "mechdoc"],
}

NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:K|M|G|k|m|g)?(?:B|b)?\b")


def _keywords(subject):
    """subject 的多个叫法要用 | 分隔——同一个实体常有多种写法，只写一种就会搜不到。

    2026-11-18 补：没写 | 时**同时按空格拆**。起因是 `--subject "需求清单时效 selfcheck requirement freshness"`
    （用空格分隔）被当成**一个**长关键词，于是任何记忆都匹配不到，`lab sync` 误报
    「必写面没写：记忆库」——而记忆明明写了。宁可多拆（可能假阳性）也不要整串匹配（必然假阴性）。

    2026-11-19 **试过但回退**：让 | 分支也按空格拆。拆是拆开了，但拆出来的是
    「commit加lab」「test闸」这种中英混排的连写，记忆正文里照样不存在——**误报没治好**，
    反而多了一批「test」「lab」这类超短词（阈值卡 4 字符又会把「四道闸」这种中文三字词误杀）。
    结论：**问题不在拆法，在 subject 的写法**——`--subject` 该写「记忆里会出现的名词短语」
    （如 `四道闸|skip-selftest`），不该写句子（如 `commit加lab test闸`）。
    """
    if "|" in subject:
        return [k.strip() for k in subject.split("|") if k.strip()]
    parts = [k.strip() for k in subject.split() if k.strip()]
    return parts or [subject.strip()]


def _match(text, kws):
    low = (text or "").lower()
    return any(k.lower() in low for k in kws)


def _first_line(text, width=90):
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:width]
    return ""


def scan_memory(subject):
    out = []
    if not os.path.exists(MEM_PATH):
        return out
    data = json.load(io.open(MEM_PATH, encoding="utf-8"))
    mems = data.get("memories", []) if isinstance(data, dict) else data
    kws = _keywords(subject)
    for m in mems:
        content = m.get("content") or ""
        if _match(content, kws):
            out.append({
                "id": m.get("id", "?"),
                "importance": m.get("importance"),
                "updatedAt": str(m.get("updatedAt") or "")[:10],
                "deprecated": bool(m.get("deprecated")),
                "first": _first_line(content),
                "numbers": sorted(set(NUM_RE.findall(content)))[:8],
            })
    # 最近改的排前面——命中很多时，本次改动的痕迹才浮得上来
    out.sort(key=lambda x: x["updatedAt"], reverse=True)
    return out


def scan_text_file(path, subject):
    out = []
    if not os.path.exists(path):
        return out
    kws = _keywords(subject)
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if _match(line, kws):
                out.append({"path": path, "line": i, "text": line.strip()[:140]})
    return out


def scan_dir(dirpath, subject):
    out = []
    if not os.path.isdir(dirpath):
        return out
    kws = _keywords(subject)
    for name in sorted(os.listdir(dirpath)):
        if not name.lower().endswith(".md"):
            continue
        path = os.path.join(dirpath, name)
        try:
            with io.open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if _match(line, kws):
                        out.append({"path": path, "line": i, "text": line.strip()[:140]})
        except OSError:
            continue
    return out


def _related_domains(subject):
    """把主语映射到路线库里的相关域（任一关键词命中就整域入选，这是 path_options 的口径）。"""
    try:
        import tier_matcher  # 同目录
        opts = tier_matcher.path_options(subject)
    except Exception:
        return []
    return [d.get("domain", "") for d in opts if d.get("domain")]


def scan_writeback(subject):
    """回写面：看「主语相关的域」有没有一条 route pick 记录（不搜关键词）。

    兼容两种记录：`used` 形如 `改插件/S`（取 `/` 前作域），或 `domain` 字段直接给域名。
    也接受 note 里含关键词的——老记录没写 used 域，别一刀切判死。

    2026-11-18 补：`--acknowledge writeback --subject "<主语>" --reason "..."` 写的
    event=skip 也算数。此前 acknowledge 写了记录但这里只认 event=pick，于是「给了出口却堵着」；
    现在按主语匹配。**无主语的老记录一律不认**——实测它会让一条 skip 命中任何后续检查，
    那不是出口是永久豁免，比堵着更糟。
    """
    out = []
    path = SURFACES["writeback"][1]
    if not os.path.exists(path):
        return out
    domains = _related_domains(subject)
    kws = _keywords(subject)
    now = datetime.now()
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ev = rec.get("event")
            if ev == "skip":
                if rec.get("target") != "writeback":
                    continue
                sub = rec.get("subject") or ""
                # 无主语的老记录一律不认：实测它会命中任何主语（24h 内等于全豁免），
                # 比「堵着」更糟。要求重新 acknowledge 一次并带上 --subject。
                if not sub:
                    continue
                hit = bool(_match(sub, kws)) or bool(domains and sub in domains)
                if hit:
                    out.append({
                        "path": path,
                        "line": i,
                        "text": "已声明跳过：{0}".format((rec.get("reason") or "")[:100]),
                        "skip": True,
                    })
                continue
            if ev != "pick":
                continue
            used = rec.get("used") or ""
            dom = rec.get("domain") or (used.split("/")[0] if "/" in used else "")
            hit = bool(dom and domains and dom in domains)
            if not hit:
                hit = _match(rec.get("note") or "", kws) or _match(used, kws)
            if hit:
                note = (rec.get("note") or "")[:100]
                out.append({
                    "path": path,
                    "line": i,
                    "text": "{0} — {1}".format(used or dom, note),
                })
    return out


def scan_jsonl(path, subject):
    """通用 jsonl 扫描（回写面已改用 scan_writeback，这里留作兜底）。"""
    out = []
    if not os.path.exists(path):
        return out
    kws = _keywords(subject)
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if _match(line, kws):
                try:
                    rec = json.loads(line)
                except ValueError:
                    rec = {}
                out.append({
                    "path": path,
                    "line": i,
                    "text": (rec.get("note") or rec.get("used") or line)[:140],
                })
    return out


def _skipped(surface, subject):
    """这个面 + 这个主语有没有 acknowledge 过（event=skip）。

    2026-11-19 补：此前只有 scan_writeback 读 skip 记录，`--acknowledge memory`
    写了记录却没人读，于是「给了出口却堵着」——和 2026-11-18 修 writeback 那次
    是同一个病，只是当时只修了一个面。现在所有面统一在 scan() 入口查。
    """
    path = SURFACES["writeback"][1]
    if not os.path.exists(path):
        return False
    kws = _keywords(subject)
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("event") != "skip" or rec.get("target") != surface:
                continue
            if _match(str(rec.get("subject", "")), kws):
                return True
    return False


def scan(surface, subject):
    if surface == "writeback":
        return scan_writeback(subject)
    label, path, kind = SURFACES[surface]
    if kind == "json":
        return scan_memory(subject)
    if kind == "dir":
        return scan_dir(path, subject)
    if kind == "jsonl":
        return scan_jsonl(path, subject)
    return scan_text_file(path, subject)


def acknowledge(target, reason, subject=""):
    """往选路记录追加一条 event=skip：「这次确实没用到路线库，不是忘了」。

    `subject` 是**必填**的（2026-11-18 定为硬要求）：没有主语时 scan_writeback
    只能按时间窗口认，实测会让一条 skip 命中任何后续检查——那不是出口，是永久豁免。
    带上主语才能精确匹配「就是这次这个任务」。
    """
    path = SURFACES["writeback"][1]
    rec = {
        "event": "skip",
        "at": datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "subject": (subject or "").strip(),
        "reason": reason,
    }
    with io.open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("[已记] {0} 跳过 {1}（主语：{2}）：{3}".format(
        path, target, rec["subject"] or "（空）", reason))
    return 0


def run(change_type, subject, as_json=False, check=False):
    required = REQUIRED[change_type]
    suggested = SUGGESTED[change_type]
    result = {
        "type": change_type,
        "subject": subject,
        "required": required,
        "suggested": suggested,
        "surfaces": {},
    }

    for surface in ORDER:
        label, path, kind = SURFACES[surface]
        hits = scan(surface, subject)
        result["surfaces"][surface] = {
            "label": label,
            "required": surface in required,
            "suggested": surface in suggested,
            "hits": hits,
            "count": len(hits),
            "skipped": _skipped(surface, subject),
        }

    def _blank(s):
        info = result["surfaces"][s]
        return info["count"] == 0 and not info["skipped"]

    missing = [s for s in required if _blank(s)]
    soft_missing = [s for s in suggested if _blank(s)]
    result["missing"] = missing
    result["soft_missing"] = soft_missing

    if check:
        if missing:
            names = " / ".join(SURFACES[s][0] for s in missing)
            print("[FAIL] 必写面没写：{0}（type={1}, subject={2}）".format(names, change_type, subject))
            return 1
        if soft_missing:
            names = " / ".join(SURFACES[s][0] for s in soft_missing)
            print("[OK] 必写面齐（建议面还差：{0}；不影响退出码）（type={1}, subject={2}）".format(
                names, change_type, subject))
        else:
            print("[OK] 六面无缺（type={0}, subject={1}）".format(change_type, subject))
        return 0

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not missing else 1

    print("lab sync  type={0}  subject={1}".format(change_type, subject))
    print("必写：{0}".format(" / ".join(SURFACES[s][0] for s in required) or "（无）"))
    print("建议：{0}".format(" / ".join(SURFACES[s][0] for s in suggested) or "（无）"))
    print("")

    for surface in ORDER:
        info = result["surfaces"][surface]
        if info["required"]:
            tag = "[OK]  " if info["count"] else "[MISS]"
            note = ""
        elif info["suggested"]:
            tag = "[OK]  " if info["count"] else "[建议]"
            note = "" if info["count"] else "（建议面，缺了不打紧）"
        else:
            tag = "[--]  "
            note = "（本类型不涉及）"
        print("{0} {1}  {2} 处{3}".format(tag, info["label"], info["count"], note))
        if not info["count"]:
            continue
        if surface == "memory":
            for m in info["hits"][:6]:
                flag = " [已废弃]" if m["deprecated"] else ""
                print("        {0}  {1}  {2}{3}".format(m["updatedAt"], m["id"], m["first"], flag))
                if m["numbers"]:
                    print("            数字：{0}".format(", ".join(m["numbers"])))
            if info["count"] > 6:
                print("        ... 还有 {0} 条（按 updatedAt 降序，最近的在前）".format(info["count"] - 6))
        else:
            for h in info["hits"][:5]:
                rel = h["path"].replace(ROOT + os.sep, "")
                print("        {0}:{1}  {2}".format(rel, h["line"], h["text"]))
            if info["count"] > 5:
                print("        ... 还有 {0} 处".format(info["count"] - 5))
        print("")

    mem_hits = result["surfaces"]["memory"]["count"]
    if mem_hits >= 2:
        print("[!] 记忆库有 {0} 条提到同一主语——核对它们的数字/结论是否一致".format(mem_hits))
        print("    （这就是「几面互相打架」最容易藏身的地方）")
        print("")

    if missing:
        print("必写面缺：{0}".format(" / ".join(SURFACES[s][0] for s in missing)))
    elif soft_missing:
        print("必写面齐；建议面还差：{0}（可选）".format(
            " / ".join(SURFACES[s][0] for s in soft_missing)))
    else:
        print("结论：该有的面都有命中。")
    return 0 if not missing else 1


def register(sub):
    p = sub.add_parser(
        "sync",
        help="检查一次改动该留的痕迹（必写只有记忆；其余按建议提示）",
    )
    p.add_argument("--type", choices=sorted(REQUIRED.keys()), dest="change_type",
                   help="改动类型（决定哪些面是建议）")
    p.add_argument("--subject", help="本次改动的主语/实体名，可用 | 分隔多个叫法")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--check", action="store_true", help="只输出一行结论（给 lab commit 用）")
    p.add_argument("--acknowledge", metavar="SURFACE",
                   help="声明某一面这次故意不写（如 writeback），会往选路记录追加 event=skip")
    p.add_argument("--reason", default="", help="配合 --acknowledge：一句理由")

    def _run(a):
        if a.acknowledge:
            if a.acknowledge not in SURFACES:
                print("[FAIL] 未知的面：{0}（可选：{1}）".format(
                    a.acknowledge, " / ".join(ORDER)))
                return 2
            if not a.reason.strip():
                print("[FAIL] --acknowledge 必须配 --reason（写清为什么这次不写）")
                return 2
            if not (a.subject or "").strip():
                print("[FAIL] --acknowledge 必须配 --subject（写清是哪个任务；"
                      "无主语的跳过会命中任何后续检查，等于永久豁免）")
                return 2
            return acknowledge(a.acknowledge, a.reason.strip(), a.subject.strip())
        if not a.change_type or not a.subject:
            print("[FAIL] 需要 --type 和 --subject（或用 --acknowledge + --reason）")
            return 2
        return run(a.change_type, a.subject, a.json, a.check)

    p.set_defaults(func=lambda a: sys.exit(_run(a)))
