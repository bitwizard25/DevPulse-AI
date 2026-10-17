import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from devpulse.application.agent import AgentSession
from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_sessions import SQLiteAgentSessions
from devpulse.infrastructure.state import State


class AgentStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = State(self.home)
        self.store = SQLiteAgentSessions(self.state)
        self.session_id = self.store.create('project', 'Task')['id']

    def test_interrupted_action_is_journaled_without_replay(self):
        turn = self.store.begin_turn(self.session_id, 'Change retry limit')
        self.store.begin_action(turn, 'edit-1', 'edit_file')
        self.store.recover(self.session_id)
        reopened = SQLiteAgentSessions(State(self.home))
        self.assertEqual(reopened.turns(self.session_id)[0]['status'], 'interrupted')
        self.assertEqual(reopened.actions(turn)[0]['status'], 'uncertain')
        self.assertEqual(len(reopened.actions(turn)), 1)

    def test_session_permission_survives_reopen(self):
        self.store.set_permission(self.session_id, 'edit')
        self.assertEqual(
            SQLiteAgentSessions(State(self.home)).get(self.session_id)['permission'], 'edit'
        )
        with self.assertRaises(ValueError):
            self.store.set_permission(self.session_id, 'unknown')

    def test_loop_interrupt_records_turn_and_unknown_action(self):
        class Tools:
            def describe(self):
                return [{'name': 'run_command'}]

            def execute(self, name, arguments):
                raise KeyboardInterrupt()

        def model(messages):
            return json.dumps(
                {
                    'message': 'Check',
                    'tool_calls': [
                        {'id': 'cmd', 'name': 'run_command', 'arguments': {'argv': ['python']}}
                    ],
                    'final': False,
                }
            )

        session = AgentSession(
            model, Tools(), Vault().scrub, store=self.store, session_id=self.session_id
        )
        with self.assertRaises(KeyboardInterrupt):
            session.run('Inspect the project', 'example')
        turn = self.store.turns(self.session_id)[0]
        self.assertEqual(turn['status'], 'interrupted')
        self.assertEqual(self.store.actions(turn['id'])[0]['status'], 'uncertain')

    def test_version_four_upgrade_backs_up_existing_transcript(self):
        legacy_home = self.home / 'legacy'
        legacy_home.mkdir()
        with closing(sqlite3.connect(legacy_home / 'state.db')) as db:
            db.executescript("""
                CREATE TABLE agent_sessions (id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    title TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE agent_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
            """)
            db.execute(
                'INSERT INTO agent_sessions VALUES(?,?,?,?,?,?)',
                (self.session_id, 'project', 'Task', 'active', 1, 1),
            )
            db.execute('PRAGMA user_version=4')
            db.execute(
                'INSERT INTO agent_messages(session_id,role,content,created) VALUES(?,?,?,?)',
                (self.session_id, 'user', 'keep existing goal', 1),
            )
            db.commit()
        upgraded = SQLiteAgentSessions(State(legacy_home))
        self.assertEqual(upgraded.get(self.session_id)['permission'], 'ask')
        self.assertEqual(upgraded.messages(self.session_id)[0]['content'], 'keep existing goal')
        backups = list((legacy_home / 'backups').glob('state-v4-*.db'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(
                db.execute('SELECT content FROM agent_messages').fetchone()[0], 'keep existing goal'
            )
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
            self.assertNotIn(
                'permission', [row[1] for row in db.execute('PRAGMA table_info(agent_sessions)')]
            )

    def test_closed_session_cannot_begin_another_turn(self):
        self.store.close(self.session_id)
        with self.assertRaisesRegex(ValueError, 'active'):
            self.store.begin_turn(self.session_id, 'Do more work')

    def test_malformed_decision_performs_no_tool_actions(self):
        from devpulse.infrastructure.agent_tools import ProjectTools

        tools = ProjectTools(self.home, lambda *_: True, Vault())
        session = AgentSession(
            lambda _: '{bad JSON',
            tools,
            Vault().scrub,
            store=self.store,
            session_id=self.session_id,
        )
        with self.assertRaisesRegex(ValueError, 'malformed'):
            session.run('Create a file', 'example')
        turn = self.store.turns(self.session_id)[0]
        self.assertEqual(turn['status'], 'failed')
        self.assertEqual(self.store.actions(turn['id']), [])

    def test_clear_removes_turn_and_action_history(self):
        turn = self.store.begin_turn(self.session_id, 'task')
        self.store.begin_action(turn, 'read', 'read_file')
        self.store.finish_action(turn, 'read', {'status': 'done'})
        self.store.finish_turn(turn, 'succeeded', summary='done')
        self.store.clear(self.session_id)
        with self.state.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_turns').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM agent_actions').fetchone()[0], 0)

    def test_session_annotations_are_valid(self):
        import inspect
        ann_messages = inspect.get_annotations(SQLiteAgentSessions.messages)
        self.assertIn('return', ann_messages)
        ann_list = inspect.get_annotations(SQLiteAgentSessions.list)
        self.assertIn('return', ann_list)

