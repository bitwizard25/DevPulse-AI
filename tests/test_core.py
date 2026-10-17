import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.context import assemble
from devpulse.infrastructure.state import State


class PrivacyTests(unittest.TestCase):
    def test_registered_credential_is_counted_only_when_it_occurs(self):
        vault = Vault()
        vault.protect('runtime-private-key')
        self.assertEqual(vault.scrub('print(1)'), 'print(1)')
        self.assertEqual(vault.count, 0)
        self.assertNotIn('runtime-private-key', vault.scrub('custom = "runtime-private-key"'))
        self.assertEqual(vault.count, 1)

    def test_secrets_are_request_local_and_repeated_values_stay_consistent(self):
        secret = 'sk-' + 'A1b2C3d4' * 5
        vault = Vault()
        value = vault.scrub(f'api_key="{secret}"\nagain={secret}')
        self.assertNotIn(secret, value)
        self.assertEqual(value.count('__SECRET_001__'), 2)
        self.assertEqual(Vault().scrub('password="hunter22"'), 'password="__SECRET_001__"')

    def test_private_keys_and_bearer_tokens_are_removed(self):
        text = '-----BEGIN PRIVATE KEY-----\nabcdef\n-----END PRIVATE KEY-----\nAuthorization: Bearer abc.def.ghi'
        result = Vault().scrub(text)
        self.assertNotIn('abcdef', result)
        self.assertNotIn('abc.def.ghi', result)


class StateTests(unittest.TestCase):
    def test_concurrent_first_start_uses_one_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            with concurrent.futures.ThreadPoolExecutor(12) as pool:
                identities = list(
                    pool.map(lambda _: State(Path(tmp)).identity('source'), range(24))
                )
            self.assertEqual(len(set(identities)), 1)

    def test_cache_expiry_and_restart_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            state.cache_put('key', {'summary': 'safe'}, ttl=-1)
            self.assertIsNone(state.cache_get('key'))
            session = state.start('project', 'digest', owner_pid=0)
            state.recover()
            self.assertEqual(state.sessions()[0]['status'], 'interrupted')
            state.finish(session, {'summary': 'done'})
            self.assertEqual(state.sessions()[0]['status'], 'completed')

    def test_recovery_keeps_live_direct_sessions_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp))
            state.start('project', 'digest')
            state.recover()
            self.assertEqual(state.sessions()[0]['status'], 'running')

    def test_key_is_durable_and_private_to_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                State(Path(tmp)).identity('source'), State(Path(tmp)).identity('source')
            )
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertNotEqual(
                State(Path(a)).identity('source'), State(Path(b)).identity('source')
            )


class ContextTests(unittest.TestCase):
    def test_cutoff_cannot_expose_partial_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.devpulse').mkdir()
            (root / '.devpulse/RULES.md').write_text(
                '-----BEGIN PRIVATE KEY-----\n' + 'TOPSECRET' * 1000 + '\n-----END PRIVATE KEY-----'
            )
            result = assemble(root, Vault(), budget=1000)
            self.assertNotIn('TOPSECRET', result['text'])

    def test_budget_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.devpulse').mkdir()
            (root / '.devpulse/RULES.md').write_text('password="private-value"\n' + 'a' * 5000)
            result = assemble(root, Vault(), budget=1000)
            self.assertLessEqual(len(result['text'].encode()), 1000)
            self.assertNotIn('private-value', result['text'])
            self.assertTrue(result['truncated'])

    def test_memory_changes_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.devpulse').mkdir()
            first = assemble(root, Vault())
            (root / '.devpulse/MEMORY.md').write_text('Use parameterized SQL.')
            second = assemble(root, Vault())
            self.assertNotEqual(first['text'], second['text'])


if __name__ == '__main__':
    unittest.main()
