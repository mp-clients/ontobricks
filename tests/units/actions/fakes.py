from contextlib import contextmanager


class FakeCursor:
    def __init__(self, rows=None):
        self.executed = []          # list of SQL strings
        self.params = []            # list of param tuples
        self._rows = rows or []
    def execute(self, sql, params=None):
        self.executed.append(sql)
        self.params.append(params)
    def fetchone(self):
        return self._rows[0] if self._rows else None
    def fetchall(self):
        return list(self._rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakeTxn:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, rows=None):
        self.cursor_obj = FakeCursor(rows)
    def cursor(self):
        return self.cursor_obj
    def transaction(self):
        return _FakeTxn()
    @contextmanager
    def ctx(self):
        yield self
