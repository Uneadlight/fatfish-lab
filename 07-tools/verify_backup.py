"""验证 config 备份的完整性：manifest 与磁盘是否一致。"""

import json
import sys
from pathlib import Path

d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'D:\work\备份\config-20261102-232010')
mf = d / 'manifest.json'
if not mf.exists():
    print(f'[FAIL] 找不到 manifest: {mf}', file=sys.stderr)
    sys.exit(1)

m = json.loads(mf.read_text(encoding='utf-8'))
print(f'目录: {d.name}')
print(f'创建: {m["created"]}')
print(f'文件: {len(m["files"])} 个 / {m["total_bytes"] / 1048576:.2f} MB')

missing = [f['path'] for f in m['files'] if not (d / f['path']).exists()]
print(f'manifest 列出但磁盘缺失: {missing if missing else "无 ✅"}')

# 反向：磁盘上有但 manifest 没记的（两边都统一成正斜杠再比，
# 否则 Windows 的 relative_to 给反斜杠、manifest 给正斜杠，会全部误报）
def rel(p: Path) -> str:
    return str(p.relative_to(d)).replace('\\', '/')


on_disk = {rel(p) for p in d.rglob('*') if p.is_file()} - {'manifest.json'}
extra = sorted(on_disk - {f['path'] for f in m['files']})
print(f'磁盘上有但 manifest 没记: {extra if extra else "无 ✅"}')

print(f'排除的 secrets: {m["excluded_secrets"]}')

ok = not missing and not extra
print(f'\n{"[OK] 备份完整" if ok else "[FAIL] 有不一致"}')
sys.exit(0 if ok else 1)
