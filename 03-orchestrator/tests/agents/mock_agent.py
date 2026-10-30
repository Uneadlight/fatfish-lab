"""测试用的假角色：按 `script.json` 里的剧本改文件，不烧一分钱。

剧本格式（放在 DSH_AGENT_HOME 里）：:

    {
      "1": {"writes": {"calc.py": "..."}, "tokens": 1200, "probe": true},
      "default": {"writes": {}, "tokens": 900}
    }

它刻意只做三件事：写文件、报账（tokens）、可选地探测"我能不能看到另一个角色的家目录"。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def main() -> int:
    home = Path(os.environ["DSH_AGENT_HOME"])
    ws = Path(os.environ["DSH_WORKSPACE"])
    rnd = os.environ.get("DSH_ROUND", "0")
    name = os.environ.get("DSH_AGENT_NAME", "?")
    script_file = home / "script.json"
    script = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
    spec = script.get(str(rnd)) or script.get("default") or {}

    for rel, content in (spec.get("writes") or {}).items():
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

    for rel, text in (spec.get("append") or {}).items():
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("a", encoding="utf-8") as fh:
            fh.write(text)

    for rel, pairs in (spec.get("replace") or {}).items():
        dst = ws / rel
        body = dst.read_text(encoding="utf-8")
        for old, new in pairs:
            if old not in body:
                print(f"[{name}] 锚点没找到：{old[:40]!r}")
                return 4
            body = body.replace(old, new, 1)
        dst.write_text(body, encoding="utf-8")

    if spec.get("sleep"):
        time.sleep(float(spec["sleep"]))

    (home / f"metrics-{rnd}.json").write_text(
        json.dumps({"tokens": int(spec.get("tokens", 0))}), encoding="utf-8"
    )

    if spec.get("probe"):
        others = [k for k in os.environ if k.startswith("DSH_") and "OTHER" in k]
        leaked = []
        for k, v in os.environ.items():
            if k in {"DSH_AGENT_HOME", "DSH_WORKSPACE", "DSH_PROMPT_FILE"}:
                continue
            if "orch-" in str(v):
                leaked.append(k)
        (home / f"probe-{rnd}.json").write_text(
            json.dumps({"other_keys": others, "leaked_env": leaked, "env": sorted(os.environ)}),
            encoding="utf-8",
        )

    print(f"[{name}] round {rnd} done, wrote {len(spec.get('writes') or {})} file(s)")
    return 0 if not spec.get("fail") else 3


if __name__ == "__main__":
    raise SystemExit(main())
