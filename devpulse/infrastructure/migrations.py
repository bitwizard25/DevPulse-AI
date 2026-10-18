"""Versioned SQLite upgrade with a consistent backup before changing existing state."""

import sqlite3
import time
from contextlib import closing

SCHEMA_VERSION = 6


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
    agent_columns = {row['name'] for row in db.execute('PRAGMA table_info(agent_sessions)')}
    add_permission = (
        "ALTER TABLE agent_sessions ADD COLUMN permission TEXT NOT NULL DEFAULT 'ask';"
        if agent_columns and 'permission' not in agent_columns
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
        CREATE TABLE IF NOT EXISTS index_permissions (
            project TEXT PRIMARY KEY, allowed INTEGER NOT NULL CHECK(allowed IN (0,1))
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            project UNINDEXED, path, kind UNINDEXED, start UNINDEXED, end UNINDEXED, text
        );
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            permission TEXT NOT NULL DEFAULT 'ask'
        );
        """
        + add_permission
        + """
        CREATE INDEX IF NOT EXISTS agent_sessions_project ON agent_sessions(project,updated);
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS agent_messages_session ON agent_messages(session_id,id);
        CREATE TABLE IF NOT EXISTS agent_turns (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task TEXT NOT NULL,
            status TEXT NOT NULL, started REAL NOT NULL, finished REAL, summary TEXT, error TEXT,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS agent_turns_session ON agent_turns(session_id,started);
        CREATE TABLE IF NOT EXISTS agent_actions (
            turn_id TEXT NOT NULL, call_id TEXT NOT NULL, name TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, PRIMARY KEY(turn_id,call_id),
            FOREIGN KEY(turn_id) REFERENCES agent_turns(id) ON DELETE CASCADE
        );
        PRAGMA user_version=6;
        COMMIT;
    """
    )
