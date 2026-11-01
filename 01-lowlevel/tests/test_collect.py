"""`ledger.collect` 的单元测试：状态读写 + 余额解析（不联网）。

真实采集依赖外部接口，测试只覆盖"能自己控住"的部分：
- 状态文件的建立、损坏、半写
- 余额响应解析与异常分支
"""

from __future__ import annotations

import json
from typing import Self

import pytest

from ledger import collect


def test_state_path_puts_suffix_on_stem(tmp_path):
  path = collect.state_path(tmp_path / 'ledger')
  assert path.name == 'ledger.state.json'
  assert path.parent == tmp_path


def test_state_roundtrip(tmp_path):
  path = tmp_path / 'ledger.state.json'
  collect.save_state(path, {'last_balance': 94.29, 'updated_at': 1})
  assert collect.load_state(path) == {'last_balance': 94.29, 'updated_at': 1}
  assert path.read_text(encoding='utf-8').endswith('\n')


def test_save_state_creates_parent_directory(tmp_path):
  path = tmp_path / 'missing' / 'deep' / 'ledger.state.json'
  collect.save_state(path, {'last_balance': 1.0})
  assert path.exists()


def test_load_state_missing_returns_empty(tmp_path):
  assert collect.load_state(tmp_path / 'nope.json') == {}


def test_load_state_broken_json_returns_empty(tmp_path):
  path = tmp_path / 'broken.json'
  path.write_text('{not json', encoding='utf-8')
  assert collect.load_state(path) == {}


def _fake_response(payload: bytes):
  class _Resp:
    def read(self) -> bytes:
      return payload

    def __enter__(self) -> Self:
      return self

    def __exit__(self, *exc) -> bool:
      return False

  return _Resp()


def test_fetch_balance_parses_total(monkeypatch):
  body = json.dumps({'balance_infos': [{'currency': 'CNY', 'total_balance': '12.34'}]}).encode()
  monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _fake_response(body))
  assert collect.fetch_balance('key') == pytest.approx(12.34)


def test_fetch_balance_without_infos_exits(monkeypatch):
  monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _fake_response(b'{}'))
  with pytest.raises(SystemExit):
    collect.fetch_balance('key')
