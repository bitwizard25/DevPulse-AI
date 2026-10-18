import contextlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.index_access import SQLiteIndexAccess
from devpulse.infrastructure.memory import SQLiteMemoryIndex
from devpulse.infrastructure.state import State
from devpulse.interfaces.cli import main
from devpulse.interfaces.indexing import ensure_index_access


class IndexAccessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.state = State(self.root / 'state')
        self.access = SQLiteIndexAccess(self.state)

    def assert_no_index(self):
        with self.state.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0], 0)

    def test_git_coding_project_is_indexed_without_a_prompt(self):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        (self.project / 'app.py').write_text('def calculate_invoice(): return 42\n')
        with patch('builtins.input') as prompt:
            self.assertTrue(ensure_index_access(self.project, self.state, interactive=True))
        prompt.assert_not_called()
        report = SQLiteMemoryIndex(self.state).refresh(self.project, Vault())
        self.assertEqual(report.status, 'indexed')
        self.assertEqual(report.documents, 1)

    def test_non_git_coding_folder_requires_approval_before_any_index_content(self):
        (self.project / 'app.py').write_text('invoice_total = 42\n')
        (self.project / 'notes.txt').write_text('ordinary unrelated notes')
        index = SQLiteMemoryIndex(self.state)
        self.assertEqual(index.refresh(self.project, Vault()).status, 'needs_approval')
        self.assert_no_index()
        with patch('builtins.input', return_value='y') as prompt:
            self.assertTrue(ensure_index_access(self.project, self.state, interactive=True))
        prompt.assert_called_once()
        report = index.refresh(self.project, Vault())
        self.assertEqual(report.status, 'indexed')
        self.assertEqual(report.documents, 1)
        self.assertEqual(
            SQLiteIndexAccess(State(self.state.home)).decision(self.project).status, 'allowed'
        )

    def test_generated_instructions_and_ignored_source_do_not_classify_as_coding(self):
        (self.project / '.devpulse').mkdir()
        (self.project / '.devpulse/RULES.md').write_text('Generated app instructions')
        (self.project / 'node_modules').mkdir()
        (self.project / 'node_modules/dependency.js').write_text('export default 42;')
        self.assertEqual(self.access.decision(self.project).status, 'not_coding')
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        (self.project / '.gitignore').write_text('*.py\nnode_modules/\n')
        (self.project / 'ignored.py').write_text('value = 42')
        self.assertEqual(self.access.decision(self.project).status, 'not_coding')
        self.assert_no_index()

    def test_cli_json_skips_without_consent_and_explicit_approval_indexes(self):
        (self.project / 'app.py').write_text('invoice_total = 42\n')
        env = {'DEVPULSE_HOME': str(self.state.home)}
        for approved in (False, True):
            with self.subTest(approved=approved):
                output = io.StringIO()
                args = ['--project', str(self.project), 'memory', 'reindex', '--json']
                if approved:
                    args.append('--approve-non-git')
                with (
                    patch.dict(os.environ, env),
                    patch('builtins.input') as prompt,
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(main(args), 0)
                prompt.assert_not_called()
                result = json.loads(output.getvalue())
                self.assertEqual(result['status'], 'indexed' if approved else 'needs_approval')
                self.assertEqual(result['documents'], 1 if approved else 0)

    def test_revoking_consent_removes_previously_indexed_content(self):
        (self.project / 'app.py').write_text('invoice_total = 42\n')
        self.access.set_allowed(self.project, True)
        self.assertEqual(SQLiteMemoryIndex(self.state).refresh(self.project, Vault()).documents, 1)
        self.access.set_allowed(self.project, False)
        self.assert_no_index()

    def test_coding_project_indexes_config_but_not_credentials_or_ordinary_notes(self):
        (self.project / 'app.py').write_text('invoice_total = 42\n')
        (self.project / 'config.json').write_text('{"invoice_currency": "USD"}')
        (self.project / 'credentials.json').write_text('{"private_value": "do-not-index"}')
        (self.project / 'notes.txt').write_text('Unrelated personal notes')
        self.access.set_allowed(self.project, True)
        for git_repo in (False, True):
            with self.subTest(git_repo=git_repo):
                if git_repo:
                    subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
                report = SQLiteMemoryIndex(self.state).refresh(self.project, Vault())
                self.assertEqual(report.documents, 2)
                with self.state.connect() as db:
                    paths = {row[0] for row in db.execute('SELECT path FROM documents')}
                self.assertEqual(paths, {'app.py', 'config.json'})

    def test_version_five_upgrade_backs_up_existing_state_and_preserves_cache(self):
        self.state.cache_put('existing-result', {'summary': 'Preserved'}, 3600)
        with self.state.connect() as db:
            db.execute('DROP TABLE index_permissions')
            db.execute('PRAGMA user_version=5')
        upgraded = State(self.state.home)
        self.assertEqual(upgraded.cache_get('existing-result')['summary'], 'Preserved')
        backups = list((self.state.home / 'backups').glob('state-v5-*.db'))
        self.assertEqual(len(backups), 1)
        with contextlib.closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
            self.assertFalse(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name='index_permissions'"
                ).fetchall()
            )
        with upgraded.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)

    def test_ordinary_files_do_not_create_an_index_even_inside_git(self):
        for git_repo in (False, True):
            with self.subTest(git_repo=git_repo):
                if git_repo:
                    subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
                (self.project / 'notes.txt').write_text('meeting notes')
                with patch('builtins.input') as prompt:
                    self.assertFalse(
                        ensure_index_access(self.project, self.state, interactive=True)
                    )
                prompt.assert_not_called()
                report = SQLiteMemoryIndex(self.state).refresh(self.project, Vault())
                self.assertEqual(report.status, 'not_coding')
                self.assertIn('not a coding repository', report.skipped[0].lower())
                self.assert_no_index()

    def test_noninteractive_run_does_not_approve_and_decline_is_remembered(self):
        (self.project / 'README.md').write_text('# Project\n')
        with patch('builtins.input') as prompt:
            self.assertFalse(ensure_index_access(self.project, self.state, interactive=False))
        prompt.assert_not_called()
        self.assert_no_index()
        with patch('builtins.input', return_value='n'):
            self.assertFalse(ensure_index_access(self.project, self.state, interactive=True))
        with patch('builtins.input') as prompt:
            self.assertFalse(ensure_index_access(self.project, self.state, interactive=True))
        prompt.assert_not_called()
        self.assertEqual(self.access.decision(self.project).status, 'declined')
        self.assert_no_index()


if __name__ == '__main__':
    unittest.main()
