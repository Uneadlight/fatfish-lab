"""lab onboard — 自研插件的闭环检查：在路线库里吗 / 有描述吗 / 工具被调用过吗

判据（2026-11-07 用户 m12313 逼出来的）：**能力落地了但路线库里没有 → 不算真的落地。**

三件全部自动判定，**不依赖我手动标记**——手动标记等于「靠我注意到」，那正是要消灭的东西。
第 3 件（调用过）用启发式：插件短名的关键词出现在工具名里就算（dsh-memory → memory_*）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\work")
LAB = ROOT / "tools" / "lab"
DEPLOY = LAB / "deploy.py"
TIER = LAB / "tier.py"
TIER_DOMAINS = LAB / "tier_domains.py"
PROFILE = Path.home() / ".dsh" / "profiles" / "desktop"

# 插件短名 → 工具名里可能出现的关键词（判「调用过」用；没列到的走默认规则）
ALIASES = {
    "dsh-memory": ("memory", "recall"),
    "dsh-env-doctor": ("env_doctor", "envdoctor"),
    "dsh-evolve": ("evolve",),
    "dsh-vision": ("vision",),
    "dsh-workflow-skill": ("skill", "workflow"),
    "dsh-worktree-tool": ("worktree",),
    "dsh-self-guard": ("self_guard", "selfguard"),
    "dsh-stickers": ("sticker", "meme"),
    "dsh-chat-background": ("chat_background", "background"),
    "dsh-session-delete": ("session_delete", "delete_session"),
    # --- 2026-11-08 扩到 23 个时补：默认规则用「包短名去 dsh- 换下划线」，
    # 对下面这些完全命中不了（它们的路线库词是功能词，不是包名）。
    "billion-context": ("compress", "acp_", "bili", "上下文压缩"),
    "cc-safety-net": ("cc-safety-net", "explain", "安全网"),
    "bridge": ("dsh-pet", "桌宠", "pet"),
    "archify-dsh": ("archify", "架构图"),
    "dsh-community": ("community", "插件市场"),
    "dsh-fail-guard": ("fail_guard", "熔断"),
    "dsh-context": ("上下文洞察", "dsh-context"),
    "dsh-startup-screen": ("startup", "启动动画"),
    "dshmarket": ("plugin_market", "插件市场"),
    "dsh-experimental-forge-bundle": ("forge", "create_worktree", "变更请求"),
    "dsh-subagent-claude-code": ("subagent", "子智能体"),
    "dsh-pocket": ("pocket", "手机"),
    "dsh-ops": ("ops_", "ops_bash"),
    # 2026-11-13：纯配置 bundle，挂的是 agent-desktop 的 MCP；能力已在「桌面 / 浏览器操作」域
    "dsh-mcp-agent-desktop": ("mcp__desk__", "agent-desktop", "desktop_"),
}

# 插件类型决定「怎样才算用过」——不能一律看工具调用数。
# 2026-11-07 第一版只看调用数，把 self-guard（被动拦命令）、stickers（靠 meme.mjs 发图）、
# chat-background（纯展示）三个正常插件判成「没被调用过」。
# 同一条判据见记忆 mem_mw3h15eq_0iuusw「零调用要分五种」。
KINDS = {
    "dsh-memory": "active",
    "dsh-env-doctor": "active",
    "dsh-evolve": "active",
    "dsh-vision": "active",
    "dsh-workflow-skill": "active",
    "dsh-worktree-tool": "active",
    "dsh-session-delete": "active",
    "dsh-self-guard": "passive",
    "dsh-stickers": "display",
    "dsh-chat-background": "display",
    # --- 2026-11-08 扩到全部 23 个时补的。判据：看它「工作」那个动作是自己被调用，
    # 还是拦在中间/画在屏幕上/写在后台文件里——后三种都不能用工具调用数判。
    # key 必须是「短名」（name.split('/')[-1]），不是包全名。
    "billion-context": "active",         # 压缩器：没有日志文件，工作痕迹就是 compress 调用数
    "cc-safety-net": "passive",          # 安全网：拦命令，没有自己的工具
    "dsh-fail-guard": "passive",         # 熔断器：连续失败才触发
    "bridge": "passive",                 # 桌宠桥（@dsh-pet/bridge）：写 jsonl 给外部读
    "dsh-community": "passive",          # 社区目录：安装通道，没有常驻工具
    "dsh-context": "display",            # 会话顶部「上下文洞察」标签页
    "dsh-startup-screen": "display",     # 启动动画
    "dshmarket": "display",              # 可视化插件市场（UI）
    "archify-dsh": "active",             # 提供 archify skill，走 skill 工具
    "dsh-experimental-forge-bundle": "active",
    "dsh-subagent-claude-code": "active",
    "dsh-pocket": "disabled",            # 用户主动停用
}

PASSIVE_LOGS = {
    "dsh-self-guard": (Path.home() / ".dsh" / "devkit" / "self-guard.log",),
    "cc-safety-net": (Path.home() / ".cc-safety-net" / "logs",),
    "bridge": (Path.home() / "AppData" / "Roaming" / "dsh-pet-bridge",),
}


def _patch_log_paths() -> dict[str, Path]:
    """从 `cordis.patch.yml` 里抓每个插件段下的 `logFile:`。

    2026-11-08 立：fail-guard 的日志路径昨天刚从代码里硬编码的
    `C:/Users/fenri/.dsh/local-plugins/dsh-fail-guard/fail-guard.log`
    改成配置里的 `~/.dsh/devkit/fail-guard.log`，但 PASSIVE_LOGS 没跟着加它
    → onboard 判「日志空」，而真相是 29,601 B 正在写。

    判据：**路径写在配置里的时候，检查器就该读配置，不该抄一份**。
    「尺子没跟着东西一起长」这一类，抄路径是根因，加一行只是这次。
    """
    patch = PROFILE / "cordis.patch.yml"
    if not patch.exists():
        return {}
    out: dict[str, Path] = {}
    cur = None
    for line in patch.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip().strip("'\"")
        elif cur and s.startswith("logFile:"):
            raw = s.split(":", 1)[1].strip().strip("'\"")
            if raw:
                out[cur] = Path(raw)
    return out


PATCH_LOGS = _patch_log_paths()

# 已知「从没触发过」的被动项——不是因为坏了，是因为阈值从没达到。
# 2026-11-07 读过源码：fail-guard 的 threshold:2 + sameToolOnly:true 要求同一工具
# 连续 2 次失败才触发，我这几个月没出现过；正确说法是「无法被证明在工作」，
# 不是「没工作」。判它失败等于逼我为凑指标去制造失败。
NEVER_FIRED_OK = {"dsh-fail-guard", "dsh-community"}

# 刚装好的插件给多少天宽限期——0 调用不算问题。
# 2026-11-07 立：dsh-session-delete 装上 1 小时后就被判「没被调用过」，
# 那是正常状态，不是缺陷。
GRACE_DAYS = 7


PKG = PROFILE / "package.json"


def all_plugins() -> list[str]:
    """从 profile 的 dependencies 读**全部装着的插件**（23 个基准）。

    2026-11-08 立：原来只读 deploy.py 的 SELF_BUILT（自研 10 个），
    导致「迭代优化全部插件」这件事从工具层就看不见另外 13 个。
    用户 m14118 点破「跟第一次一样，只选了自身造的 10 个插件」——
    根因不是我不肯看，是这个工具只给我看了 10 个。

    为什么用 `dependencies` 而不是 `bundles`：
    `bundles` 有 31 项，多出 8 个是官方 experimental 的子组件包
    （voice-input / agent-team-profile / inspector-profile / plugin-market /
    tool-worktree / session-search / terminal-bundle / session-titles-bundle），
    它们由所属 bundle 带进来、从不独立存在，拿它们当插件会误报「没描述/没调用」。
    `dependencies` 的 23 项才是「真的装着的包」——和 `plugin_manager`
    的 `installed:true` 数量一致。
    """
    if not PKG.exists():
        return []
    try:
        d = json.loads(PKG.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    return sorted(d.get("dependencies", {}).keys())


def layer_of(name: str, self_built: set[str]) -> str:
    """三层，决定「能改到什么程度」——这是迭代方案的硬边界。

    官方：在 app.asar 里，只能开关/配置，改不了代码
    自研：源码在 E:\\DS公作区\\dsh-*，可改代码（但要 lab deploy 同步 + 重启）
    外来：只能配置级，禁止改第三方源码、禁止自研替代
    """
    if name.startswith("@deepseek-ai/"):
        return "官方"
    if name in self_built:
        return "自研"
    return "外来"


def self_built() -> list[str]:
    """从 deploy.py 的 SELF_BUILT 表读权威清单（不扫目录、不靠记忆）。"""
    if not DEPLOY.exists():
        return []
    text = DEPLOY.read_text(encoding="utf-8")
    m = re.search(r"SELF_BUILT\s*=\s*\[(.*?)\n\]", text, re.S)
    if not m:
        return []
    return re.findall(r"""["']([^"']+@?[^"']*)["']""", m.group(1))


def pkg_path(name: str) -> Path | None:
    short = name.split("/")[-1].strip()
    for cand in (
        PROFILE / "node_modules" / name / "package.json",
        PROFILE / "node_modules" / "@local" / short / "package.json",
        PROFILE / "node_modules" / short / "package.json",
    ):
        if cand.exists():
            return cand
    return None


def call_counter():
    """复用 tool_stats.collect() 从会话日志数工具调用。"""
    try:
        sys.path.insert(0, str(LAB))
        import tool_stats  # type: ignore

        counter, _sessions = tool_stats.collect()
        return dict(counter)
    except Exception as exc:  # 统计失败不能挡住闭环检查
        print(f"[WARN] 读会话日志失败（{exc}），调用列标 n/a")
        return None


def three_checks(names: list[str], with_calls: bool = True) -> list[dict]:
    # 2026-11-13 修：路线已移到 tier_domains.py，只读 tier.py 会把所有插件判成没闭环
    tier_text = ""
    for _p in (TIER, TIER_DOMAINS):
        if _p.exists():
            tier_text += _p.read_text(encoding="utf-8")

    counter = call_counter() if with_calls else None
    rows = []
    for n in names:
        short = n.split("/")[-1].strip()
        # 判据是「它的能力在路线库里」，不是「它的名字在路线库里」——
        # 2026-11-07 第一版按短名判,10 个里报 9 个没闭环，其实 dsh-memory 的
        # memory_search、dsh-vision 的 vision_describe 都写在 AUX_MAP 里。
        keys = ALIASES.get(short, (short.replace("dsh-", "").replace("-", "_"),))
        routed = any(k in tier_text for k in keys) or short in tier_text
        p = pkg_path(n)
        desc = ""
        if p:
            try:
                desc = (json.loads(p.read_text(encoding="utf-8")).get("description") or "").strip()
            except Exception:
                desc = ""
        if counter is None:
            calls = None
        else:
            keys = ALIASES.get(short, (short.replace("dsh-", "").replace("-", "_"),))
            calls = sum(v for k, v in counter.items() if any(a in k.lower() for a in keys))
        kind = KINDS.get(short, "active")
        passive_ok = None
        if kind == "passive":
            passive_ok = False
            candidates = list(PASSIVE_LOGS.get(short, ()))
            if short in PATCH_LOGS:
                candidates.append(PATCH_LOGS[short])
            for lp in candidates:
                if lp.exists() and (lp.is_dir() or lp.stat().st_size > 0):
                    passive_ok = True
        # 刚装好的插件给宽限期：0 调用不算问题（判据见下方 GRACE_DAYS）
        fresh = False
        if p:
            try:
                age_days = (time.time() - p.stat().st_birthtime) / 86400
                fresh = age_days < GRACE_DAYS
            except AttributeError:  # 非 Windows / 无 birthtime
                fresh = False
        rows.append(
            {
                "name": n,
                "routed": routed,
                "desc": bool(desc),
                "desc_text": desc,
                "calls": calls,
                "kind": kind,
                "passive_ok": passive_ok,
                "fresh": fresh,
            }
        )
    return rows


def main(argv=None) -> int:
    argv = list(argv or [])
    with_calls = "--no-calls" not in argv
    # 2026-11-08：默认看全部 23 个（dependencies），`--self-built` 退回只看自研 10 个。
    # 判据：用户要的是「迭代全部插件」，那工具默认就得给全部，不能让我自己去别的命令拼。
    self_only = "--self-built" in argv
    only = None
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = argv[i + 1]
    names = self_built() if self_only else all_plugins()
    if not names:
        src = "deploy.py 的 SELF_BUILT 表" if self_only else "profile 的 dependencies"
        print(f"[WARN] 没从{src}读到插件（结构变了吗？）")
        return 1
    if only:
        names = [n for n in names if only in n]
        if not names:
            # 2026-11-07 测试抓到：原来走 --only 过滤后为空时也报上面那句
            # 「SELF_BUILT 读不到」——把「源数据为空」和「过滤后为空」混为一谈。
            print(f"[WARN] 没有匹配 --only {only} 的插件（清单有 {len(names)} 个，只是过滤后空了）")
            return 0

    sb = set(self_built())
    rows = three_checks(names, with_calls)
    scope = "自研" if self_only else "全部"
    print(f"=== {scope}插件闭环（{len(rows)} 个{'，调用数来自会话日志' if with_calls else '，跳过调用统计'}）===")
    print(f"{'插件':<46}{'层':<6}{'类型':<9}{'路线库':<8}{'描述':<6}{'用过':<8}还差")
    for r in rows:
        mark = lambda b: "[OK]" if b else "[--]"
        lack = []
        # display 型（纯展示，如表情包/聊天背景）不进选路清单也不算缺陷
        need_route = r["kind"] != "display"
        if need_route and not r["routed"]:
            lack.append("补进 tier.py")
        if not r["desc"]:
            lack.append("package.json 缺 description")
        kind = r["kind"]
        if kind == "display":
            used = "—"
        elif kind == "passive":
            used = "日志有" if r["passive_ok"] else "日志空"
            if not r["passive_ok"]:
                lack.append("日志是空的（从没触发过）")
        else:
            used = "n/a" if r["calls"] is None else str(r["calls"])
            if r["calls"] == 0:
                lack.append("新装·宽限中" if r["fresh"] else "没被调用过")
        if r["fresh"] and r["calls"] == 0 and kind == "active":
            used = "0(新)"
        print(f"{r['name']:<46}{layer_of(r['name'], sb):<6}{kind:<9}{mark(r['routed']):<8}{mark(r['desc']):<6}{used:<8}{'、'.join(lack) or '—'}")

    bad = []
    warn_only = []
    for r in rows:
        reasons = []
        # display（画在屏幕上）、disabled（用户主动停）、passive（拦在中间自动生效）
        # 三类都不需要「在路线库里」——它们不是我要主动选的路。
        # 2026-11-08 扩到 23 个时两次修这条：先漏了 disabled（把用户停用的 dsh-pocket
        # 判成没闭环），又漏了 passive（把桌宠桥判成没闭环，可它本来就不该被「选」）。
        if r["kind"] not in ("display", "disabled", "passive") and not r["routed"]:
            reasons.append("routed")
        if not r["desc"]:
            reasons.append("desc")
        if r["kind"] == "passive" and not r["passive_ok"] and r["name"].split("/")[-1] not in NEVER_FIRED_OK:
            reasons.append("passive")
        if reasons:
            bad.append(r)
            continue
        # 「0 调用」只是待观察，不判闭环失败——它可能真的不该被用，
        # 也可能是刚装好还没场景。判据：闭环三件是「有描述 + 在路线库 + 能用」，
        # 「用过」是更后面的验证，不该拖住前面的结论。
        if r["kind"] == "active" and r["calls"] == 0:
            warn_only.append(r)
    print()
    if warn_only:
        names = "、".join(r["name"].split("/")[-1] for r in warn_only)
        print(f"⚠️ 待观察（{len(warn_only)} 个）：{names} —— 在路线库里但一次都没被调用过。")
        print("   不是缺陷：可能只是还没遇到场景；但连续几周都这样，就该问「它到底解不解决我的问题」。")
    if bad:
        print(f"共 {len(bad)} 个没闭环。判据：能力落地了但路线库里没有 → 不算真的落地。")
        print("补法：看它的工具有哪些 → 给 tier.py 对应域加一条路线（或 AUX_MAP）→")
        print('      跑 `lab tier "<它该用的场景>"` 能命中才算补上。')
        return 1
    print("闭环全部走完。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
