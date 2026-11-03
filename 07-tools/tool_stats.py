"""Count how often each tool was actually invoked, across every session.

"Installed" is not "used". This script answers the only question that matters
when checking whether a capability is really in the loop: how many times did it
actually run?

用法:
    py tool_stats.py            # 全量排行 + 零使用清单
    py tool_stats.py --top 20   # 只看前 20
    py tool_stats.py --never    # 只看零使用的

「零使用」的判定要用一份**已知工具清单**，所以下面 KNOWN 是手写的。
它不追求完整——追求的是「我明确知道自己有、但从来没用过」这一档。
清单会过期，但过期本身有用：清单里写了但系统已经没了的工具，会显示成 NEVER，
那说明该更新这份清单了。
"""

from __future__ import annotations

import argparse
import io
import json
from collections import Counter
from pathlib import Path

import zstandard

SESSIONS = Path.home() / ".dsh" / "sessions"

# 我明确知道自己有、值得盯使用率的工具（按用途分组）
KNOWN = {
    "核心读写": ["read", "write", "edit", "grep", "glob", "pwsh", "ops_bash", "ops_read_files"],
    "会话检索": ["session_search", "session_event_search", "session_event_read", "session_trace"],
    "智能体团队": ["spawn_teammate", "send_message", "list_agents", "wait_agent",
                   "interrupt_agent", "team_task_create", "team_task_list",
                   "team_task_get", "team_task_update"],
    "并行编排": ["workflow"],
    "计划任务": ["schedule_create", "schedule_list", "schedule_update", "schedule_delete"],
    "worktree": ["worktree_create", "worktree_list", "worktree_remove", "create_worktree"],
    "目标": ["create_goal", "get_goal", "update_goal"],
    "记忆": ["memory_save", "memory_search", "memory_update", "memory_list", "memory_forget",
             "memory_to_skill"],
    "自研插件": ["env_doctor", "evolve_add", "evolve_list", "evolve_status",
                 "evolve_inbox", "evolve_inbox_done", "evolve_done", "vision_describe"],
    "上下文": ["compress", "decompress", "acp_status", "acp_cache"],
    "网络": ["web_search", "web_fetch"],
    "图片": ["read_image", "acp_read_original_image"],
    "交互": ["ask_user_question", "present", "skill", "todo_write", "exit_plan_mode"],
    "MCP": ["list_mcp_resources", "read_mcp_resource", "list_mcp_resource_templates"],
    "其他": ["job_list", "job_output", "job_kill", "plugin_manager", "load_workspace_dependencies",
             "ops_discover_tools", "working_directory", "terminal_open", "terminal_send",
             "terminal_read", "terminal_close", "terminal_list", "terminal_signal"],
}


def tool_calls(record: dict):
    data = record.get("data", {}) or {}
    message = data.get("message") or {}
    for part in message.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "tool-call":
            yield part.get("name") or "?"


def collect() -> tuple[Counter[str], int]:
    counter: Counter[str] = Counter()
    sessions = 0
    for path in SESSIONS.glob("*/session-*/session.v4.jsonl.zstd"):
        sessions += 1
        sid = path.parent.name.replace("session-", "")[:8]
        try:
            with path.open("rb") as handle:
                reader = zstandard.ZstdDecompressor().stream_reader(handle)
                for line in io.TextIOWrapper(reader, encoding="utf-8"):
                    if '"tool-call"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for name in tool_calls(record):
                        counter[name] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] {sid}: {exc}")
    return counter, sessions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="只显示前 N 个（0 = 全部）")
    ap.add_argument("--never", action="store_true", help="只显示零使用清单")
    args = ap.parse_args()

    counter, sessions = collect()
    known_all = [n for group in KNOWN.values() for n in group]
    never = [n for n in known_all if counter.get(n, 0) == 0]

    if not args.never:
        print(f"=== 工具调用排行（{sessions} 个会话，共 {len(counter)} 种工具被调用过）===")
        items = counter.most_common(args.top or None)
        for name, count in items:
            print(f"  {name:<28} {count:>5}")

    print(f"\n=== 零使用（我有、但一次都没调用过）{len(never)}/{len(known_all)} ===")
    for group, names in KNOWN.items():
        dead = [n for n in names if n not in counter]
        if dead:
            print(f"  [{group}] {', '.join(dead)}")

    used_known = len([n for n in known_all if counter.get(n, 0) > 0])
    print(f"\n=== 使用率：{used_known}/{len(known_all)} = {used_known * 100 // len(known_all)}% ===")
    unknown = [n for n in counter if n not in known_all]
    if unknown:
        print(f"=== 清单外但用过的（{len(unknown)} 个，清单该更新了）===")
        print(f"  {', '.join(sorted(unknown))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
