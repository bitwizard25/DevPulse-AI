import unittest
from unittest.mock import patch

from devpulse.domain.hardware import HardwareProfile
from devpulse.infrastructure.hardware import fetch_models, probe_hardware


class HardwareInfraTests(unittest.TestCase):
    def test_live_hardware_probe(self):
        profile = probe_hardware()
        self.assertIsInstance(profile, HardwareProfile)
        self.assertGreater(profile.total_ram_bytes, 0)
        self.assertGreater(profile.available_ram_bytes, 0)
        # Should have detected OS name
        self.assertIn(profile.os_name.lower(), ["windows", "linux", "darwin"])

    def test_fetch_models_fallback_when_ollama_unreachable(self):
        models = fetch_models("http://127.0.0.1:9999")  # Unreachable port
        self.assertGreater(len(models), 0)
        self.assertIn("qwen2.5-coder:7b", [m.name for m in models])

    @patch("devpulse.infrastructure.hardware.http_json")
    def test_fetch_models_parses_ollama_tags(self, mock_http):
        mock_http.return_value = {
            "models": [
                {
                    "name": "qwen2.5-coder:7b",
                    "size": 4700000000,
                    "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M"},
                },
                {
                    "name": "custom-coder:3b",
                    "size": 2000000000,
                    "details": {"parameter_size": "3B", "quantization_level": "Q4_0"},
                },
            ]
        }
        models = fetch_models("http://127.0.0.1:11434")
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].name, "qwen2.5-coder:7b")
        self.assertEqual(models[0].params_billion, 7.0)
        self.assertEqual(models[1].name, "custom-coder:3b")
        self.assertEqual(models[1].params_billion, 3.0)


if __name__ == "__main__":
    unittest.main()
