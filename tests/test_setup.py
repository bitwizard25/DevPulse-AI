import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.hardware import HardwareProfile, ModelSpec
from devpulse.infrastructure.project import initialize
from devpulse.interfaces.setup import run_setup_wizard


class SetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def setup_with_choice(self, choice):
        with (
            patch('builtins.input', return_value=choice) as prompt,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_setup_wizard(self.root), 0)
        self.assertEqual(prompt.call_count, 1)
        return json.loads((self.root / '.devpulse/config.json').read_text('utf-8'))

    @patch('devpulse.interfaces.setup.installed_model_names', return_value=[])
    def test_single_choice_offline_setup_creates_rules_without_integrations(self, _):
        config = self.setup_with_choice('3')
        self.assertEqual(config['providers'], [])
        self.assertTrue((self.root / '.devpulse/RULES.md').is_file())
        self.assertFalse((self.root / '.agents/mcp_config.json').exists())

    @patch('devpulse.interfaces.setup.installed_model_names', return_value=['qwen2.5-coder:1.5b'])
    @patch(
        'devpulse.interfaces.setup.fetch_models',
        return_value=[ModelSpec('qwen2.5-coder:1.5b', 1.5)],
    )
    @patch(
        'devpulse.interfaces.setup.probe_hardware',
        return_value=HardwareProfile(
            8 * 1024**3, 4 * 1024**3, 4 * 1024**3, 'Fixture GPU', 'Windows'
        ),
    )
    def test_local_setup_uses_installed_model_without_another_menu(self, *_):
        config = self.setup_with_choice('1')
        self.assertEqual(config['providers'][0]['kind'], 'ollama')
        self.assertEqual(config['providers'][0]['model'], 'qwen2.5-coder:1.5b')

    @patch('devpulse.interfaces.setup.installed_model_names', return_value=[])
    def test_cloud_setup_upgrades_offline_config_and_preserves_rules(self, _):
        initialize(self.root, provider='offline')
        rules = self.root / '.devpulse/RULES.md'
        rules.write_text('Keep our project conventions.')
        config = self.setup_with_choice('2')
        self.assertEqual(config['providers'][0]['kind'], 'openai-compatible')
        self.assertEqual(rules.read_text(), 'Keep our project conventions.')
