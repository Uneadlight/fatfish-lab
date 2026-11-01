"""WAL 单元测试：记录能读回、未提交的作废、坏尾部能截断。"""

from __future__ import annotations

import struct

from bplus.wal import (
  KIND_ACK,
  KIND_COMMIT,
  KIND_PAGE,
  KIND_PUT,
  WAL,
  _pack,
)


def test_recover_empty_wal(tmp_path):
  path = tmp_path / 'empty.wal'
  with WAL(str(path)) as wal:
    committed, max_txn = wal.recover()
  assert committed == []
  assert max_txn == 0


def test_committed_put_is_recovered(tmp_path):
  path = tmp_path / 'put.wal'
  wal = WAL(str(path))
  wal.append_put(1, 10, 100)
  wal.commit(1)
  wal.close()

  with WAL(str(path)) as wal2:
    committed, max_txn = wal2.recover()
  assert max_txn == 1
  assert len(committed) == 1
  assert committed[0].kind == KIND_PUT
  assert committed[0].key_value == (10, 100)


def test_uncommitted_transaction_is_dropped(tmp_path):
  path = tmp_path / 'nocommit.wal'
  wal = WAL(str(path))
  wal.append_put(1, 1, 1)
  wal.append_put(2, 2, 2)
  wal.commit(2)  # 只提交 2
  wal.append_put(3, 3, 3)  # 3 没提交
  wal.sync()
  wal.close()

  with WAL(str(path)) as wal2:
    committed, max_txn = wal2.recover()
  txn_ids = {rec.txn for rec in committed}
  assert txn_ids == {2}
  assert max_txn == 3
  assert [(r.key_value) for r in committed] == [(2, 2)]


def test_multiple_records_per_transaction(tmp_path):
  path = tmp_path / 'multi.wal'
  wal = WAL(str(path))
  wal.append_page(7, 0, bytes([7]) * 32)
  wal.append_page(7, 1, bytes([8]) * 32)
  wal.append_ack(7, 'req-abc')
  wal.commit(7)
  wal.close()

  with WAL(str(path)) as wal2:
    committed, _ = wal2.recover()
  kinds = [rec.kind for rec in committed]
  assert kinds == [KIND_PAGE, KIND_PAGE, KIND_ACK]

  page0 = committed[0].page
  assert page0 == (0, bytes([7]) * 32)
  assert committed[2].request_id == 'req-abc'


def test_truncated_tail_is_ignored(tmp_path):
  path = tmp_path / 'tail.wal'
  wal = WAL(str(path))
  wal.append_put(1, 5, 50)
  wal.commit(1)
  wal.close()

  # 手工在末尾粘一段坏数据（模拟写到一半断电）
  raw = path.read_bytes()
  path.write_bytes(raw + b'WAL1' + b'\x00' * 4)

  with WAL(str(path)) as wal2:
    committed, _ = wal2.recover()
    valid = wal2.valid_size()
  assert len(committed) == 1
  assert committed[0].key_value == (5, 50)
  assert valid == len(raw)


def test_crc_corruption_stops_reading(tmp_path):
  path = tmp_path / 'crc.wal'
  wal = WAL(str(path))
  wal.append_put(1, 1, 11)
  wal.commit(1)
  wal.append_put(2, 2, 22)
  wal.commit(2)
  wal.close()

  raw = bytearray(path.read_bytes())
  # 记录布局：[12B 头][payload]；第 1 条是 PUT、第 2 条是 COMMIT(txn=1)
  len0 = struct.unpack_from('>I', raw, 8)[0]
  rec1_start = 12 + len0
  len1 = struct.unpack_from('>I', raw, rec1_start + 8)[0]
  rec2_start = rec1_start + 12 + len1  # 第 3 条是 PUT(txn=2)
  raw[rec2_start + 4] ^= 0xFF  # 破坏第 3 条的 crc

  path.write_bytes(bytes(raw))
  with WAL(str(path)) as wal2:
    committed, _ = wal2.recover()
  assert len(committed) == 1
  assert committed[0].key_value == (1, 11)


def test_truncate_clears_log(tmp_path):
  path = tmp_path / 'trunc.wal'
  wal = WAL(str(path))
  wal.append_put(1, 1, 1)
  wal.commit(1)
  assert wal.stats['size'] > 0
  wal.truncate()
  assert wal.stats['size'] == 0
  committed, max_txn = wal.recover()
  assert committed == []
  assert max_txn == 0
  wal.close()


def test_pack_rejects_garbage_magic(tmp_path):
  path = tmp_path / 'garbage.wal'
  path.write_bytes(b'NOPE' + b'\x00' * 20)
  with WAL(str(path)) as wal:
    assert wal.recover() == ([], 0)
    assert wal.valid_size() == 0


def test_commit_is_the_visibility_boundary(tmp_path):
  """没有 COMMIT 的记录即使已经 fsync，也不可见。"""
  path = tmp_path / 'boundary.wal'
  wal = WAL(str(path))
  wal.append_put(1, 9, 90)
  wal.sync()  # 落盘了，但没提交
  wal.close()

  with WAL(str(path)) as wal2:
    committed, max_txn = wal2.recover()
  assert committed == []
  assert max_txn == 1


def test_record_shape_of_commit(tmp_path):
  """COMMIT 记录的 extra 为空，且 kind 是 KIND_COMMIT。"""
  path = tmp_path / 'shape.wal'
  raw = _pack(KIND_COMMIT, 42)
  path.write_bytes(raw)
  with WAL(str(path)) as wal:
    records = wal.records()
  assert len(records) == 1
  assert records[0].kind == KIND_COMMIT
  assert records[0].txn == 42
  assert records[0].extra == b''
