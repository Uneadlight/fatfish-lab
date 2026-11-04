"""Search DSH session logs for messages containing every given keyword.

DSH keeps the raw conversation on disk at
``~/.dsh/sessions/<encoded-workspace>/session-<id>/session.v4.jsonl.zstd``.
Compression only rewrites what is *sent to the model* -- the original text stays
on disk -- so this is the only way to look something up that was folded away.

Scanning the raw files costs ~1.4s (it has to decompress ~35 MB). So the first
run builds a plain-text index under ``~/.dsh/session-index/`` and later runs
search that instead, which takes milliseconds. The index rebuilds itself
automatically when any session file is newer than it.

Usage:
    py tools/lab/session_grep.py 记忆 净化
    py tools/lab/session_grep.py 章鱼 --all --limit 50
    py tools/lab/session_grep.py 交叉定年 --days 7
    py tools/lab/session_grep.py --build      # force a rebuild
    py tools/lab/session_grep.py --stats      # what is in the index
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import zstandard

SESSIONS = Path.home() / ".dsh" / "sessions"
INDEX_DIR = Path.home() / ".dsh" / "session-index"
INDEX_FILE = INDEX_DIR / "messages.jsonl"
META_FILE = INDEX_DIR / "index.meta.json"

# Harness-injected text arrives as a user/message but is not the user talking.
INJECTED_PREFIXES = (
    "Current runtime context.",
    "Time sampled",
    "[Compressed conversation section]",
    "<system-reminder>",
    "Tokens prefixed with @",
)

SNIPPET = 160


def is_injected(text: str) -> bool:
    return any(text.startswith(prefix) for prefix in INJECTED_PREFIXES)


def message_text(record: dict) -> str:
    """Extract visible text from either record shape.

    ``user/message`` keeps its content at ``data.content``; ``assistant/message``
    wraps it one level deeper at ``data.message.content``. Missing the second
    shape means every assistant reply indexes as empty -- which is exactly the
    bug this docstring exists to prevent.
    """
    data = record.get("data", {}) or {}
    parts = data.get("content")
    if parts is None:
        parts = (data.get("message") or {}).get("content") or []
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            chunks.append(str(part.get("text", "")))
    return "\n".join(chunks)


def is_real_user_message(record: dict) -> bool:
    source = record.get("data", {}).get("source", {}) or {}
    if source.get("kind") != "user":
        return False
    return not is_injected(message_text(record))


def iter_records(path: Path):
    try:
        with path.open("rb") as handle:
            reader = zstandard.ZstdDecompressor().stream_reader(handle)
            for line in io.TextIOWrapper(reader, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") in ("user/message", "assistant/message"):
                    yield record
    except Exception as exc:  # noqa: BLE001 - one bad file must not kill the scan
        print(f"  [WARN] {path.parent.name}: {exc}", file=sys.stderr)


def session_files() -> list[Path]:
    return sorted(
        SESSIONS.glob("*/session-*/session.v4.jsonl.zstd"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def build_index(quiet: bool = False) -> dict:
    """Rewrite the flat index from every session file. Returns the meta dict."""
    if not SESSIONS.is_dir():
        return {}

    files = session_files()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    started = time.time()
    count = 0
    tmp = INDEX_FILE.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        for path in files:
            session_id = path.parent.name.replace("session-", "")[:8]
            for record in iter_records(path):
                kind = record.get("type")
                if kind == "user/message":
                    if not is_real_user_message(record):
                        continue
                    role = "u"
                else:
                    role = "a"
                text = message_text(record)
                if not text.strip():
                    continue
                # turn/step 在 record['data'] 里（不在消息文本里）。
                # 有它才能"回到那一刻"——按轮次定位，而不是只能按时间取尾巴。
                data = record.get("data") or {}
                row = {
                    "t": record.get("time"),
                    "s": session_id,
                    "r": role,
                    "x": text,
                    "turn": data.get("turn"),
                    "step": data.get("step"),
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1

    tmp.replace(INDEX_FILE)
    meta = {
        "built_at": int(time.time() * 1000),
        "sessions": len(files),
        "messages": count,
        "newest_session_mtime": max((p.stat().st_mtime for p in files), default=0),
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    if not quiet:
        print(f"索引已重建：{count:,} 条消息 / {len(files)} 个会话，用时 {time.time() - started:.1f}s")
    return meta


def index_is_stale() -> bool:
    if not INDEX_FILE.is_file() or not META_FILE.is_file():
        return True
    try:
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    files = session_files()
    if not files:
        return False
    newest = max(p.stat().st_mtime for p in files)
    return newest > float(meta.get("newest_session_mtime") or 0)


def load_index() -> list[dict]:
    rows: list[dict] = []
    with INDEX_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_time(ms: int | None) -> str:
    if not ms:
        return "????-??-?? ??:??"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def snippet(text: str, keywords: list[str]) -> str:
    flat = " ".join(text.split())
    if len(flat) <= SNIPPET:
        return flat
    low = flat.lower()
    first = min((low.find(k.lower()) for k in keywords if k.lower() in low), default=0)
    start = max(0, first - SNIPPET // 3)
    piece = flat[start : start + SNIPPET]
    return ("…" if start else "") + piece + ("…" if start + SNIPPET < len(flat) else "")


def cmd_stats() -> int:
    if not META_FILE.is_file():
        print("还没有索引，运行一次搜索或加 --build 即可建立。")
        return 1
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    size = INDEX_FILE.stat().st_size if INDEX_FILE.is_file() else 0
    built = datetime.fromtimestamp(meta["built_at"] / 1000).strftime("%Y-%m-%d %H:%M")
    print(f"索引文件: {INDEX_FILE}")
    print(f"  建立于: {built}")
    print(f"  会话数: {meta['sessions']}   消息数: {meta['messages']:,}   大小: {size / 1024:.0f} KB")
    print(f"  是否过期: {'是，下次搜索会自动重建' if index_is_stale() else '否'}")
    return 0


def cmd_show(session: str, limit: int = 40, head: bool = False,
             at: int | None = None, around: int | None = None) -> int:
    """打印某个会话的原文（默认最后 40 条，--head 从头，--at/--around 按 turn 定位）。"""
    if index_is_stale():
        build_index()
    rows = [r for r in load_index() if r["s"] == session]
    if not rows:
        # 允许传完整目录名或前缀
        rows = [r for r in load_index() if r["s"] == session[:8]]
    if not rows:
        print(f"索引里没有会话 {session}。先跑 --list 看有哪些。")
        return 1

    rows.sort(key=lambda r: r.get("t") or 0)
    total = len(rows)

    target = at if at is not None else around
    if target is not None:
        idx = None
        for i, r in enumerate(rows):
            if r.get("turn") == target:
                idx = i
                break
        if idx is None:
            turns = sorted({r.get("turn") for r in rows if r.get("turn") is not None})
            span = f"{turns[0]}–{turns[-1]}" if turns else "（这个会话没有 turn 字段）"
            print(f"会话 {session} 里没有 turn={target}。有的 turn：{span}")
            return 1
        if around is not None:
            half = max(1, limit // 2)
            lo, hi = max(0, idx - half), min(total, idx + half + 1)
        else:
            lo, hi = idx, min(total, idx + limit)
        picked = rows[lo:hi]
        print(f"（turn={target} 在第 {idx + 1}/{total} 条，显示第 {lo + 1}–{hi} 条）\n")
    else:
        picked = rows[:limit] if head else rows[-limit:]
        if not head and total > limit:
            print(f"（共 {total} 条，只显示最后 {limit} 条；要前面用 --head，要全部用 --limit {total}）\n")

    for row in picked:
        who = "你" if row.get("r") == "u" else "我"
        turn, step = row.get("turn"), row.get("step")
        stamp = f" T{turn}/S{step}" if turn is not None else ""
        text = str(row.get("x", "")).strip()
        if len(text) > 1200:
            text = text[:1200] + f"…（截断，原文 {len(row.get('x', ''))} 字）"
        print(f"── {fmt_time(row.get('t'))} {who}{stamp} ──")
        print(text)
        print()
    return 0


def iter_all_records(path: Path):
    """流式读原始记录：会话头、权限预设、消息、工具调用与结果。

    和 iter_records 的区别：那个只给消息（建索引用），这个给「那一刻的全现场」。
    """
    try:
        with path.open("rb") as handle:
            reader = zstandard.ZstdDecompressor().stream_reader(handle)
            for line in io.TextIOWrapper(reader, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") in ALLOWED_TYPES:
                    yield record
    except Exception as exc:  # noqa: BLE001 - 读不了就报，不要静默
        print(f"  [WARN] {path.parent.name}: {exc}", file=sys.stderr)


ALLOWED_TYPES = ("session", "permission/preset", "user/message", "assistant/message",
                 "tool/call", "tool/result")


def find_session_file(session: str) -> Path | None:
    for p in session_files():
        sid = p.parent.name.replace("session-", "")
        if sid == session or sid.startswith(session):
            return p
    return None


def _result_text(record: dict) -> str:
    content = ((record.get("data") or {}).get("message") or {}).get("content") or []
    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def cmd_context(session: str, turn: int, before: int = 1, max_text: int = 800) -> int:
    """重建 turn=N 那一刻的完整上下文：消息 + 工具调用与结果。

    系统提示不在会话记录里（harness 每轮现拼），所以能还原的是「消息 + 工具现场」；
    静态配置能对回来：agentPreset、permission preset、cwd（都在会话头里）。
    这是 `--at` 的加强版——`--at` 只给那一刻之后的消息，这个给「怎么走到那一刻的」。
    """
    path = find_session_file(session)
    if path is None:
        print(f"没有这个会话：{session}（先 --list 看有哪些）")
        return 1

    records = list(iter_all_records(path))
    head = next((r for r in records if r.get("type") == "session"), {})
    preset = next((r.get("data", {}).get("preset", "") for r in records
                   if r.get("type") == "permission/preset"), "")
    turns = sorted({r["data"]["turn"] for r in records
                    if r.get("data", {}).get("turn") is not None})
    if not turns:
        print(f"会话 {session} 没有 turn 字段，只能用 --show --head 看")
        return 1
    if turn not in turns:
        print(f"会话 {session} 里没有 turn={turn}。有的 turn：{turns[0]}–{turns[-1]}")
        return 1

    idx = turns.index(turn)
    start = turns[max(0, idx - before)]
    picked = [r for r in records
              if r.get("data", {}).get("turn") is not None
              and start <= r["data"]["turn"] <= turn]
    picked.sort(key=lambda r: r.get("seq") or 0)

    names = {r["data"].get("callId"): r["data"].get("name")
             for r in records if r.get("type") == "tool/call"}
    print(f"[会话 {session}] turn={turn} 那一刻的上下文（{len(picked)} 条记录，从 turn={start} 起）")
    print(f"  preset={head.get('agentPreset', '?')} / {preset or '?'} / "
          f"cwd={head.get('cwd', '?')} / 建于 {fmt_time(head.get('createdAt'))}")
    print("  （系统提示不在会话记录里，是 harness 每轮现拼的；这里还原消息与工具现场）")
    print()
    for r in picked:
        data = r.get("data") or {}
        kind = r.get("type")
        t, s = data.get("turn"), data.get("step")
        stamp = fmt_time(r.get("time"))
        if kind == "user/message":
            body = message_text(r)
            print(f"── T{t}/S{s} 你 {stamp} ──")
            print(body[:max_text] + (f"…（原文 {len(body)} 字）" if len(body) > max_text else ""))
        elif kind == "assistant/message":
            body = message_text(r) or "（这一步只调了工具，没有文本）"
            print(f"── T{t}/S{s} 我 {stamp} ──")
            print(body[:max_text] + (f"…（原文 {len(body)} 字）" if len(body) > max_text else ""))
        elif kind == "tool/call":
            args = str(data.get("arguments") or "")
            print(f"── T{t}/S{s} 工具 {data.get('name')} {stamp} ──")
            print(args[:300] + ("…" if len(args) > 300 else ""))
        elif kind == "tool/result":
            body = _result_text(r)
            call_id = data.get("callId") or ((data.get("message") or {}).get("toolCallId"))
            name = names.get(call_id, "?")
            print(f"── T{t}/S{s} 结果 {name} {stamp} ──")
            print(body[:max_text] + (f"…（原文 {len(body)} 字）" if len(body) > max_text else ""))
        print()
    return 0


def cmd_list(days: float = 0, limit: int = 0) -> int:
    """列出所有会话：时间 / id / 消息数 / 大小 / 首句用户消息。

    这是「找 3 天前的对话」的第一步——先看见有哪些，再决定挖哪个。
    搜索只能在你记得关键词时用；不记得关键词时，只有清单能救你。
    """
    if index_is_stale():
        build_index()
    rows = load_index()

    by_session: dict[str, list[dict]] = {}
    for row in rows:
        by_session.setdefault(row["s"], []).append(row)

    cutoff_ms = (time.time() - days * 86400) * 1000 if days > 0 else 0

    entries = []
    for path in session_files():  # 已按 mtime 倒序
        sid = path.parent.name.replace("session-", "")
        short = sid[:8]
        mtime_ms = path.stat().st_mtime * 1000
        if cutoff_ms and mtime_ms < cutoff_ms:
            continue
        msgs = by_session.get(short, [])
        user_msgs = [m for m in msgs if m.get("r") == "u"]
        title = ""
        if user_msgs:
            earliest = min(user_msgs, key=lambda m: m.get("t") or 0)
            title = " ".join(str(earliest.get("x", "")).split())[:100]
        entries.append({
            "short": short,
            "full": sid,
            "mtime": mtime_ms,
            "size": path.stat().st_size,
            "count": len(msgs),
            "title": title,
            "dir": str(path.parent),
        })

    if limit and limit > 0:
        entries = entries[:limit]

    if not entries:
        print("没有符合条件的会话。")
        return 0

    print(f"{len(entries)} 个会话（按文件时间倒序）\n")
    for e in entries:
        print(f"{fmt_time(e['mtime'])}  [{e['short']}]  "
              f"{e['count']:>5} 条  {e['size'] / 1024 / 1024:>6.1f} MB")
        if e["title"]:
            print(f"   {e['title']}")
        print()
    print("读某个会话的原文： lab sessions --show " + entries[0]["short"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grep DSH session logs on disk (every keyword must appear, case-insensitive).",
    )
    parser.add_argument("keywords", nargs="*", help="all of them must appear in the message")
    parser.add_argument("--all", action="store_true", help="also match assistant replies")
    parser.add_argument("--limit", type=int, default=20, help="stop after N hits (default 20)")
    parser.add_argument("--days", type=float, default=0, help="only messages from the last N days")
    parser.add_argument("--build", action="store_true", help="force rebuild the index, then exit")
    parser.add_argument("--list", action="store_true", help="list every session (time / id / messages / size / first user line)")
    parser.add_argument("--show", metavar="ID", help="print one session's turns (default last 40; combine with --limit / --head / --at / --around)")
    parser.add_argument("--head", action="store_true", help="with --show, start from the first turn instead of the last")
    parser.add_argument("--at", type=int, metavar="TURN", help="with --show, start at this turn number")
    parser.add_argument("--around", type=int, metavar="TURN", help="with --show, show messages around this turn")
    parser.add_argument("--stats", action="store_true", help="show index status, then exit")
    parser.add_argument("--raw", action="store_true", help="skip the index and scan the zstd files directly (slow but authoritative)")
    parser.add_argument("--context", type=int, metavar="TURN",
                        help="with --show, rebuild the full context at this turn (messages + tool calls/results)")
    parser.add_argument("--before", type=int, default=1,
                        help="with --context, how many earlier user turns to include (default 1)")
    args = parser.parse_args(argv)

    if args.stats:
        return cmd_stats()

    if args.list:
        return cmd_list(days=args.days, limit=args.limit)

    if args.show:
        if args.context is not None:
            return cmd_context(args.show, args.context, before=args.before)
        return cmd_show(args.show, limit=args.limit if args.limit != 20 else 40,
                        head=args.head, at=args.at, around=args.around)

    if args.build:
        build_index()
        return 0

    if not args.keywords:
        parser.print_usage()
        return 2

    started = time.time()
    needles = [k.lower() for k in args.keywords]
    cutoff_ms = (time.time() - args.days * 86400) * 1000 if args.days > 0 else 0

    if args.raw:
        # Authoritative path: decompress every session and match in memory.
        rows = []
        for path in session_files():
            session_id = path.parent.name.replace("session-", "")[:8]
            for record in iter_records(path):
                kind = record.get("type")
                if kind == "user/message":
                    if not is_real_user_message(record):
                        continue
                    role = "u"
                else:
                    role = "a"
                text = message_text(record)
                if text.strip():
                    data = record.get("data") or {}
                    rows.append({"t": record.get("time"), "s": session_id, "r": role, "x": text,
                                 "turn": data.get("turn"), "step": data.get("step")})
        source = f"原始文件（{len(session_files())} 个会话）"
    else:
        if index_is_stale():
            build_index()
        rows = load_index()
        source = "索引"
    loaded = time.time()

    print(f"{source} {len(rows):,} 条消息，关键词: {' + '.join(args.keywords)}"
          f"{'(含我的回复)' if args.all else '(只搜你的原话)'}\n")

    hits = 0
    for row in rows:
        if not args.all and row.get("r") != "u":
            continue
        if cutoff_ms and (row.get("t") or 0) < cutoff_ms:
            continue
        text = row.get("x", "")
        low = text.lower()
        if not all(n in low for n in needles):
            continue
        role = "你" if row.get("r") == "u" else "我"
        print(f"{fmt_time(row.get('t'))}  [{row.get('s')}] {role}: {snippet(text, args.keywords)}")
        hits += 1
        if hits >= args.limit:
            print(f"\n--- 到达上限 {args.limit} 条 ---")
            break

    elapsed = time.time() - started
    print(f"\n--- 共 {hits} 条命中 ---")
    print(f"索引载入 {loaded - started:.2f}s + 匹配 {time.time() - loaded:.3f}s = {elapsed:.2f}s")
    return 0 if hits else 2


if __name__ == "__main__":
    raise SystemExit(main())
