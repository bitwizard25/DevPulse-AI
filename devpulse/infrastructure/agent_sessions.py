"""SQLite-backed conversation metadata and bounded, already-redacted turns."""

import builtins
import json
import time
import uuid

from .state import State

MAX_MESSAGES = 200
MAX_MESSAGE_BYTES = 65536


class SQLiteAgentSessions:
    def __init__(self, state: State):
        self.state = state

    def create(self, project: str, title: str) -> dict:
        session_id = uuid.uuid4().hex
        now = time.time()
        with self.state.connect() as db:
            db.execute(
                'INSERT INTO agent_sessions(id,project,title,status,created,updated) VALUES(?,?,?,?,?,?)',
                (session_id, project, title[:160], 'active', now, now),
            )
        return self.get(session_id)

    def get(self, session_id: str) -> dict:
        with self.state.connect() as db:
            row = db.execute(
                'SELECT id,project,title,status,created,updated,permission FROM agent_sessions WHERE id=?',
                (session_id,),
            ).fetchone()
        if not row:
            raise ValueError('Unknown agent session.')
        return dict(row)

    def latest(self, project: str) -> dict | None:
        with self.state.connect() as db:
            row = db.execute(
                "SELECT id,project,title,status,created,updated FROM agent_sessions WHERE project=? AND status='active' ORDER BY updated DESC LIMIT 1",
                (project,),
            ).fetchone()
        return dict(row) if row else None

    def list(self, project: str, limit: int = 20) -> builtins.list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError('Session limit must be between 1 and 200.')
        with self.state.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    'SELECT id,project,title,status,created,updated FROM agent_sessions WHERE project=? ORDER BY updated DESC LIMIT ?',
                    (project, limit),
                )
            ]

    def messages(self, session_id: str) -> builtins.list[dict]:
        self.get(session_id)
        with self.state.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    'SELECT role,content,created FROM agent_messages WHERE session_id=? ORDER BY id',
                    (session_id,),
                )
            ]

    def append(self, session_id: str, role: str, content: str):
        if role not in ('user', 'assistant', 'tool'):
            raise ValueError('Invalid agent message role.')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_MESSAGE_BYTES:
            raise ValueError('Agent message exceeds the 64 KB storage limit.')
        now = time.time()
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            session = db.execute(
                "SELECT id FROM agent_sessions WHERE id=? AND status='active'", (session_id,)
            ).fetchone()
            if not session:
                raise ValueError('Agent session is not active.')
            count = db.execute(
                'SELECT COUNT(*) FROM agent_messages WHERE session_id=?', (session_id,)
            ).fetchone()[0]
            if count >= MAX_MESSAGES:
                db.execute(
                    'DELETE FROM agent_messages WHERE session_id=? AND id IN (SELECT id FROM agent_messages WHERE session_id=? ORDER BY id LIMIT ?)',
                    (session_id, session_id, count - MAX_MESSAGES + 1),
                )
            db.execute(
                'INSERT INTO agent_messages(session_id,role,content,created) VALUES(?,?,?,?)',
                (session_id, role, content, now),
            )
            db.execute('UPDATE agent_sessions SET updated=? WHERE id=?', (now, session_id))

    def set_title(self, session_id: str, title: str):
        with self.state.connect() as db:
            db.execute(
                "UPDATE agent_sessions SET title=?,updated=? WHERE id=? AND status='active'",
                (title[:160], time.time(), session_id),
            )

    def close(self, session_id: str):
        with self.state.connect() as db:
            db.execute(
                "UPDATE agent_sessions SET status='closed',updated=? WHERE id=?",
                (time.time(), session_id),
            )

    def clear(self, session_id: str):
        with self.state.connect() as db:
            db.execute(
                'DELETE FROM agent_actions WHERE turn_id IN (SELECT id FROM agent_turns WHERE session_id=?)',
                (session_id,),
            )
            db.execute('DELETE FROM agent_turns WHERE session_id=?', (session_id,))
            db.execute('DELETE FROM agent_messages WHERE session_id=?', (session_id,))
            db.execute('DELETE FROM agent_sessions WHERE id=?', (session_id,))

    def set_permission(self, session_id: str, mode: str):
        if mode not in ('ask', 'edit', 'auto'):
            raise ValueError('Permission mode must be ask, edit or auto.')
        with self.state.connect() as db:
            db.execute('UPDATE agent_sessions SET permission=? WHERE id=?', (mode, session_id))

    def begin_turn(self, session_id, task):
        turn_id = uuid.uuid4().hex
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute(
                "SELECT id FROM agent_sessions WHERE id=? AND status='active'", (session_id,)
            ).fetchone():
                raise ValueError('Agent session is not active.')
            if db.execute(
                "SELECT id FROM agent_turns WHERE session_id=? AND status='running'", (session_id,)
            ).fetchone():
                raise ValueError('This session already has a running turn.')
            db.execute(
                'INSERT INTO agent_turns(id,session_id,task,status,started) VALUES(?,?,?,?,?)',
                (turn_id, session_id, task, 'running', time.time()),
            )
        return turn_id

    def finish_turn(self, turn_id, status, *, summary=None, error=None):
        if status not in ('succeeded', 'failed', 'interrupted'):
            raise ValueError('Invalid terminal turn status.')
        with self.state.connect() as db:
            db.execute(
                "UPDATE agent_turns SET status=?,finished=?,summary=?,error=? WHERE id=? AND status='running'",
                (status, time.time(), summary, error, turn_id),
            )
            db.execute(
                "UPDATE agent_actions SET status='uncertain' WHERE turn_id=? AND status='started'",
                (turn_id,),
            )

    def begin_action(self, turn_id, call_id, name):
        with self.state.connect() as db:
            db.execute(
                'INSERT INTO agent_actions(turn_id,call_id,name,status) VALUES(?,?,?,?)',
                (turn_id, call_id, name, 'started'),
            )

    def finish_action(self, turn_id, call_id, result):
        summary = {
            key: result[key]
            for key in ('status', 'path', 'exit_code', 'timed_out', 'error', 'provenance')
            if key in result
        }
        status = (
            'failed'
            if 'error' in result
            else 'denied'
            if result.get('status') == 'denied'
            else 'completed'
        )
        with self.state.connect() as db:
            db.execute(
                'UPDATE agent_actions SET status=?,result=? WHERE turn_id=? AND call_id=?',
                (status, json.dumps(summary), turn_id, call_id),
            )

    def recover(self, session_id):
        """Only call while owning this session's process lock. Never replay mutations."""
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(
                "UPDATE agent_actions SET status='uncertain' WHERE status='started' AND turn_id IN (SELECT id FROM agent_turns WHERE session_id=? AND status='running')",
                (session_id,),
            )
            changed = db.execute(
                "UPDATE agent_turns SET status='interrupted',finished=?,error='Interrupted; inspect tool effects before retrying.' WHERE session_id=? AND status='running'",
                (time.time(), session_id),
            ).rowcount
        if changed:
            self.append(
                session_id,
                'user',
                'A previous turn was interrupted. Tool effects may have occurred. Inspect current files and command results before continuing; do not blindly replay edits.',
            )

    def turns(self, session_id, limit=20):
        with self.state.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    'SELECT * FROM agent_turns WHERE session_id=? ORDER BY started DESC LIMIT ?',
                    (session_id, limit),
                )
            ]

    def actions(self, turn_id):
        with self.state.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    'SELECT * FROM agent_actions WHERE turn_id=? ORDER BY rowid', (turn_id,)
                )
            ]
