"""SQLite stores metadata and redacted results, never raw source or credentials."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .files import ProcessLock
from .migrations import SCHEMA_VERSION, migrate


class State:
    def __init__(self, home: Path):
        self.home = home.expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / 'state.db'
        with ProcessLock(self.home / 'initialize.lock', timeout=15):
            self._initialize()

    def _initialize(self):
        key_path = self.home / 'identity.key'
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(secrets.token_bytes(32))
        self._key = key_path.read_bytes()
        if len(self._key) != 32:
            raise ValueError('Invalid state identity key; restore identity.key from backup.')
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError('State was created by a newer DevPulse version.')
            migrate(db, self.home, version)
            db.execute('PRAGMA journal_mode=WAL')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def identity(self, value: str) -> str:
        return hmac.new(self._key, value.encode('utf-8'), hashlib.sha256).hexdigest()

    def start(self, project: str, digest: str, owner_pid: int | None = None) -> str:
        session = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                'INSERT INTO sessions(id,project,digest,status,started,owner_pid) VALUES(?,?,?,?,?,?)',
                (
                    session,
                    project,
                    digest,
                    'running',
                    time.time(),
                    os.getpid() if owner_pid is None else owner_pid,
                ),
            )
        return session

    def finish(self, session: str, result: dict | None = None, error: str | None = None):
        with self.connect() as db:
            db.execute(
                'UPDATE sessions SET status=?,finished=?,result=?,error=? WHERE id=?',
                (
                    'failed' if error else 'completed',
                    time.time(),
                    json.dumps(result) if result is not None else None,
                    error,
                    session,
                ),
            )

    def recover(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,owner_pid FROM sessions WHERE status='running'").fetchall()
            for row in rows:
                if not process_alive(row['owner_pid']):
                    db.execute(
                        "UPDATE sessions SET status='interrupted',finished=? WHERE id=? AND status='running'",
                        (time.time(), row['id']),
                    )

    def sessions(self, limit: int = 20, project: str | None = None) -> list[dict]:
        with self.connect() as db:
            query = 'SELECT id,project,status,started,finished,error FROM sessions'
            args: list = []
            if project:
                query += ' WHERE project=?'
                args.append(project)
            return [
                dict(row)
                for row in db.execute(query + ' ORDER BY started DESC LIMIT ?', (*args, limit))
            ]

    def cache_get(self, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                'SELECT result FROM cache WHERE key=? AND expires>?', (key, time.time())
            ).fetchone()
        return json.loads(row['result']) if row else None

    def cache_put(self, key: str, result: dict, ttl: float = 86400):
        with self.connect() as db:
            db.execute('DELETE FROM cache WHERE expires<=?', (time.time(),))
            db.execute(
                'INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                (key, json.dumps(result), time.time() + ttl),
            )

    def clear_cache(self):
        with self.connect() as db:
            db.execute('DELETE FROM cache')

    def prune(self, days: int = 30):
        with self.connect() as db:
            count = db.execute(
                "DELETE FROM sessions WHERE status!='running' AND started<?",
                (time.time() - days * 86400,),
            ).rowcount
            db.execute('DELETE FROM cache WHERE expires<=?', (time.time(),))
            return count


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # An inaccessible process may still be alive.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
