#!/usr/bin/env python3
"""会话健康检查 / 修复（2026-11-05 事故后固化）。

背景：dsh-memory v0.6.6 用 `agent.steer(字符串)` 把裸字符串写进
`agent/inbox/spliced` 的 inserted 数组，导致 resume 时报
`SessionFormatError: agent/inbox/spliced requires message objects`，整个对话打不开。

用法：
    py session_health.py              # 只读扫描，有问题退出码 1
    py session_health.py --fix        # 修复（自动备份）
    py session_health.py --report     # 扫描并把报告写到 ~/.dsh/session-health.log

判据：
    bad_json   —— 行不是合法 JSON（JSONL 必须用 split("\\n") 读；splitlines() 会把
                  \\u2028 / \\x85 当行界，误报）
    bad_splice —— type=agent/inbox/spliced 且 inserted 里有非 message 对象
"""
import io
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

try:
    import zstandard
except ImportError:
    print("[FAIL] 缺少 zstandard（用 DSH runtime python 跑：py session_health.py）")
    raise SystemExit(2)

HOME = Path(os.path.expandvars(r"%USERPROFILE%"))
ROOT = HOME / ".dsh" / "sessions"
BACKUP = Path(r"D:\work\备份\session-repair-20261105")
REPORT = HOME / ".dsh" / "session-health.log"
WS_FILE = HOME / ".dsh" / "storages" / "workspace.json"
WS_BACKUP = Path(r"D:\work\备份")


def is_msg(x):
    return (
        isinstance(x, dict)
        and isinstance(x.get("content"), list)
        and isinstance(x.get("role"), str)
    )


def to_msg(text):
    return {
        "content": [{"type": "text", "text": text}],
        "source": {"kind": "dsh-memory"},
        "role": "user",
        "id": str(uuid.uuid4()),
    }


def load_lines(path):
    d = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        with d.stream_reader(f, read_across_frames=True) as r:
            raw = r.read()
    text = raw.decode("utf-8")
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines = lines[:-1]
    return lines, trailing


def inspect(lines):
    bad_json, bad_splice = [], []
    for i, s in enumerate(lines, 1):
        if not s.strip():
            continue
        try:
            o = json.loads(s)
        except Exception as e:
            bad_json.append((i, str(e)[:80]))
            continue
        if o.get("type") == "agent/inbox/spliced":
            ins = (o.get("data") or {}).get("inserted")
            if not isinstance(ins, list):
                bad_splice.append((i, "inserted not list"))
            elif any(not is_msg(v) for v in ins):
                bad_splice.append((i, "non-message"))
    return bad_json, bad_splice


def repair(lines, trailing, path, apply):
    out, merged, fixed, unresolved = [], 0, 0, []
    i = 0
    while i < len(lines):
        s = lines[i]
        if not s.strip():
            out.append(s)
            i += 1
            continue
        obj = None
        try:
            obj = json.loads(s)
        except Exception:
            obj = None
        if obj is None:
            done = False
            for k in range(2, 9):
                if i + k > len(lines):
                    break
                joined = "".join(lines[i:i + k])
                try:
                    json.loads(joined)
                    out.append(joined)
                    merged += 1
                    i += k
                    done = True
                    break
                except Exception:
                    continue
            if not done:
                unresolved.append(i + 1)
                out.append(s)
                i += 1
            continue
        if obj.get("type") == "agent/inbox/spliced":
            ins = (obj.get("data") or {}).get("inserted")
            if isinstance(ins, list) and any(not is_msg(v) for v in ins):
                obj["data"]["inserted"] = [v if is_msg(v) else to_msg(str(v)) for v in ins]
                out.append(json.dumps(obj, ensure_ascii=False))
                fixed += 1
                i += 1
                continue
        out.append(s)
        i += 1

    new_text = "\n".join(out) + ("\n" if trailing else "")
    if apply and (merged or fixed):
        BACKUP.mkdir(parents=True, exist_ok=True)
        bdst = BACKUP / path.relative_to(ROOT)
        bdst.parent.mkdir(parents=True, exist_ok=True)
        if not bdst.exists():
            shutil.copy2(path, bdst)
        # DSH 要求第一帧恰好是一行 header（assertZstdHeaderFrame 校验）。
        # 若把整文件压成一帧，readFirstZstdLine 会抛 CorruptionError，
        # 该会话被 list() 静默跳过，侧边栏里就"消失"了。
        raw = new_text.encode("utf-8")
        nl = raw.index(b"\n")
        header_bytes, rest = raw[: nl + 1], raw[nl + 1:]
        _c = zstandard.ZstdCompressor(level=10, write_checksum=True)
        blob = _c.compress(header_bytes) + (_c.compress(rest) if rest else b"")
        _probe = zstandard.ZstdDecompressor().decompressobj()
        _first = _probe.decompress(blob)
        assert (
            _first.count(b"\n") == 1 and _first.endswith(b"\n")
        ), "first frame must be exactly one header line"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(blob)
        with open(tmp, "rb") as f:
            with zstandard.ZstdDecompressor().stream_reader(
                f, read_across_frames=True
            ) as r:
                assert r.read().decode("utf-8") == new_text, "roundtrip mismatch"
        tmp.replace(path) if False else os.replace(tmp, path)
        with open(path, "rb") as f:
            with zstandard.ZstdDecompressor().stream_reader(
                f, read_across_frames=True
            ) as r:
                assert r.read().decode("utf-8") == new_text, "post-swap mismatch"
    return {"merged": merged, "fixed": fixed, "unresolved": unresolved}


def read_header(path):
    """只解压到第一个换行，不读全文件（46 MB 的大会话也能秒回）。"""
    d = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        with d.stream_reader(f, read_across_frames=True) as r:
            buf = b""
            while b"\n" not in buf:
                chunk = r.read(65536)
                if not chunk:
                    break
                buf += chunk
    return json.loads(buf.split(b"\n")[0].decode("utf-8"))


def collect_by_cwd():
    """cwd -> [(createdAt, sessionId)]，按 createdAt 降序。"""
    out = {}
    for p in sorted(ROOT.rglob("session.v4.jsonl.zstd")):
        sid = p.parent.name
        try:
            h = read_header(p)
        except Exception:
            continue
        if h.get("id") != sid:
            continue
        cwd = h.get("cwd")
        if not isinstance(cwd, str):
            continue
        out.setdefault(cwd, []).append((h.get("createdAt") or 0, sid))
    for v in out.values():
        v.sort(reverse=True)
    return out


def workspace_audit(apply):
    """对照磁盘会话审 workspace.json 的 sessionIds（侧边栏列表来源）。

    判据：登记的 id 与磁盘会话的 header.cwd 不一致 = 侧边栏会少/多。
    DSH 在某些重启路径下会把 sessionIds 剪成只剩当前会话（2026-11-05 事故），
    因为 mutate() 会用 candidateMatches 过滤掉它认为不存在的会话。
    """
    if not WS_FILE.exists():
        print(f"[FAIL] 找不到 {WS_FILE}")
        return 2
    data = json.loads(WS_FILE.read_text(encoding="utf-8"))
    tables = data.get("tables", {}).get("workspaces", {})
    by_cwd = collect_by_cwd()
    rows = []
    for wid, rec in tables.items():
        path = rec.get("path")
        have = rec.get("sessionIds") or []
        want = [sid for _, sid in by_cwd.get(path, [])]
        have_set = set(have)
        want_set = set(want)
        missing = [s for s in want if s not in have_set]
        extra = [s for s in have if s not in want_set]
        rows.append((wid, path, have, want, missing, extra))

    print(f"[workspace] file={WS_FILE} size={WS_FILE.stat().st_size} B")
    bad = 0
    for wid, path, have, want, missing, extra in rows:
        flag = "OK" if not missing and not extra else "DIFF"
        if flag == "DIFF":
            bad += 1
        print(f"  {flag} {wid} path={path} have={len(have)} disk={len(want)} "
              f"missing={len(missing)} extra={len(extra)}")
        if flag == "DIFF":
            for s in missing[:5]:
                print(f"       - missing {s}")
            for s in extra[:5]:
                print(f"       + extra   {s}")

    if not bad:
        print("[workspace] 一致，无需修复")
        return 0
    if not apply:
        print("[workspace] 有差异（加 --fix 修复；DSH 运行中改文件需重启才生效）")
        return 1

    # 修复：只在磁盘确实有该 cwd 的会话时才重建，避免把登记全清掉
    for wid, path, have, want, missing, extra in rows:
        if not missing and not extra:
            continue
        if not want:
            print(f"  [SKIP] {wid} path={path}: 磁盘上找不到该 cwd 的会话，保持原样")
            continue
        tables[wid]["sessionIds"] = want
        tables[wid]["updatedAt"] = (
            datetime.now().astimezone().isoformat(timespec="milliseconds").replace("+08:00", "Z")
        )
        print(f"  [FIX] {wid} path={path}: {len(have)} -> {len(want)}")

    WS_BACKUP.mkdir(parents=True, exist_ok=True)
    bak = WS_BACKUP / f"workspace-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    shutil.copy2(WS_FILE, bak)
    tmp = WS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, WS_FILE)
    print(f"[workspace] 已写回，备份 {bak}")
    print("[workspace] DSH 运行中读的是内存旧状态，**重启 DSH 才生效**")
    return 0


def first_frame_of(path):
    """解到第一帧结束即停，返回（首帧明文, 是否帧完整）。"""
    d = zstandard.ZstdDecompressor()
    obj = d.decompressobj()
    out = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            out += obj.decompress(chunk)
            if obj.eof:
                break
    return out, obj.eof


def reframe(path, apply):
    """把整文件单帧重写成「header 帧 + 数据帧」，DSH 才读得出头部。"""
    d = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        with d.stream_reader(f, read_across_frames=True) as r:
            text = r.read()
    nl = text.index(b"\n")
    header_bytes, rest = text[: nl + 1], text[nl + 1:]
    c = zstandard.ZstdCompressor(level=10, write_checksum=True)
    blob = c.compress(header_bytes) + (c.compress(rest) if rest else b"")
    probe = zstandard.ZstdDecompressor().decompressobj()
    first = probe.decompress(blob)
    assert (
        first.count(b"\n") == 1 and first.endswith(b"\n")
    ), "first frame not exactly one line"
    if apply:
        BACKUP.mkdir(parents=True, exist_ok=True)
        bdst = BACKUP / path.relative_to(ROOT)
        bdst.parent.mkdir(parents=True, exist_ok=True)
        if not bdst.exists():
            shutil.copy2(path, bdst)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(blob)
        with open(tmp, "rb") as f:
            with zstandard.ZstdDecompressor().stream_reader(
                f, read_across_frames=True
            ) as r:
                assert r.read() == text, "roundtrip mismatch"
        os.replace(tmp, path)
    return len(text)


def reframe_audit(apply):
    files = sorted(ROOT.rglob("session.v4.jsonl.zstd"))
    bad = []
    for p in files:
        try:
            first, _eof = first_frame_of(p)
        except Exception as e:
            bad.append((p, f"read:{type(e).__name__}:{e}"))
            continue
        if first.count(b"\n") != 1 or not first.endswith(b"\n"):
            bad.append((p, f"lines={first.count(b'\n')}"))
    print(f"[reframe] total={len(files)} bad={len(bad)} mode={'fix' if apply else 'scan'}")
    for p, why in bad[:40]:
        print(f"  BAD {p.relative_to(ROOT)} :: {why}")
    if apply and bad:
        fixed, failed = 0, 0
        for p, _why in bad:
            try:
                reframe(p, True)
                fixed += 1
            except Exception as e:
                failed += 1
                print(f"  FAIL {p.relative_to(ROOT)} :: {type(e).__name__}: {e}")
        left = 0
        for p, _why in bad:
            try:
                f1, _e = first_frame_of(p)
                if f1.count(b"\n") != 1 or not f1.endswith(b"\n"):
                    left += 1
            except Exception:
                left += 1
        print(f"[reframe] fixed={fixed} failed={failed} remaining_bad={left}")
        return 0 if left == 0 else 1
    return 0 if not bad else 1


def main():
    apply = "--fix" in sys.argv
    report = "--report" in sys.argv
    if "--reframe" in sys.argv:
        return reframe_audit(apply)
    if "--workspace" in sys.argv:
        return workspace_audit(apply)
    files = sorted(ROOT.rglob("session.v4.jsonl.zstd"))
    total = len(files)
    broken, fixed_rows, errors = [], [], []
    for p in files:
        try:
            lines, trailing = load_lines(p)
            bj, bs = inspect(lines)
            if bj or bs:
                rec = {
                    "path": str(p).replace(str(ROOT) + os.sep, ""),
                    "bad_json": [x[0] for x in bj],
                    "bad_splice": [x[0] for x in bs],
                }
                if apply:
                    r = repair(lines, trailing, p, True)
                    rec.update(r)
                    fixed_rows.append(rec)
                    # 修完复核
                    lines2, _ = load_lines(p)
                    bj2, bs2 = inspect(lines2)
                    if bj2 or bs2:
                        rec["STILL_BAD"] = {"bad_json": len(bj2), "bad_splice": len(bs2)}
                else:
                    broken.append(rec)
        except Exception as e:
            errors.append({"path": str(p), "error": f"{type(e).__name__}: {e}"})

    lines_out = [
        f"[{datetime.now().isoformat(timespec='seconds')}] session-health "
        f"total={total} mode={'fix' if apply else 'scan'}"
    ]
    if apply:
        lines_out.append(f"repaired={len(fixed_rows)} errors={len(errors)}")
        for r in fixed_rows:
            lines_out.append(f"  FIXED {r['path']} merged={r.get('merged')} fixed={r.get('fixed')}")
            if "STILL_BAD" in r:
                lines_out.append(f"    !! STILL_BAD {r['STILL_BAD']}")
    else:
        lines_out.append(f"broken={len(broken)} errors={len(errors)}")
        for r in broken:
            lines_out.append(
                f"  BAD {r['path']} bad_json={r['bad_json']} bad_splice={r['bad_splice']}"
            )
    for e in errors:
        lines_out.append(f"  ERROR {e['path']} :: {e['error']}")

    text = "\n".join(lines_out)
    print(text)
    if report:
        try:
            with open(REPORT, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as e:
            print(f"[WARN] 写报告失败: {e}")

    ok = (len(fixed_rows) == 0) if apply else (len(broken) == 0)
    return 0 if (ok and not errors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
