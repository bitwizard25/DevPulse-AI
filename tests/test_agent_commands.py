import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_tools import ProjectTools


class AgentCommandTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.tools = ProjectTools(self.root, lambda *_: True, Vault())

    def run_code(self, code, **options):
        return self.tools.execute('run_command', {'argv': [sys.executable, '-c', code], **options})

    def test_denied_command_cannot_create_a_file(self):
        self.tools.approve = lambda *_: False
        result = self.run_code('from pathlib import Path; Path("effect").touch()')
        self.assertEqual(result['status'], 'denied')
        self.assertFalse((self.root / 'effect').exists())

    def test_provider_environment_keys_are_not_inherited(self):
        with patch.dict(os.environ, {'DEVPULSE_TEST_PROVIDER_KEY': 'private-fixture'}):
            result = self.run_code(
                'import os; print(os.environ.get("DEVPULSE_TEST_PROVIDER_KEY", "absent"))'
            )
        self.assertEqual(result['output'].strip(), 'absent')

    def test_output_limit_is_explicit_and_discards_partial_credentials(self):
        result = self.run_code('print("x" * (2 * 1024 * 1024))')
        self.assertTrue(result['output_limited'])
        self.assertTrue(result['truncated'])
        self.assertIn('discarded', result['output'])

    def test_timeout_stops_command_and_its_running_child(self):
        child = (
            'import time; from pathlib import Path; time.sleep(2); Path("orphan-effect").touch()'
        )
        parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(10)'
        result = self.run_code(parent, timeout=1)
        self.assertTrue(result['timed_out'])
        subprocess.run([sys.executable, '-c', 'import time; time.sleep(1.4)'], check=True)
        self.assertFalse(
            (self.root / 'orphan-effect').exists(), 'Timed-out command left a live child process.'
        )

    def test_unknown_tool_fields_cannot_cause_file_effects(self):
        with self.assertRaisesRegex(ValueError, 'unknown fields'):
            self.tools.execute(
                'write_file', {'path': 'effect.py', 'content': 'print(1)', 'force': True}
            )
        self.assertFalse((self.root / 'effect.py').exists())
