import tempfile
import unittest
from pathlib import Path

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_tools import ProjectTools


class AgentGuidanceTests(unittest.TestCase):
    def test_root_and_scoped_instructions_are_available(self):
        from devpulse.infrastructure.agent_guidance import read_agent_guidance

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / '.devpulse').mkdir()
            (root / 'src').mkdir()
            (root / 'AGENTS.md').write_text('Keep public API stable.')
            (root / 'CLAUDE.md').write_text('Use the existing formatter.')
            (root / '.devpulse/RULES.md').write_text('Prefer focused fixes.')
            (root / 'src/AGENTS.md').write_text('Use async database calls. password="do-not-send"')
            (root / 'src/a.py').write_text('print(1)')
            vault = Vault()
            guidance = read_agent_guidance(root, vault)
            self.assertIn('Keep public API stable.', guidance['text'])
            self.assertIn('Use the existing formatter.', guidance['text'])
            self.assertIn('Prefer focused fixes.', guidance['text'])
            result = ProjectTools(root, lambda *_: True, vault).execute(
                'read_file', {'path': 'src/a.py'}
            )
            self.assertIn('Use async database calls.', result['instructions'][0]['text'])
            self.assertNotIn('do-not-send', str(result))
