"""Read a DSH session file (`session.v4.jsonl.zstd`) and show its record shape.

Usage:
    py tools/lab/read_session.py <session.v4.jsonl.zstd> [n]

Prints the first n records as one-line summaries plus the top-level keys, so the
on-disk schema can be inspected without dumping megabytes into a terminal.
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

import zstandard


def iter_records(path: Path):
    with path.open("rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh)
        text = io.TextIOWrapper(reader, encoding="utf-8")
        for line in text:
            line = line.strip()
            if line:
                yield json.loads(line)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    path = Path(argv[1])
    limit = int(argv[2]) if len(argv) > 2 else 6

    kinds: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    shown = 0

    for rec in iter_records(path):
        kind = str(rec.get("type") or rec.get("kind") or "?")
        kinds[kind] += 1
        role = rec.get("role") or (rec.get("message") or {}).get("role")
        if role:
            roles[str(role)] += 1
        if shown < limit:
            preview = json.dumps(rec, ensure_ascii=False)
            print(f"[{shown}] type={kind} keys={sorted(rec)[:10]}")
            print(f"     {preview[:300]}")
            shown += 1

    print("\n--- totals ---")
    print("records:", sum(kinds.values()))
    print("types:", dict(kinds.most_common(12)))
    print("roles:", dict(roles.most_common(8)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
