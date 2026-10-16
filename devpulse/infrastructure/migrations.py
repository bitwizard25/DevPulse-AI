"""Versioned SQLite upgrade with a consistent backup before changing existing state."""

import sqlite3
import time
from contextlib import closing

SCHEMA_VERSION = 3


def migrate(db, home, previous: int):
    try:
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_probe USING fts5(text)')
        db.execute('DROP TABLE temp.fts_probe')
    except sqlite3.OperationalError:
        raise ValueError(
            'This Python SQLite build lacks FTS5. Install a Python build with SQLite FTS5 support.'
        ) from None
    if previous >= SCHEMA_VERSION:
        return
    if previous:
        backup_dir = home / 'backups'
        backup_dir.mkdir(exist_ok=True, mode=0o700)
        destination = backup_dir / f'state-v{previous}-{time.time_ns()}.db'
        with closing(sqlite3.connect(destination)) as backup:
            db.backup(backup)
    old_columns = {row['name'] for row in db.execute('PRAGMA table_info(sessions)')}
    add_owner = (
        'ALTER TABLE sessions ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0;'
        if old_columns and 'owner_pid' not in old_columns
        else ''
    )
    db.executescript(
        """
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, digest TEXT NOT NULL,
            status TEXT NOT NULL, started REAL NOT NULL, finished REAL,
            result TEXT, error TEXT, owner_pid INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY, result TEXT NOT NULL, expires REAL NOT NULL
        );
        """
        + add_owner
        + """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, digest TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL, updated REAL NOT NULL, expires REAL NOT NULL,
            available REAL NOT NULL, owner TEXT, heartbeat REAL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, snapshot TEXT,
            result TEXT, error TEXT
        );
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,available,created);
        CREATE INDEX IF NOT EXISTS jobs_identity ON jobs(project,digest,status);
        CREATE TABLE IF NOT EXISTS circuits (
            key TEXT PRIMARY KEY, failures INTEGER NOT NULL, opened_until REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            project TEXT NOT NULL, path TEXT NOT NULL, fingerprint TEXT NOT NULL,
            kind TEXT NOT NULL, PRIMARY KEY(project,path)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            project UNINDEXED, path, kind UNINDEXED, start UNINDEXED, end UNINDEXED, text
        );
        PRAGMA user_version=3;
        COMMIT;
    """
    )
