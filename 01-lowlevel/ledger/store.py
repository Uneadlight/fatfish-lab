"""账本存储层：append-only 数据文件 + DurableTree 索引。

## 为什么是两个文件

`DurableTree` 的键和值都是 **int64**（B+ 树签名就是这样），而一条账目含
时间、类型、金额、备注、标签——都是字符串。所以拆开：

- `ledger.data`：append-only，每条 `[长度 4B][crc32 4B][json]`
- `ledger.idx`：`DurableTree`，存 `seq -> 条目在 data 里的偏移`

这也顺带回答了「这个引擎到底好不好用」：**好用，但它的边界一开始就得说清楚**，
不然用的人会以为它能存任意值。

## 崩溃语义

写序是：

```
数据 append → fsync(data) → tree.put(seq, offset)   ← WAL fsync 是提交点
```

于是只会有两种结果：

- 崩在 `fsync` 之后、`put` 之前 → data 里多一条**孤儿**记录（没有索引指向它），
  `verify()` 能查出来，`recover()` 能顺手trim 掉；已提交的账一条不少。
- 崩在 `put` 之后 → WAL 里有 COMMIT，索引恢复，数据早就在盘上。

反过来（先 `put` 再写数据）就会出现「索引说有条账、读出来是空的」——
这是最坏的一种不一致，因为读的时候才知道坏了。
"""

from __future__ import annotations

import json
import os
import struct
import sys
import zlib
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bplus.durable import DurableTree

HDR = struct.Struct('>II')  # [json 长度 4B][crc32 4B]
MAX_ENTRY = 1 << 20  # 单条上限 1 MB，防止误传大对象把文件撑爆
SEQ_MAX = 1 << 62


class LedgerError(RuntimeError):
  """账本层的错误：数据损坏、格式不对、业务约束不满足。"""


class LedgerStore:
  """本地账本。单写者（和 DurableTree 一样，构造即独占文件锁）。"""

  def __init__(self, prefix: str | os.PathLike) -> None:
    self.prefix = Path(prefix)
    self.data_path = Path(str(self.prefix) + '.data')
    self.idx = DurableTree(str(self.prefix) + '.idx')
    self._fd = os.open(
      str(self.data_path),
      os.O_RDWR | getattr(os, 'O_BINARY', 0) | os.O_CREAT,
    )
    self._size = os.fstat(self._fd).st_size
    self._seq = self._max_seq()

  # -- 写 ------------------------------------------------------------- #
  def append(self, entry: dict) -> int:
    """追加一条账目，返回它的 seq（从 1 开始）。"""
    blob = json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(blob) > MAX_ENTRY:
      raise LedgerError(f'单条账目过大：{len(blob)} > {MAX_ENTRY}')
    frame = HDR.pack(len(blob), zlib.crc32(blob)) + blob

    offset = self._size
    self._write_all(offset, frame)
    os.fsync(self._fd)  # 数据先落地，再让索引指向它
    self._size += len(frame)

    seq = self._seq + 1
    self.idx.put(seq, offset)  # 内部 WAL fsync = 提交点
    self._seq = seq
    return seq

  # -- 读 ------------------------------------------------------------- #
  def read_at(self, offset: int) -> dict:
    head = self._read_exact(offset, HDR.size)
    length, crc = HDR.unpack(head)
    if length == 0 or length > MAX_ENTRY:
      raise LedgerError(f'偏移 {offset} 处的长度字段不合理：{length}')
    blob = self._read_exact(offset + HDR.size, length)
    if zlib.crc32(blob) != crc:
      raise LedgerError(f'偏移 {offset} 处 CRC 不符（数据损坏）')
    return json.loads(blob.decode('utf-8'))

  def entries(self) -> Iterator[tuple[int, dict]]:
    """按 seq 升序产出 `(seq, entry)`。"""
    for seq, offset in self.idx.range_scan(1, SEQ_MAX):
      yield seq, self.read_at(offset)

  def close(self) -> None:
    try:
      os.close(self._fd)
    finally:
      self.idx.close()

  # -- 自检与修复 ----------------------------------------------------- #
  def verify(self) -> dict:
    """逐条校验 CRC，并找出 data 里没有被索引引用的孤儿字节。"""
    indexed_offsets: set[int] = set()
    bad: list[dict] = []
    for seq, offset in self.idx.range_scan(1, SEQ_MAX):
      indexed_offsets.add(offset)
      try:
        self.read_at(offset)
      except (LedgerError, ValueError, json.JSONDecodeError) as exc:
        bad.append({'seq': seq, 'offset': offset, 'error': str(exc)})
    orphans = self._scan_orphans(indexed_offsets)
    return {
      'entries': len(indexed_offsets),
      'bad': bad,
      'orphans': orphans,
      'committed_bytes': max(indexed_offsets) if indexed_offsets else 0,
      'file_bytes': self._size,
    }

  def _scan_orphans(self, indexed: set[int]) -> list[int]:
    """顺序扫一遍 data，找出没被索引引用的帧（崩溃留下的孤儿）。"""
    orphans: list[int] = []
    pos = 0
    while pos + HDR.size <= self._size:
      try:
        length, _crc = HDR.unpack(self._read_exact(pos, HDR.size))
      except LedgerError:
        break
      if length == 0 or length > MAX_ENTRY or pos + HDR.size + length > self._size:
        break
      if pos not in indexed:
        orphans.append(pos)
      pos += HDR.size + length
    return orphans

  def recover(self, dry_run: bool = False) -> dict:
    """把孤儿帧收进索引（它们是"数据已落盘但索引没记"的完整条目）。

    注意：这里**不删数据**。孤儿帧是完整的账目，删了就真丢了；
    先收进索引、让人决定要不要留，比默默清理安全。
    """
    indexed = {off for _seq, off in self.idx.range_scan(1, SEQ_MAX)}
    orphans = self._scan_orphans(indexed)
    recovered = 0
    for offset in orphans:
      try:
        entry = self.read_at(offset)  # 先确认能解出来
      except (LedgerError, ValueError, json.JSONDecodeError):
        continue
      recovered += 1
      if not dry_run:
        seq = self._seq + 1
        self.idx.put(seq, offset)
        self._seq = seq
      del entry
    return {'orphans_found': len(orphans), 'recovered': recovered, 'dry_run': dry_run}

  # -- 内部 ----------------------------------------------------------- #
  def _max_seq(self) -> int:
    rows = self.idx.range_scan(1, SEQ_MAX)
    return rows[-1][0] if rows else 0

  def _write_all(self, offset: int, data: bytes) -> None:
    os.lseek(self._fd, offset, os.SEEK_SET)
    view = memoryview(data)
    while view:
      written = os.write(self._fd, view)
      if written <= 0:
        raise LedgerError('写入返回 0 字节')
      view = view[written:]

  def _read_exact(self, offset: int, size: int) -> bytes:
    os.lseek(self._fd, offset, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
      chunk = os.read(self._fd, remaining)
      if not chunk:
        raise LedgerError(f'读到文件尾（想要 {size} 字节，偏移 {offset}）')
      chunks.append(chunk)
      remaining -= len(chunk)
    return b''.join(chunks)
