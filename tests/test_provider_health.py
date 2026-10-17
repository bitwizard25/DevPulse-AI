import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.errors import ProviderError
from devpulse.domain.models import ProviderConfig
from devpulse.infrastructure.provider_health import probe_provider
from devpulse.interfaces.cli import main


class ProviderHealthTests(unittest.TestCase):
    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_available_service_checks_selected_model_without_inference(self, http):
        http.return_value = {'models': [{'name': 'phi3.5:3.8b'}]}
        result = probe_provider(ProviderConfig(model='phi3.5:3.8b'))
        self.assertEqual(result['status'], 'ready')
        http.assert_called_once_with('http://127.0.0.1:11434/api/tags', timeout=5, service='Ollama')

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_running_server_with_missing_model_is_not_reported_ready(self, http):
        http.return_value = {'models': [{'name': 'another:latest'}]}
        result = probe_provider(ProviderConfig(model='phi3.5:3.8b'))
        self.assertEqual(result['status'], 'model_missing')
        self.assertIn('ollama pull phi3.5:3.8b', result['message'])

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_implicit_latest_tag_matches_installed_model(self, http):
        http.return_value = {'models': [{'name': 'phi3.5:latest'}]}
        self.assertEqual(probe_provider(ProviderConfig(model='phi3.5'))['status'], 'ready')

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_unreachable_service_is_reported_without_crashing_doctor(self, http):
        http.side_effect = ProviderError('Cannot connect to Ollama. Start Ollama.')
        result = probe_provider(ProviderConfig())
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('Start Ollama', result['message'])

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_cloud_provider_probe_does_not_send_a_request_or_credentials(self, http):
        config = ProviderConfig(
            kind='openai-compatible', base_url='https://example.com/v1', api_key_env='KEY'
        )
        self.assertEqual(probe_provider(config)['status'], 'not_checked')
        http.assert_not_called()

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_malformed_ollama_model_list_is_not_ready(self, http):
        http.return_value = {'models': 'unexpected'}
        self.assertEqual(probe_provider(ProviderConfig())['status'], 'invalid_response')

    @patch('devpulse.infrastructure.provider_health.http_json')
    def test_doctor_reports_unavailable_service_in_its_output(self, http):
        http.side_effect = ProviderError('Cannot connect to Ollama. Start Ollama.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.devpulse').mkdir()
            (root / '.devpulse/config.json').write_text(
                json.dumps({'providers': [{'kind': 'ollama', 'model': 'phi3.5:3.8b'}]})
            )
            output = io.StringIO()
            with (
                patch.dict(os.environ, {'DEVPULSE_HOME': str(root / 'state')}),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(['--project', str(root), 'doctor']), 0)
            provider = json.loads(output.getvalue())['providers'][0]
            self.assertEqual(provider['health']['status'], 'unavailable')
            self.assertIn('Start Ollama', provider['health']['message'])
