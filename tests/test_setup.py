import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.hardware import HardwareProfile, ModelSpec
from devpulse.infrastructure.project import initialize
from devpulse.interfaces.cli import main
from devpulse.interfaces.setup import run_setup_wizard


class SetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def setup_with_choice(self, *choices):
        with (
            patch('builtins.input', side_effect=choices) as prompt,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_setup_wizard(self.root), 0)
        self.assertEqual(prompt.call_count, len(choices))
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
        with patch('devpulse.interfaces.setup.read_api_key', return_value='existing-fixture-key'):
            config = self.setup_with_choice('2', '1')
        self.assertEqual(config['providers'][0]['kind'], 'openai-compatible')
        self.assertEqual(rules.read_text(), 'Keep our project conventions.')

    @patch('devpulse.interfaces.setup.installed_model_names', return_value=[])
    def test_online_setup_prompts_for_hidden_key_and_saves_without_project_storage(self, _):
        key = 'fixture-google-key-never-print'
        output = io.StringIO()
        with (
            patch('devpulse.interfaces.setup.read_api_key', return_value=''),
            patch('devpulse.interfaces.setup.getpass.getpass', return_value=key) as prompt,
            patch('devpulse.interfaces.setup.save_api_key', return_value=True) as save,
            patch('builtins.input', side_effect=['2', '3']),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(run_setup_wizard(self.root), 0)
        prompt.assert_called_once()
        save.assert_called_once_with('GOOGLE_API_KEY', key)
        self.assertNotIn(key, output.getvalue())
        self.assertIn('saved', output.getvalue().lower())
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(key.encode(), path.read_bytes())

    @patch('devpulse.interfaces.setup.installed_model_names', return_value=[])
    def test_cancelled_api_key_entry_does_not_initialize_project(self, _):
        with (
            patch('devpulse.interfaces.setup.read_api_key', return_value=''),
            patch('devpulse.interfaces.setup.getpass.getpass', side_effect=KeyboardInterrupt),
            patch('devpulse.interfaces.setup.save_api_key') as save,
            patch('builtins.input', side_effect=['2', '2']),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_setup_wizard(self.root), 130)
        save.assert_not_called()
        self.assertFalse((self.root / '.devpulse/config.json').exists())

    def test_existing_online_project_requests_missing_key_on_interactive_start(self):
        initialize(self.root, provider='google', api_key_env='DEVPULSE_FIXTURE_API_KEY')
        key = 'fixture-private-google-key'
        with (
            patch.dict(
                os.environ,
                {
                    'DEVPULSE_HOME': str(self.root / 'state'),
                    'DEVPULSE_FIXTURE_API_KEY': '',
                },
            ),
            patch('devpulse.interfaces.setup.getpass.getpass', return_value=key) as prompt,
            patch(
                'devpulse.interfaces.setup.save_api_key',
                side_effect=lambda name, value: os.environ.__setitem__(name, value) or True,
            ) as save,
            patch('sys.stdin.isatty', return_value=True),
            patch('builtins.input', return_value='/quit'),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(['--project', str(self.root)]), 0)
        prompt.assert_called_once()
        save.assert_called_once_with('DEVPULSE_FIXTURE_API_KEY', key)
        self.assertNotIn(key, output.getvalue())
