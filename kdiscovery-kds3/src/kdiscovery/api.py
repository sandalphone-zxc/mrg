"""Workspace initialization and a small persistent GitHub configuration adapter."""
import os
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

def initialize_workspace(path):
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    schema = root/'mrg.format.json'
    raw = files('kdiscovery').joinpath('resources/mrg.format.json').read_bytes()
    if schema.exists() and schema.read_bytes() != raw:
        raise ValueError('Workspace schema differs; use a new workspace or explicitly migrate it')
    if not schema.exists():
        schema.write_bytes(raw)
    return root

class GithubConfiguration:
    def __init__(self, workspace):
        self.path = Path(workspace)/'github-cache.sqlite'
        self.store = self

    def private(self):
        return {'github_key': os.environ.get('GITHUB_TOKEN', '')}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

@contextmanager
def exclusive_run(folder):
    """OS-owned lock; a process crash releases ownership without resetting ledgers."""
    path = Path(folder)/'.run.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    acquired = False
    try:
        if path.stat().st_size == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise RuntimeError('This run is already active; refusing concurrent writes') from None
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
