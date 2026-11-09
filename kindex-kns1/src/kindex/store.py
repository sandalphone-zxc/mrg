"""Small SQLite adapter; compatible callers may supply their own connect() store."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class SQLiteStore:
    def __init__(self, path):
        if str(path) == ':memory:':
            raise ValueError('Use a database file; separate connections cannot share :memory:')
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
