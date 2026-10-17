import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_tools import ProjectTools


class AgentFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = Vault()
        self.tools = ProjectTools(self.root, lambda *_: True, self.vault)

    def test_read_range_reports_position_and_more_content(self):
        (self.root / 'a.py').write_text('one\ntwo\nthree\nfour\nfive\n')
        result = self.tools.execute('read_file', {'path': 'a.py', 'start_line': 3, 'limit': 2})
        self.assertEqual(result['content'], 'three\nfour\n')
        self.assertEqual(
            (result['start_line'], result['end_line'], result['total_lines']), (3, 4, 5)
        )
        self.assertTrue(result['truncated'])

    def test_existing_file_requires_read_and_current_fingerprint(self):
        target = self.root / 'a.py'
        target.write_text('original\n')
        with self.assertRaisesRegex(ValueError, 'read|fingerprint'):
            self.tools.execute('write_file', {'path': 'a.py', 'content': 'replacement\n'})
        original = self.tools.execute('read_file', {'path': 'a.py'})
        target.write_text('user change\n')
        with self.assertRaisesRegex(ValueError, 'changed|stale'):
            self.tools.execute(
                'write_file',
                {
                    'path': 'a.py',
                    'content': 'replacement\n',
                    'expected_fingerprint': original['fingerprint'],
                },
            )
        self.assertEqual(target.read_text(), 'user change\n')

    def test_exact_edit_preserves_unrelated_secret_and_crlf(self):
        target = self.root / 'a.py'
        target.write_bytes(b'password="keep-private"\r\nresult = 1\r\n')
        read = self.tools.execute('read_file', {'path': 'a.py'})
        result = self.tools.execute(
            'edit_file',
            {
                'path': 'a.py',
                'old_text': 'result = 1',
                'new_text': 'result = 2',
                'expected_fingerprint': read['fingerprint'],
            },
        )
        self.assertEqual(target.read_bytes(), b'password="keep-private"\r\nresult = 2\r\n')
        self.assertNotIn('keep-private', json.dumps(result))

    def test_redacted_full_replacement_cannot_erase_secret(self):
        target = self.root / 'a.py'
        target.write_text('password="keep-private"\nresult = 1\n')
        read = self.tools.execute('read_file', {'path': 'a.py'})
        with self.assertRaisesRegex(ValueError, 'secret|redacted|edit_file'):
            self.tools.execute(
                'write_file',
                {
                    'path': 'a.py',
                    'content': read['content'].replace('result = 1', 'result = 2'),
                    'expected_fingerprint': read['fingerprint'],
                },
            )
        self.assertIn('keep-private', target.read_text())

    def test_edit_rejects_ambiguous_match(self):
        target = self.root / 'a.py'
        target.write_text('value = 1\nvalue = 1\n')
        read = self.tools.execute('read_file', {'path': 'a.py'})
        with self.assertRaisesRegex(ValueError, 'unique|exactly once|ambiguous'):
            self.tools.execute(
                'edit_file',
                {
                    'path': 'a.py',
                    'old_text': 'value = 1',
                    'new_text': 'value = 2',
                    'expected_fingerprint': read['fingerprint'],
                },
            )
        self.assertEqual(target.read_text(), 'value = 1\nvalue = 1\n')

    def test_change_during_approval_is_not_overwritten(self):
        target = self.root / 'a.py'
        target.write_text('value = 1\n')

        def approve(*_):
            target.write_text('external = 3\n')
            return True

        self.tools.approve = approve
        read = self.tools.execute('read_file', {'path': 'a.py'})
        with self.assertRaisesRegex(ValueError, 'changed|stale'):
            self.tools.execute(
                'write_file',
                {
                    'path': 'a.py',
                    'content': 'value = 2\n',
                    'expected_fingerprint': read['fingerprint'],
                },
            )
        self.assertEqual(target.read_text(), 'external = 3\n')

    def test_escape_and_credential_paths_are_rejected(self):
        (self.root / '.ENV').write_text('sensitive')
        (self.root / '.npmrc').write_text('sensitive')
        (self.root / '.aws').mkdir()
        (self.root / '.aws/credentials').write_text('sensitive')
        for name in ('../outside.py', '.ENV', '.aws/credentials', '.npmrc'):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, 'escapes|excluded|credential'),
            ):
                self.tools.execute('read_file', {'path': name})

    def test_command_redacts_before_output_excerpt(self):
        secret = 'known-private-credential-' + 'v' * 40
        self.vault.protect(secret)
        result = self.tools.execute(
            'run_command',
            {
                'argv': [sys.executable, '-c', f'print("x" * 31990 + {secret!r})'],
            },
        )
        self.assertFalse('known-priv' in result['output'])
        self.assertEqual(result['exit_code'], 0)

    @unittest.skipIf(os.name == 'nt', 'POSIX executable permissions')
    def test_edit_keeps_executable_permission(self):
        target = self.root / 'run.sh'
        target.write_text('#!/bin/sh\necho one\n')
        target.chmod(0o755)
        read = self.tools.execute('read_file', {'path': 'run.sh'})
        self.tools.execute(
            'edit_file',
            {
                'path': 'run.sh',
                'old_text': 'echo one',
                'new_text': 'echo two',
                'expected_fingerprint': read['fingerprint'],
            },
        )
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
