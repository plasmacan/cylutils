import json

import pytest

from cylutils.simple_store import _TYPE_TAG, _Serializer


class TestDumps:
    def test_int(self):
        assert _Serializer.dumps(42) == "42"

    def test_str(self):
        assert _Serializer.dumps("hi") == '"hi"'

    def test_none(self):
        assert _Serializer.dumps(None) == "null"

    def test_list(self):
        assert json.loads(_Serializer.dumps([1, 2])) == [1, 2]

    def test_dict(self):
        assert json.loads(_Serializer.dumps({"a": 1})) == {"a": 1}

    def test_set(self):
        raw = _Serializer.dumps({10, 20})
        data = json.loads(raw)
        assert data[_TYPE_TAG] == "set"
        assert set(data["v"]) == {10, 20}

    def test_frozenset(self):
        raw = _Serializer.dumps(frozenset([3, 4]))
        data = json.loads(raw)
        assert data[_TYPE_TAG] == "set"
        assert set(data["v"]) == {3, 4}

    def test_tuple(self):
        raw = _Serializer.dumps((7, 8, 9))
        data = json.loads(raw)
        assert data[_TYPE_TAG] == "tuple"
        assert data["v"] == [7, 8, 9]


class TestLoads:
    def test_plain_int(self):
        assert _Serializer.loads("99") == 99

    def test_plain_list(self):
        assert _Serializer.loads("[1,2]") == [1, 2]

    def test_plain_dict_without_type_tag(self):
        assert _Serializer.loads('{"x":1}') == {"x": 1}

    def test_set_roundtrip(self):
        assert _Serializer.loads(_Serializer.dumps({1, 2, 3})) == {1, 2, 3}

    def test_tuple_roundtrip(self):
        assert _Serializer.loads(_Serializer.dumps((5, 6))) == (5, 6)

    def test_unknown_type_tag_returns_dict_as_is(self):
        # _TYPE_TAG is present but tag is neither "set" nor "tuple" → returns the dict unchanged
        raw = json.dumps({_TYPE_TAG: "exotic", "v": [1, 2]})
        result = _Serializer.loads(raw)
        assert result == {_TYPE_TAG: "exotic", "v": [1, 2]}
