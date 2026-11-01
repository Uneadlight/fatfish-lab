"""Count how often each tool was actually invoked, across every session.

"Installed" is not "used". This script answers the only question that matters
when checking whether a capability is really in the loop: how many times did it
actually run?
"""

from __future__ import annotations

import io
import json
from collections import Counter
from pathlib import Path

import zstandard

SESSIONS = Path.home() / ".dsh" / "sessions"
WATCH = ("vision_describe", "triage", "memory_search", "session_grep", "env_doctor", "pwsh")


def tool_calls(record: dict):
    data = record.get("data", {}) or {}
    message = data.get("message") or {}
    for part in message.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "tool-call":
            yield part.get("name") or "?"


def main() -> int:
    counter: Counter[str] = Counter()
    per_session: dict[str, Counter[str]] = {}

    for path in SESSIONS.glob("*/session-*/session.v4.jsonl.zstd"):
        sid = path.parent.name.replace("session-", "")[:8]
        local: Counter[str] = Counter()
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
                        local[name] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] {sid}: {exc}")
        if local:
            per_session[sid] = local

    print("=== 工具调用总排行（全部 28 个会话）===")
    for name, count in counter.most_common(30):
        print(f"  {name:<26} {count:>5}")

    print("\n=== 关注的几个 ===")
    for key in WATCH:
        print(f"  {key:<26} {counter.get(key, 0) > 0 and counter.get(key) or 'NEVER':>5}")

    print(f"\n=== 有工具调用的会话数: {len(per_session)} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
