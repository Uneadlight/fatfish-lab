# -*- coding: utf-8 -*-
"""测试智谱 GLM-4V 视觉 API（key 从 ~/.dsh/dsh-vision-key.txt 读）"""
import base64
import json
import os
import sys
import urllib.request

KEY_FILE = os.path.expanduser(r"~\.dsh\dsh-vision-key.txt")
img_path = sys.argv[1]
question = sys.argv[2] if len(sys.argv) > 2 else "请详细描述这张图片的内容；如果有文字，完整提取。"

with open(KEY_FILE) as f:
    key = f.read().strip()

with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

ext = os.path.splitext(img_path)[1].lower()
mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/webp" if ext == ".webp" else "image/png")

payload = {
    "model": "glm-4v-flash",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }
    ],
}

req = urllib.request.Request(
    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:1000])
except Exception as e:
    print("ERROR:", type(e).__name__, e)
