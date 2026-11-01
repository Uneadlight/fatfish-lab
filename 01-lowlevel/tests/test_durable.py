"""DurableTree 测试：持久性、幂等、崩溃后恢复。"""

from __future__ import annotations

import pytest

from bplus.durable import DurableTree, ack_key


def test_basic_put_and_get(tmp_path):
  path = str(tmp_path / 'basic.tree')
  tree = DurableTree(path)
  try:
    assert tree.put(1, 100) is True
    assert tree.put(2, 200) is True
    assert tree.get(1) == 100
    assert tree.get_or(99) is None
    assert len(tree) == 2
  finally:
    tree.close()


def test_reopen_keeps_data(tmp_path):
  path = str(tmp_path / 'reopen.tree')
  tree = DurableTree(path)
  try:
    for i in range(20):
      tree.put(i, i * 10)
  finally:
    tree.close()

  again = DurableTree(path)
  try:
    assert len(again) == 20
    for i in range(20):
      assert again.get(i) == i * 10
  finally:
    again.close()


def test_idempotent_request_id(tmp_path):
  path = str(tmp_path / 'idem.tree')
  tree = DurableTree(path)
  try:
    assert tree.put(1, 111, request_id='req-a') is True
    assert tree.put(2, 222, request_id='req-a') is False  # 重复，整笔忽略
    assert tree.get(1) == 111
    assert tree.get_or(2) is None

    assert tree.put(3, 333, request_id='req-b') is True
    assert tree.put(3, 999, request_id='req-b') is False
    assert tree.get(3) == 333
  finally:
    tree.close()


def test_idempotent_survives_restart(tmp_path):
  path = str(tmp_path / 'idem2.tree')
  tree = DurableTree(path)
  try:
    assert tree.put(1, 111, request_id='once') is True
  finally:
    tree.close()

  again = DurableTree(path)
  try:
    assert again.put(2, 222, request_id='once') is False
    assert again.get_or(2) is None
  finally:
    again.close()


def test_ack_key_shape():
  k = ack_key('some-request-id')
  assert k < 0
  assert ack_key('some-request-id') == k
  assert ack_key('other') != k


def test_negative_key_is_rejected(tmp_path):
  path = str(tmp_path / 'neg.tree')
  tree = DurableTree(path)
  try:
    with pytest.raises(ValueError, match='非负'):
      tree.put(-5, 1)
  finally:
    tree.close()


def test_range_scan_hides_ack_marks(tmp_path):
  path = str(tmp_path / 'scan.tree')
  tree = DurableTree(path)
  try:
    for i in range(5):
      tree.put(i, i * 100, request_id=f'r{i}')
    rows = tree.range_scan()
    assert [k for k, _ in rows] == [0, 1, 2, 3, 4]
    assert all(k >= 0 for k, _ in rows)
    assert tree.range_scan(1, 3) == [(1, 100), (2, 200), (3, 300)]
  finally:
    tree.close()


def test_commit_before_page_write_recovers(tmp_path, monkeypatch):
  """模拟"WAL 已提交、页还没写"就崩溃：重开时必须重放出来。"""
  path = str(tmp_path / 'crash.tree')
  tree = DurableTree(path)
  try:
    tree.put(1, 111)
  finally:
    tree.close()

  victim = DurableTree(path)
  original = victim._pool.flush_dirty

  def explode():
    raise RuntimeError('模拟提交后崩溃')

  monkeypatch.setattr(victim._pool, 'flush_dirty', explode)
  with pytest.raises(RuntimeError, match='模拟'):
    victim.put(2, 222)
  # 崩溃即"进程死掉"：不调用 close()，直接放手（锁随进程释放，这里手动放）
  monkeypatch.setattr(victim._pool, 'flush_dirty', original)
  victim._pool.drop_dirty()
  victim._wal.close()
  victim._tree._pf.close()
  victim._lock.release()

  revived = DurableTree(path)
  try:
    assert revived.get(1) == 111
    assert revived.get(2) == 222, '已提交的 txn 必须重放出来'
  finally:
    revived.close()


def test_uncommitted_is_not_replayed(tmp_path, monkeypatch):
  """提交点之前崩溃：这次改动整体作废，不能出现在恢复后的树里。"""
  path = str(tmp_path / 'nocommit.tree')
  tree = DurableTree(path)
  try:
    tree.put(1, 111)
  finally:
    tree.close()

  victim = DurableTree(path)

  def explode(txn):
    raise RuntimeError('模拟提交前崩溃')

  monkeypatch.setattr(victim._wal, 'commit', explode)
  with pytest.raises(RuntimeError, match='模拟'):
    victim.put(2, 222)
  victim._pool.drop_dirty()
  victim._wal.close()
  victim._tree._pf.close()
  victim._lock.release()

  revived = DurableTree(path)
  try:
    assert revived.get(1) == 111
    assert revived.get_or(2) is None, '未提交的写不该出现'
  finally:
    revived.close()


def test_wal_is_truncated_after_recovery(tmp_path, monkeypatch):
  """恢复完要清空 WAL，否则日志会随着每次重启无限增长。"""
  path = str(tmp_path / 'trunc.tree')
  tree = DurableTree(path)
  try:
    tree.put(1, 111)
  finally:
    tree.close()

  victim = DurableTree(path)

  def explode():
    raise RuntimeError('boom')

  monkeypatch.setattr(victim._pool, 'flush_dirty', explode)
  with pytest.raises(RuntimeError):
    victim.put(2, 222)
  victim._pool.drop_dirty()
  victim._wal.close()
  victim._tree._pf.close()
  victim._lock.release()

  # 崩溃前 WAL 非空
  import os

  assert os.path.getsize(path + '.wal') > 0

  revived = DurableTree(path)
  try:
    assert revived.stats['wal_size'] == 0
  finally:
    revived.close()


def test_many_writes_survive_reopen(tmp_path):
  path = str(tmp_path / 'bulk.tree')
  tree = DurableTree(path)
  try:
    for i in range(200):
      tree.put(i, i + 1000)
  finally:
    tree.close()

  again = DurableTree(path)
  try:
    assert len(again) == 200
    for i in (0, 50, 199):
      assert again.get(i) == i + 1000
  finally:
    again.close()
