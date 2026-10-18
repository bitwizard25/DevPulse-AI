import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from devpulse.domain.models import Config, ProviderConfig
from devpulse.infrastructure.config import credential_values, protected_vault
from devpulse.infrastructure.credentials import read_api_key, save_api_key
from devpulse.infrastructure.providers import complete_agent

NAME = 'DEVPULSE_FIXTURE_API_KEY'
KEY = 'fixture-private-key-not-a-real-credential'


class CredentialTests(unittest.TestCase):
    def registry(self):
        registry = MagicMock()
        registry.QueryValueEx.return_value = (KEY, registry.REG_SZ)
        return registry

    def test_save_activates_key_and_writes_only_windows_user_environment(self):
        registry = self.registry()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('devpulse.infrastructure.credentials.IS_WINDOWS', True),
            patch.dict(sys.modules, {'winreg': registry}),
        ):
            self.assertTrue(save_api_key(NAME, KEY))
            self.assertEqual(os.environ[NAME], KEY)
        registry.CreateKeyEx.assert_called_once_with(
            registry.HKEY_CURRENT_USER, 'Environment', 0, registry.KEY_SET_VALUE
        )
        registry.SetValueEx.assert_called_once_with(
            registry.CreateKeyEx.return_value.__enter__.return_value,
            NAME,
            0,
            registry.REG_SZ,
            KEY,
        )

    def test_saved_user_key_authenticates_and_is_registered_for_redaction(self):
        registry = self.registry()
        config = Config(
            providers=[
                ProviderConfig(
                    name='fixture',
                    kind='openai-compatible',
                    api_key_env=NAME,
                    model='fixture',
                    base_url='https://example.invalid/v1',
                )
            ]
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('devpulse.infrastructure.credentials.IS_WINDOWS', True),
            patch.dict(sys.modules, {'winreg': registry}),
            patch('devpulse.infrastructure.providers.http_json') as http,
        ):
            http.return_value = {'choices': [{'message': {'content': 'fixture-result'}}]}
            self.assertEqual(credential_values(config), [KEY])
            self.assertNotIn(KEY, protected_vault(config).scrub(KEY))
            self.assertEqual(complete_agent(config.providers[0], []), 'fixture-result')
            self.assertEqual(http.call_args.kwargs['headers']['Authorization'], 'Bearer ' + KEY)

    def test_process_environment_overrides_saved_user_key_including_explicit_empty(self):
        registry = self.registry()
        with (
            patch.dict(os.environ, {NAME: ''}),
            patch('devpulse.infrastructure.credentials.IS_WINDOWS', True),
            patch.dict(sys.modules, {'winreg': registry}),
        ):
            self.assertEqual(read_api_key(NAME), '')
        registry.OpenKey.assert_not_called()

    def test_invalid_key_does_not_change_environment_or_registry(self):
        registry = self.registry()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('devpulse.infrastructure.credentials.IS_WINDOWS', True),
            patch.dict(sys.modules, {'winreg': registry}),
        ):
            for value in ('', 'two tokens', 'secret\r\nInjected: header'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    save_api_key(NAME, value)
            self.assertNotIn(NAME, os.environ)
        registry.CreateKeyEx.assert_not_called()

    def test_non_windows_key_is_available_in_current_session(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch('devpulse.infrastructure.credentials.IS_WINDOWS', False),
        ):
            self.assertFalse(save_api_key(NAME, KEY))
            self.assertEqual(read_api_key(NAME), KEY)


if __name__ == '__main__':
    unittest.main()
