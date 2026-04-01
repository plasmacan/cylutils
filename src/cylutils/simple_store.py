import json
import queue
import sqlite3
import threading
import time

DEFAULT_STORE_NAME = "DEFAULT.STORE"
_TYPE_TAG = "__SIMPLESTORE__TYPE__"


class _Serializer:
    @staticmethod
    def dumps(val) -> str:
        if isinstance(val, (set, frozenset)):
            return json.dumps({_TYPE_TAG: "set", "v": list(val)})
        if isinstance(val, tuple):
            return json.dumps({_TYPE_TAG: "tuple", "v": list(val)})
        return json.dumps(val)

    @staticmethod
    def loads(raw: str):
        val = json.loads(raw)
        if isinstance(val, dict) and _TYPE_TAG in val:
            tag = val[_TYPE_TAG]
            if tag == "set":
                return set(val["v"])
            if tag == "tuple":
                return tuple(val["v"])
        return val


class Store:
    def __init__(
        self,
        store_name=DEFAULT_STORE_NAME,
        delete_on_expire=False,
    ):
        """
        A simple key-value store that persists data. It supports basic CRUD operations and optional expiration of entries.

        All database operations are serialized through a dedicated worker thread,
        making this store safe to use from multiple threads concurrently.

        Parameters:
            store_name (str): The name of the SQLite database file to use for storage.
            delete_on_expire (bool): If True, expired keys will be automatically deleted when accessed.
        """

        self.delete_on_expire = delete_on_expire
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, args=(store_name,), daemon=True)
        self._worker.start()

    def get(self, k: str) -> any:
        """
        Get the value for a key. Returns None if the key does not exist or has expired.

        Parameters:
            k (str): The key to retrieve.

        Returns:
            any: The value associated with the key, or None if the key does not exist or has expired.
        """
        return self._submit(self._get, k)

    def put(self, k: str, val: any, exp: int = 0) -> bool:
        """
        Put a key-value pair into the store. If the key already exists, it will not be updated.

        Parameters:
            k (str): The key to store.
            val (any): The value to store.
            exp (int): The expiration time in seconds. If 0, the key will not expire.

        Returns:
            bool: True if the key-value pair was added, False if the key already exists.
        """
        return self._submit(self._put, k, val, exp)

    def increment(
        self,
        k: str,
        sk: list[str] = None,
        by: int = 1,
        exp: int = 0,
        init_value: int = 0,
        update_exp: bool = False,
    ) -> int:
        """
        Atomically increment a numeric value in the store.

        Parameters:
            k (str): The key of the value to increment.
            sk (str): The sub-key chain to the numeric value to increment. If None, the top-level value is incremented.
            exp (int): The expiration time in seconds to set if the key is created.
            init_value (int): The initial value to set if the key is created. Defaults to 0.
            by (int): The amount to increment by. Defaults to 1.
            update_exp (bool): If True, the expiration time will be updated on each increment. Defaults to False.
        """

        return self._submit(self._increment, k, sk, by, exp, init_value, update_exp)

    def patch(
        self,
        k: str,
        val,
        exp: int = 0,
        create_if_missing: bool = False,
        create_exp=None,
        type_checking: bool = True,
    ) -> bool:
        """
        Patch a key-value pair in the store.

        For dicts, the new value is merged into the existing value. For all other types, the value is replaced.

        Parameters:
            k (str): The key to patch.
            val: The value to patch.
            exp (int): The expiration time in seconds. If 0, the key will not expire.
            create_if_missing (bool): If True, the key-value pair will be created if the key does not exist.
            create_exp (int): The expiration time in seconds to use if create_if_missing is True and the key does not exist. If None, the exp parameter will be used.
            type_checking (bool): If True (default), the patch will fail if the type of val does not match the type of the existing value.

        Returns:
            bool: True if the key-value pair was patched or created, False if the key does not exist and create_if_missing is False, or if type_checking is True and types do not match.
        """
        return self._submit(self._patch, k, val, exp, create_if_missing, create_exp, type_checking)

    def delete(self, k: str) -> bool:
        """
        Delete a key-value pair from the store.
        Parameters:
            k (str): The key to delete.
        Returns:
            bool: True if the key-value pair was deleted, False if the key does not exist.
        """
        return self._submit(self._delete, k)

    def _submit(self, fn, *args):
        result_event = threading.Event()
        container = {}
        self._queue.put((fn, args, container, result_event))
        result_event.wait()
        if "exc" in container:
            raise container["exc"]
        return container.get("val")

    def _run(self, store_name: str):
        conn = self._get_conn(store_name)
        while True:
            fn, args, container, event = self._queue.get()
            try:
                container["val"] = fn(conn, *args)
            except Exception as e:
                container["exc"] = e
            finally:
                event.set()

    def _get(self, conn, k):
        self._clean(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM store WHERE key = ?", (k,))
        result = cursor.fetchone()
        if result:
            return _Serializer.loads(result[0])
        return None

    def _increment(self, conn, k, sk, by, exp, init_value, update_exp):
        self._clean(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value, exp FROM store WHERE key = ?", (k,))
        result = cursor.fetchone()
        if result is None:
            val = init_value
            serialized = _Serializer.dumps(val)
            cursor.execute("INSERT INTO store (key, value, exp) VALUES (?, ?, ?)", (k, serialized, exp))
        else:
            val = _Serializer.loads(result[0])
            existing_exp = result[1]
            if sk and isinstance(val, dict):
                target = val
                for subkey in sk[:-1]:
                    target = target.setdefault(subkey, {})
                last_key = sk[-1]
                target[last_key] = target.get(last_key, init_value) + by
            else:
                val += by
            new_exp = exp if update_exp else existing_exp
            serialized = _Serializer.dumps(val)
            cursor.execute("UPDATE store SET value = ?, exp = ? WHERE key = ?", (serialized, new_exp, k))
        conn.commit()
        return val

    def _put(self, conn, k, val, exp):
        self._clean(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM store WHERE key = ?", (k,))
        result = cursor.fetchone()
        if result:
            return False
        val = _Serializer.dumps(val)
        cursor.execute("INSERT INTO store (key, value, exp) VALUES (?, ?, ?)", (k, val, exp))
        conn.commit()
        return True

    def _patch(self, conn, k, val, exp, create_if_missing, create_exp, type_checking):
        self._clean(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value, exp FROM store WHERE key = ?", (k,))
        result = cursor.fetchone()
        if result:
            existing_val = _Serializer.loads(result[0])
            if type_checking and type(existing_val) is not type(val):
                return False
            if isinstance(existing_val, dict) and isinstance(val, dict):
                existing_val.update(val)
                new_val = _Serializer.dumps(existing_val)
            elif isinstance(existing_val, (list, tuple, set)) and isinstance(val, (list, tuple, set)):
                merged = list(existing_val) + list(val)
                new_val = _Serializer.dumps(type(existing_val)(merged))
            else:
                new_val = _Serializer.dumps(val)
            cursor.execute("UPDATE store SET value = ?, exp = ? WHERE key = ?", (new_val, exp, k))
            conn.commit()
            return True
        elif create_if_missing:
            if create_exp is None:
                create_exp = exp
            return self._put(conn, k, val, create_exp)
        return False

    def _delete(self, conn, k):
        self._clean(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM store WHERE key = ?", (k,))
        result = cursor.fetchone()
        if not result:
            return False
        cursor.execute("DELETE FROM store WHERE key = ?", (k,))
        conn.commit()
        return True

    def _clean(self, conn):
        if not self.delete_on_expire:
            return
        current_time = time.time()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM store WHERE exp > 0 AND exp < ?", (current_time,))

    def _get_conn(self, store_name: str):
        conn = sqlite3.connect(store_name)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS store (key TEXT PRIMARY KEY, value TEXT, exp REAL)")
        conn.commit()
        return conn
