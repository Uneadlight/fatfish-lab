"""lab i23d —— 单图生成 3D 模型（腾讯 TokenHub 混元 HY-3D）。

跟 `lab ocr` 一样是「转发型」工具：本体跑在
`E:\\DS公作区\\tools\\i23d\\.venv\\Scripts\\python.exe`（要 trimesh 转 GLB），
`lab.py` 只负责 subprocess 转发。

链路（2026-11-10 打通，全程实测）：
  1. 图上传到 uguu.se 换公网 URL（API 只收 URL，base64 一律 UrlIllegal）
  2. POST /v1/api/3d/submit  {model, image_url, num_of_faces}  → {id, status}
  3. 轮询 POST /v1/api/3d/query {model, id}  → status: queued|in_progress|completed|failed
  4. completed 后拿 data[0]：
       - hy-3d-polygen-image：data[0].glb_url（无材质无贴图，纯几何）
       - hy-3d-3.1 / hy-3d-express：data[0].url 指向 .zip（里面 obj + texture.png + mtl）
  5. zip 解包 → trimesh 转 GLB（带贴图）

坑：
  - 默认并发 1（第二个任务报 RequestLimitExceeded.JobNumExceed）
  - 3.1 比 polygen 慢得多（实测 3 分钟+，polygen 25 秒）
  - glb_url / url 有效期 1 天，任务 id 有效期 24 小时
  - trimesh 4.0.5 + numpy 2.x 不兼容，必须打 allclose patch
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

BASE = "https://tokenhub.tencentmaas.com"
UPLOAD_URL = "https://uguu.se/upload.php"
KEY_FILE = Path.home() / ".dsh" / "tokenhub-key-guangzhou.txt"

MODELS = ("hy-3d-polygen-image", "hy-3d-3.1", "hy-3d-express")


def _key() -> str:
    if not KEY_FILE.exists():
        raise SystemExit(f"[FAIL] 找不到 key：{KEY_FILE}")
    k = KEY_FILE.read_text(encoding="utf-8").strip()
    if not k:
        raise SystemExit(f"[FAIL] key 文件是空的：{KEY_FILE}")
    return k


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + _key(),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"[FAIL] HTTP {e.code} {url}\n{raw[:1200]}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"[FAIL] 不是 JSON：{raw[:400]}")


def upload_image(path: Path) -> str:
    """multipart/form-data 传到 uguu.se，返回公网 URL。"""
    if not path.exists():
        raise SystemExit(f"[FAIL] 图片不存在：{path}")
    size = path.stat().st_size
    if size > 10 * 1024 * 1024:
        raise SystemExit(f"[FAIL] 图片 {size} B 超过 10 MB 上限")

    boundary = "----i23d" + uuid.uuid4().hex
    ctype = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")

    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="files[]"; filename="{path.name}"\r\n'.encode()
    body += f"Content-Type: {ctype}\r\n\r\n".encode()
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        UPLOAD_URL,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[FAIL] uguu.se 上传失败：{e}")
    url = (out.get("files") or [{}])[0].get("url") or out.get("url") or ""
    if not url:
        raise SystemExit(f"[FAIL] 上传没返回 URL：{json.dumps(out, ensure_ascii=False)[:400]}")
    return url


def submit(model: str, image_url: str, faces: int) -> str:
    body = {"model": model, "image_url": image_url, "num_of_faces": faces}
    out = _post(f"{BASE}/v1/api/3d/submit", body)
    if out.get("status") == "failed":
        err = out.get("error") or {}
        raise SystemExit(f"[FAIL] 提交失败：{err.get('code')} {err.get('message')}")
    jid = out.get("id")
    if not jid:
        raise SystemExit(f"[FAIL] 没拿到任务 id：{json.dumps(out, ensure_ascii=False)[:400]}")
    return jid


def wait(model: str, jid: str, timeout: int, interval: int) -> dict:
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        out = _post(f"{BASE}/v1/api/3d/query", {"model": model, "id": jid})
        st = out.get("status") or ""
        if st != last:
            print(f"  [{int(time.time() - t0):3d}s] {st}", flush=True)
            last = st
        if st == "completed":
            return out
        if st == "failed":
            err = out.get("error") or {}
            raise SystemExit(f"[FAIL] 任务失败：{err.get('code')} {err.get('message')}")
        time.sleep(interval)
    raise SystemExit(f"[FAIL] 轮询超时（{timeout}s），任务 id 还有 24 小时有效，可稍后手动查：{jid}")


def _download(url: str, out: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "lab-i23d/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return len(data)


def zip_to_glb(zip_path: Path, glb_out: Path) -> dict:
    """解 zip（obj + texture.png + mtl）→ trimesh 转 GLB（带贴图）。"""
    # 必须打这个补丁，否则 trimesh 4.0.5 + numpy 2.x 在 allclose 上崩
    import numpy as np
    import trimesh

    trimesh.util.allclose = lambda a, b, atol=1e-8, **k: bool(
        float(np.ptp(np.asarray(a) - np.asarray(b))) < atol
    )

    work = glb_out.parent / (glb_out.stem + "_unzip")
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(work)

    objs = sorted(work.rglob("*.obj"))
    if not objs:
        raise SystemExit(f"[FAIL] zip 里没有 .obj：{[p.name for p in work.rglob('*')]}")
    obj = objs[0]

    scene = trimesh.load(str(obj), force="scene")
    meshes = [g for g in scene.geometry.values()] if hasattr(scene, "geometry") else []
    total_v = sum(len(m.vertices) for m in meshes)
    total_f = sum(len(m.faces) for m in meshes)
    has_tex = any(getattr(m.visual, "uv", None) is not None for m in meshes)
    scene.export(str(glb_out))
    return {
        "obj": obj.name,
        "meshes": len(meshes),
        "verts": total_v,
        "faces": total_f,
        "textured": bool(has_tex),
        "glb_bytes": glb_out.stat().st_size,
        "unzip_dir": str(work),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="单图生成 3D 模型（混元 HY-3D）")
    ap.add_argument("--image", required=True, help="输入图片路径")
    ap.add_argument("--model", default="hy-3d-3.1", choices=MODELS)
    ap.add_argument("--faces", type=int, default=10000, help="面数上限，100~20000")
    ap.add_argument("--out", required=True, help="输出 GLB 路径")
    ap.add_argument("--timeout", type=int, default=900, help="轮询总超时（秒）")
    ap.add_argument("--interval", type=int, default=10, help="轮询间隔（秒）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    img = Path(a.image)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] 上传 {img.name} -> uguu.se", flush=True)
    public_url = upload_image(img)
    print(f"      {public_url}")

    print(f"[2/5] 提交 model={a.model} faces={a.faces}", flush=True)
    jid = submit(a.model, public_url, a.faces)
    print(f"      job id = {jid}")

    print("[3/5] 轮询", flush=True)
    result = wait(a.model, jid, a.timeout, a.interval)
    data = (result.get("data") or [{}])[0]
    raw_url = data.get("glb_url") or data.get("url") or ""
    if not raw_url:
        raise SystemExit(f"[FAIL] completed 但没有下载地址：{json.dumps(data, ensure_ascii=False)[:400]}")

    print("[4/5] 下载", flush=True)
    ext = ".zip" if ".zip" in raw_url.split("?")[0].lower() else ".glb"
    tmp = out.parent / (out.stem + "_raw" + ext)
    n = _download(raw_url, tmp)
    print(f"      {tmp.name} ({n:,} B)")

    info = {"job_id": jid, "model": a.model, "image_url": public_url}
    if ext == ".glb":
        if tmp != out:
            tmp.replace(out)
        info["glb_bytes"] = out.stat().st_size
    else:
        print("[5/5] obj+贴图 -> GLB", flush=True)
        info.update(zip_to_glb(tmp, out))

    info["out"] = str(out)
    print(f"[OK] {out}  ({out.stat().st_size:,} B)")
    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
