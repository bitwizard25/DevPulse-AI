import sys
import tempfile
import unittest
from pathlib import Path

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_tools import ProjectTools


class AgentCommandRecoveryTests(unittest.TestCase):
    def test_missing_executable_returns_available_interpreter_without_rewriting_command(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = ProjectTools(Path(directory), lambda *_: True, Vault())
            result = tools.execute('run_command', {'argv': ['devpulse-definitely-missing-runner']})
            self.assertEqual(result['status'], 'not_found')
            self.assertEqual(result['python_executable'], sys.executable)
            self.assertIn('project', result['hint'])
            self.assertNotIn('exit_code', result)


if __name__ == '__main__':
    unittest.main()
