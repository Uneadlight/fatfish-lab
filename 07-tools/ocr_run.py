#!/usr/bin/env python
"""在 ocr-venv312 里跑 RapidOCR，把结果以 JSON 打到 stdout。

为什么单独一个文件：rapidocr 只装在 E:\\DS公作区\\tools\\ocr-venv312，
而 lab.py 跑在 DSH runtime python 里（没有 rapidocr）。所以 lab ocr 是
"转发"给这个解释器，不是自己 import。

用法（由 lab.py 调用，一般不直接用）：
    python ocr_run.py <图片路径> [--min-score 0.5]

输出：一个 JSON 对象（不是数组），字段：
    {"ok": true, "file": ..., "elapsed": ..., "lines": [{"text":..., "score":..., "box":[[x,y],...]}]}
失败时 {"ok": false, "error": "..."}, 退出码非 0。
"""

import json
import sys
from pathlib import Path


def main(argv):
    if len(argv) < 2:
        print(json.dumps({'ok': False, 'error': '用法: ocr_run.py <图片路径> [--min-score N]'}, ensure_ascii=False))
        return 2

    img = Path(argv[1])
    min_score = 0.3
    for i, a in enumerate(argv):
        if a == '--min-score' and i + 1 < len(argv):
            min_score = float(argv[i + 1])

    if not img.exists():
        print(json.dumps({'ok': False, 'error': f'文件不存在: {img}'}, ensure_ascii=False))
        return 2

    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({'ok': False, 'error': f'import 失败: {type(exc).__name__}: {exc}'}, ensure_ascii=False))
        return 3

    try:
        engine = RapidOCR()
        result, elapse = engine(str(img))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({'ok': False, 'error': f'识别失败: {type(exc).__name__}: {exc}'}, ensure_ascii=False))
        return 4

    lines = []
    if result:
        for item in result:
            # item = [box(4 点), text, score]
            try:
                box, text, score = item[0], item[1], item[2]
            except (IndexError, TypeError):
                continue
            if score is None or float(score) < min_score:
                continue
            lines.append({
                'text': str(text),
                'score': round(float(score), 4),
                'box': [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in box],
            })

    elapsed = None
    if isinstance(elapse, (list, tuple)) and elapse:
        try:
            elapsed = round(sum(float(x) for x in elapse), 3)
        except (TypeError, ValueError):
            elapsed = None

    print(json.dumps({
        'ok': True,
        'file': str(img),
        'elapsed': elapsed,
        'count': len(lines),
        'lines': lines,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
