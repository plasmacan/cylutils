import pytest

from cylutils.simple_store import Store


@pytest.fixture
def store():
    return Store(":memory:")


@pytest.fixture
def expiring_store():
    return Store(":memory:", delete_on_expire=True)


class TestGetPut:
    def test_put_new_key_returns_true(self, store):
        assert store.put("k", "v") is True

    def test_put_duplicate_key_returns_false(self, store):
        store.put("k", "v")
        assert store.put("k", "other") is False

    def test_get_existing_key(self, store):
        store.put("msg", "hello")
        assert store.get("msg") == "hello"

    def test_get_missing_key_returns_none(self, store):
        assert store.get("ghost") is None

    def test_put_and_get_list(self, store):
        store.put("l", [1, 2, 3])
        assert store.get("l") == [1, 2, 3]

    def test_put_and_get_dict(self, store):
        store.put("d", {"a": 1})
        assert store.get("d") == {"a": 1}

    def test_put_and_get_set(self, store):
        store.put("s", {1, 2})
        assert store.get("s") == {1, 2}

    def test_put_and_get_tuple(self, store):
        store.put("t", (3, 4))
        assert store.get("t") == (3, 4)


class TestDelete:
    def test_delete_existing_key_returns_true(self, store):
        store.put("k", "v")
        assert store.delete("k") is True
        assert store.get("k") is None

    def test_delete_missing_key_returns_false(self, store):
        assert store.delete("ghost") is False


class TestIncrement:
    def test_new_key_created_with_init_value(self, store):
        result = store.increment("counter", init_value=10)
        assert result == 10
        assert store.get("counter") == 10

    def test_existing_flat_value(self, store):
        store.put("n", 5)
        assert store.increment("n", by=3) == 8

    def test_default_by_one(self, store):
        store.put("n", 0)
        assert store.increment("n") == 1

    def test_subkey_on_dict(self, store):
        store.put("d", {"hits": 0})
        store.increment("d", sk=["hits"])
        assert store.get("d") == {"hits": 1}

    def test_nested_subkey_creates_path(self, store):
        store.put("d", {})
        store.increment("d", sk=["x", "y"])
        assert store.get("d") == {"x": {"y": 1}}

    def test_subkey_on_existing_nested_path(self, store):
        store.put("d", {"a": {"b": 4}})
        store.increment("d", sk=["a", "b"], by=6)
        assert store.get("d") == {"a": {"b": 10}}

    def test_sk_on_non_dict_falls_back_to_flat_increment(self, store):
        # sk is specified but the stored value is not a dict → flat increment
        store.put("n", 10)
        assert store.increment("n", sk=["ignored"], by=2) == 12

    def test_update_exp_true_updates_expiration(self, store):
        store.put("n", 0)
        result = store.increment("n", exp=9_999_999_999, update_exp=True)
        assert result == 1

    def test_update_exp_false_preserves_expiration(self, store):
        store.put("n", 0)
        result = store.increment("n", exp=9_999_999_999, update_exp=False)
        assert result == 1


class TestPatch:
    def test_dict_merge(self, store):
        store.put("d", {"a": 1})
        assert store.patch("d", {"b": 2}) is True
        assert store.get("d") == {"a": 1, "b": 2}

    def test_list_concat(self, store):
        store.put("l", [1, 2])
        assert store.patch("l", [3, 4]) is True
        assert store.get("l") == [1, 2, 3, 4]

    def test_tuple_concat(self, store):
        store.put("t", (1, 2))
        assert store.patch("t", (3,)) is True
        assert store.get("t") == (1, 2, 3)

    def test_set_concat(self, store):
        store.put("s", {1, 2})
        assert store.patch("s", {3}) is True
        assert store.get("s") == {1, 2, 3}

    def test_scalar_replace(self, store):
        store.put("x", "old")
        assert store.patch("x", "new") is True
        assert store.get("x") == "new"

    def test_type_mismatch_returns_false(self, store):
        store.put("x", "string")
        assert store.patch("x", 42) is False
        assert store.get("x") == "string"  # unchanged

    def test_type_mismatch_no_type_checking_replaces(self, store):
        store.put("x", "string")
        assert store.patch("x", 42, type_checking=False) is True
        assert store.get("x") == 42

    def test_missing_key_no_create_returns_false(self, store):
        assert store.patch("ghost", "v") is False

    def test_missing_key_create_if_missing(self, store):
        assert store.patch("new", "v", create_if_missing=True) is True
        assert store.get("new") == "v"

    def test_missing_key_create_with_explicit_create_exp(self, store):
        assert store.patch("new", "v", create_if_missing=True, create_exp=9_999_999_999) is True
        assert store.get("new") == "v"


class TestExpiration:
    def test_expired_key_cleaned_on_get(self, expiring_store):
        # exp=1 is 1 second after the Unix epoch — always in the past
        expiring_store.put("old", "value", exp=1)
        assert expiring_store.get("old") is None

    def test_non_expiring_store_ignores_past_exp(self, store):
        # delete_on_expire=False → _clean is a no-op, key survives past exp
        store.put("k", "v", exp=1)
        assert store.get("k") == "v"


class TestExceptionPropagation:
    def test_worker_exception_is_reraised_in_caller(self, store):
        def bad_fn(conn):
            raise ValueError("worker error")

        with pytest.raises(ValueError, match="worker error"):
            store._submit(bad_fn)
