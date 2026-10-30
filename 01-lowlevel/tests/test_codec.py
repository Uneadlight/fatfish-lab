"""手写 TLV 序列化：边界与随机往返测试（禁止 pickle / json 参与实现）。

被测接口（契约，实现方必须提供这些名字）：
    codec.tlv.encode(obj) -> bytes
    codec.tlv.decode(data: bytes) -> Any
    codec.tlv.CodecError
"""

import random
import string

import pytest
from codec.tlv import CodecError, decode, encode

MAX_DEPTH = 3


def _rand_str(rng, maxlen=12):
    n = rng.randint(0, maxlen)
    alphabet = string.ascii_letters + string.digits + "中文测试_-,.!?"
    return "".join(rng.choice(alphabet) for _ in range(n))


def _rand_int(rng):
    choice = rng.random()
    if choice < 0.5:
        return rng.randint(-2**31, 2**31)
    if choice < 0.8:
        return rng.randint(-2**63, 2**63)
    # 超出 64 位，验证变长编码不受限
    return rng.choice([1, -1, 0]) * rng.randint(2**63, 2**80)


def _rand_obj(rng, depth=0):
    kinds = ["int", "str", "bool", "none", "bytes", "float"]
    if depth < MAX_DEPTH:
        kinds += ["list", "dict"]
    kind = rng.choice(kinds)

    if kind == "int":
        return _rand_int(rng)
    if kind == "str":
        return _rand_str(rng)
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "none":
        return None
    if kind == "bytes":
        return bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 16)))
    if kind == "float":
        return rng.choice([0.0, -0.0, 1.5, -3.25, 1e300, -1e-300, 2.2250738585072014e-308])
    if kind == "list":
        return [_rand_obj(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    # dict: 键限定 str/int，值递归
    d = {}
    for _ in range(rng.randint(0, 4)):
        key = _rand_str(rng) if rng.random() < 0.6 else _rand_int(rng)
        d[key] = _rand_obj(rng, depth + 1)
    return d


def test_codec_roundtrip_1000():
    rng = random.Random(20261029)
    objs = [_rand_obj(rng) for _ in range(1000)]
    for i, obj in enumerate(objs):
        blob = encode(obj)
        assert isinstance(blob, bytes)
        back = decode(blob)
        assert back == obj, f"第 {i} 个对象往返不一致: {obj!r} -> {back!r}"


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -1,
        2**63,
        -(2**63) - 1,
        2**200,
        "",
        "中文 emoji 🐟",
        b"",
        b"\x00\xff\xfe",
        [],
        {},
        [1, [2, [3, [4, [5]]]]],
        {"a": {"b": {"c": {"d": [1, 2, 3]}}}},
        {"中文键": "中文值", "n": -42, "t": True, "z": None},
    ],
)
def test_codec_boundary_values(value):
    assert decode(encode(value)) == value


def test_codec_empty_bytes_roundtrip():
    assert decode(encode(b"")) == b""


def test_codec_chinese_utf8_length_prefix():
    s = "中文" * 1000
    blob = encode(s)
    assert decode(blob) == s
    # str 的长度前缀必须是 UTF-8 字节数（6000），不是字符数（2000）
    assert len(s) == 2000
    assert len(s.encode("utf-8")) == 6000
    assert len(blob) < len(s.encode("utf-8")) + 16


def test_codec_10mb_bytes():
    payload = b"x" * (10 * 1024 * 1024)
    blob = encode(payload)
    assert len(blob) >= len(payload)
    assert len(blob) <= len(payload) + 16  # 只有类型 1 字节 + 长度前缀
    assert decode(blob) == payload


def test_codec_rejects_truncated():
    blob = encode({"key": "value", "n": 12345})
    for cut in (1, 2, 5, len(blob) - 1):
        with pytest.raises(CodecError):
            decode(blob[:cut])


def test_codec_rejects_trailing_garbage():
    blob = encode([1, 2, 3]) + b"\x00"
    with pytest.raises(CodecError):
        decode(blob)


def test_codec_rejects_unknown_type_tag():
    with pytest.raises(CodecError):
        decode(b"\xfe")


def test_codec_rejects_oversized_length_prefix():
    # 长度前缀声明 100MB，但实际只有几个字节 -> 必须报错而不是死等/爆内存
    with pytest.raises(CodecError):
        decode(b"\x06" + b"\xff\xff\xff\xff\x7f")


def test_codec_does_not_use_pickle_or_json():
    import inspect

    import codec.tlv as tlv

    src = inspect.getsource(tlv)
    for banned in ("import pickle", "import json", "json.dumps", "pickle.dumps"):
        assert banned not in src, f"实现里出现了禁用项: {banned}"
