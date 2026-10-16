import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from devpulse.domain.hardware import HardwareProfile, ModelSpec
from devpulse.interfaces.commands import models


class ModelsCliTests(unittest.TestCase):
    def setUp(self):
        self.profile = HardwareProfile(
            total_ram_bytes=8 * 1024**3,
            available_ram_bytes=4 * 1024**3,
            vram_bytes=4 * 1024**3,
            gpu_name='NVIDIA GeForce RTX 2050',
            os_name='Windows',
        )

    @patch('devpulse.interfaces.commands.models.probe_hardware')
    @patch('devpulse.interfaces.commands.models.fetch_models')
    def test_filter_single_model(self, mock_fetch, mock_probe):
        mock_probe.return_value = self.profile
        mock_fetch.return_value = [
            ModelSpec('qwen2.5-coder:1.5b', 1.5, 'Q4_K_M', coding_iq=68),
            ModelSpec('deepseek-coder:6.7b', 6.7, 'Q4_K_M', coding_iq=82),
        ]

        args = MagicMock()
        args.model = 'deepseek-coder:6.7b'
        args.select = False
        args.base_url = None
        args.json = True

        captured = []
        with patch(
            'devpulse.interfaces.commands.models.emit',
            side_effect=lambda val, **kw: captured.append(val),
        ):
            ret = models.handle(args, Path('.'))
            self.assertEqual(ret, 0)
            self.assertEqual(len(captured), 1)
            data = captured[0]
            self.assertEqual(len(data['ratings']), 1)
            self.assertEqual(data['ratings'][0]['model'], 'deepseek-coder:6.7b')

    @patch('devpulse.interfaces.commands.models.probe_hardware')
    @patch('devpulse.interfaces.commands.models.fetch_models')
    def test_inspect_unseen_custom_model_by_name(self, mock_fetch, mock_probe):
        mock_probe.return_value = self.profile
        mock_fetch.return_value = []

        args = MagicMock()
        args.model = 'custom-coder:14b'
        args.select = False
        args.base_url = None
        args.json = True

        captured = []
        with patch(
            'devpulse.interfaces.commands.models.emit',
            side_effect=lambda val, **kw: captured.append(val),
        ):
            ret = models.handle(args, Path('.'))
            self.assertEqual(ret, 0)
            data = captured[0]
            self.assertEqual(len(data['ratings']), 1)
            self.assertEqual(data['ratings'][0]['model'], 'custom-coder:14b')
            self.assertEqual(data['ratings'][0]['params_b'], 14.0)


if __name__ == '__main__':
    unittest.main()
