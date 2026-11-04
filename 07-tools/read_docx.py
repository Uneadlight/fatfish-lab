"""读 docx 全文（段落 + 表格），输出为可读文本。

用法：py D:\work\tools\lab\read_docx.py <文件.docx>
"""

import sys
from pathlib import Path

from docx import Document

path = Path(sys.argv[1])
doc = Document(str(path))

print(f'=== 文件：{path.name} ===')
print(f'段落数：{len(doc.paragraphs)}  表格数：{len(doc.tables)}\n')

for p in doc.paragraphs:
    text = p.text.strip()
    if not text:
        continue
    style = p.style.name if p.style else ''
    if style.startswith('Heading'):
        level = style.replace('Heading ', '')
        print(f'\n{"#" * int(level) if level.isdigit() else "#"} {text}')
    else:
        print(text)

for i, table in enumerate(doc.tables, 1):
    print(f'\n=== 表格 {i}（{len(table.rows)} 行 × {len(table.columns)} 列）===')
    for row in table.rows:
        cells = [c.text.strip().replace('\n', ' / ') for c in row.cells]
        print(' | '.join(cells))
