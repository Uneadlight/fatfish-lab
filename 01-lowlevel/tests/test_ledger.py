"""账本存储层测试。"""

from __future__ import annotations

import json
import zlib

import pytest

from ledger.cli import fmt_money, main, parse_when
from ledger.store import HDR, LedgerError, LedgerStore


def _entry(ts: int = 1_760_000_000, kind: str = 'api', amount: int = 3, note: str = 'x', tags=None) -> dict:
  return {'ts': ts, 'kind': kind, 'amount': amount, 'note': note, 'tags': tags or []}


def test_append_and_read_back(tmp_path):
  prefix = tmp_path / 'ledger'
  store = LedgerStore(prefix)
  try:
    seq = store.append(_entry(note='第一条'))
    assert seq == 1
    rows = list(store.entries())
    assert len(rows) == 1
    assert rows[0][1]['note'] == '第一条'
  finally:
    store.close()


def test_sequence_increases(tmp_path):
  store = LedgerStore(tmp_path / 'ledger')
  try:
    seqs = [store.append(_entry(note=f'n{i}')) for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]
    assert [e['note'] for _s, e in store.entries()] == [f'n{i}' for i in range(5)]
  finally:
    store.close()


def test_reopen_keeps_data(tmp_path):
  prefix = tmp_path / 'ledger'
  s1 = LedgerStore(prefix)
  s1.append(_entry(note='重开前'))
  s1.close()

  s2 = LedgerStore(prefix)
  try:
    assert s2.append(_entry(note='重开后')) == 2
    assert [e['note'] for _s, e in s2.entries()] == ['重开前', '重开后']
  finally:
    s2.close()


def test_verify_clean(tmp_path):
  store = LedgerStore(tmp_path / 'ledger')
  try:
    store.append(_entry())
    store.append(_entry(amount=7))
    report = store.verify()
    assert report['entries'] == 2
    assert report['bad'] == []
    assert report['orphans'] == []
  finally:
    store.close()


def test_crc_corruption_detected(tmp_path):
  prefix = tmp_path / 'ledger'
  store = LedgerStore(prefix)
  store.append(_entry(note='会被改坏'))
  store.close()

  data = bytearray((prefix.parent / 'ledger.data').read_bytes())
  data[-1] ^= 0xFF  # 改坏最后一个字节
  (prefix.parent / 'ledger.data').write_bytes(bytes(data))

  again = LedgerStore(prefix)
  try:
    report = again.verify()
    assert len(report['bad']) == 1
    with pytest.raises(LedgerError):
      list(again.entries())
  finally:
    again.close()


def test_orphan_frame_detected_and_recovered(tmp_path):
  prefix = tmp_path / 'ledger'
  store = LedgerStore(prefix)
  store.append(_entry(note='正式'))
  store.close()

  # 手工往 data 尾部写一条完整帧，但不进索引 —— 模拟"数据落盘、索引没记"的崩溃点
  blob = json.dumps(_entry(note='孤儿'), ensure_ascii=False).encode('utf-8')
  frame = HDR.pack(len(blob), zlib.crc32(blob)) + blob
  with open(str(prefix) + '.data', 'ab') as fh:
    fh.write(frame)

  again = LedgerStore(prefix)
  try:
    report = again.verify()
    assert len(report['orphans']) == 1
    dry = again.recover(dry_run=True)
    assert dry['orphans_found'] == 1
    assert dry['recovered'] == 1
    assert len(list(again.entries())) == 1  # dry 不写

    done = again.recover()
    assert done['recovered'] == 1
    notes = [e['note'] for _s, e in again.entries()]
    assert notes == ['正式', '孤儿']
  finally:
    again.close()


def test_entry_too_large_rejected(tmp_path):
  store = LedgerStore(tmp_path / 'ledger')
  try:
    with pytest.raises(LedgerError):
      store.append(_entry(note='x' * (1 << 20)))
  finally:
    store.close()


def test_empty_ledger(tmp_path):
  store = LedgerStore(tmp_path / 'ledger')
  try:
    assert list(store.entries()) == []
    report = store.verify()
    assert report['entries'] == 0
    assert report['orphans'] == []
  finally:
    store.close()


def test_cli_add_and_sum(tmp_path, capsys):
  path = str(tmp_path / 'cli')
  assert main(['--file', path, 'add', '--amount', '250', '--note', '跑了一轮', '--kind', 'api', '--tag', 'oss']) == 0
  assert main(['--file', path, 'add', '--amount', '150', '--note', '读码', '--kind', 'task']) == 0
  capsys.readouterr()

  assert main(['--file', path, 'sum', '--by', 'kind']) == 0
  out = capsys.readouterr().out
  assert 'api' in out
  assert '2.50' in out  # 250 分
  assert '1.50' in out  # 150 分
  assert '4.00' in out  # 合计 400 分


def test_cli_list_filters(tmp_path, capsys):
  path = str(tmp_path / 'cli2')
  main(['--file', path, 'add', '--amount', '100', '--note', 'A', '--tag', 'x'])
  main(['--file', path, 'add', '--amount', '200', '--note', 'B', '--tag', 'y'])
  capsys.readouterr()

  assert main(['--file', path, 'list', '--tag', 'x']) == 0
  out = capsys.readouterr().out
  assert 'A' in out
  assert 'B' not in out


def test_parse_when_and_money():
  assert parse_when('2026-11-01') > 0
  assert parse_when('2026-11-01 13:50') > parse_when('2026-11-01')
  with pytest.raises(argparse_type_error()):
    parse_when('昨天')
  assert fmt_money(0) == '0.00'
  assert fmt_money(3) == '0.03'
  assert fmt_money(-250) == '-2.50'


def argparse_type_error():
  import argparse

  return argparse.ArgumentTypeError
