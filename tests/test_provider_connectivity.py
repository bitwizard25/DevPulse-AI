import socket
import unittest
from unittest.mock import patch
from urllib.error import URLError

from devpulse.domain.errors import ProviderError
from devpulse.domain.models import ProviderConfig
from devpulse.infrastructure.providers import complete, complete_agent


class ProviderConnectivityTests(unittest.TestCase):
    @patch('devpulse.infrastructure.providers.request.build_opener')
    def test_ollama_connection_failure_identifies_service_and_recovery(self, opener):
        opener.return_value.open.side_effect = URLError(
            ConnectionRefusedError('sensitive-network-detail')
        )
        for transport, value in ((complete, 'review'), (complete_agent, [])):
            with self.subTest(transport=transport.__name__):
                with self.assertRaises(ProviderError) as caught:
                    transport(ProviderConfig(), value)
                text = str(caught.exception)
                self.assertIn('Cannot connect to Ollama', text)
                self.assertIn('127.0.0.1:11434', text)
                self.assertIn('ollama serve', text)
                self.assertNotIn('timed out', text)
                self.assertNotIn('sensitive-network-detail', text)
                self.assertTrue(caught.exception.retryable)

    @patch('devpulse.infrastructure.providers.request.build_opener')
    def test_ollama_timeout_is_distinct_from_an_absent_server(self, opener):
        opener.return_value.open.side_effect = URLError(socket.timeout('sensitive-detail'))
        with self.assertRaises(ProviderError) as caught:
            complete_agent(ProviderConfig(timeout=17), [])
        text = str(caught.exception)
        self.assertIn('Ollama', text)
        self.assertIn('17 seconds', text)
        self.assertIn('timeout', text)
        self.assertNotIn('Cannot connect', text)
        self.assertNotIn('sensitive-detail', text)
