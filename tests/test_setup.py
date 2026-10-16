import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.hardware import HardwareProfile
from devpulse.interfaces.setup import run_setup_wizard


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='devpulse-setup-test-')
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch('devpulse.interfaces.setup.probe_hardware')
    @patch('builtins.input')
    def test_setup_wizard_offline_mode(self, mock_input, mock_probe):
        mock_probe.return_value = HardwareProfile(
            total_ram_bytes=8 * 1024**3,
            available_ram_bytes=4 * 1024**3,
            vram_bytes=4 * 1024**3,
            gpu_name='NVIDIA GeForce RTX 2050',
            os_name='Windows',
        )
        # Choose option 1 (offline), then Y (integrate)
        mock_input.side_effect = ['1', 'y']

        ret = run_setup_wizard(self.root)
        self.assertEqual(ret, 0)
        self.assertTrue((self.root / '.devpulse/config.json').is_file())
        self.assertTrue((self.root / '.devpulse/RULES.md').is_file())
        self.assertTrue((self.root / '.agents/mcp_config.json').is_file())

    @patch('devpulse.interfaces.setup.probe_hardware')
    @patch('builtins.input')
    def test_setup_wizard_ollama_mode_picks_model(self, mock_input, mock_probe):
        mock_probe.return_value = HardwareProfile(
            total_ram_bytes=8 * 1024**3,
            available_ram_bytes=4 * 1024**3,
            vram_bytes=4 * 1024**3,
            gpu_name='NVIDIA GeForce RTX 2050',
            os_name='Windows',
        )
        # Choose option 2 (Ollama), choose model 1, then Y (integrate)
        mock_input.side_effect = ['2', '1', 'y']

        ret = run_setup_wizard(self.root)
        self.assertEqual(ret, 0)
        cfg_data = json.loads((self.root / '.devpulse/config.json').read_text('utf-8'))
        self.assertEqual(len(cfg_data['providers']), 1)
        self.assertEqual(cfg_data['providers'][0]['kind'], 'ollama')


if __name__ == '__main__':
    unittest.main()
