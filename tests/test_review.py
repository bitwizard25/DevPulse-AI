import concurrent.futures
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from devpulse.bootstrap import make_engine as Engine
from devpulse.domain.errors import ProviderError
from devpulse.domain.models import Config, ProviderConfig
from devpulse.domain.review import validate_result
from devpulse.infrastructure.config import load_config
from devpulse.infrastructure.source import collect
from devpulse.infrastructure.state import State


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.state = State(self.root / 'state')

    def test_offline_checks_syntax_and_never_persists_source(self):
        path = self.project / 'bad.py'
        path.write_text('password="my-private-password"\ndef broken(:\n')
        result = Engine(self.state).review(self.project, Config(), mode='offline', file='bad.py')
        self.assertTrue(any(f['rule'] == 'python-syntax' for f in result['findings']))
        self.assertTrue(any(f['rule'] == 'secret-detected' for f in result['findings']))
        self.assertNotIn('my-private-password', json.dumps(result))
        self.assertNotIn(b'my-private-password', self.state.path.read_bytes())

    def test_cache_is_invalidated_by_memory_and_original_secret_changes(self):
        calls = []

        def provider(config, prompt):
            calls.append(prompt)
            return {'summary': 'Reviewed', 'findings': []}

        config = Config(providers=[ProviderConfig(name='local', model='test')])
        path = self.project / 'a.py'
        path.write_text('password="first-secret"')
        engine = Engine(self.state, transport=provider)
        one = engine.review(self.project, config, file='a.py')
        two = engine.review(self.project, config, file='a.py')
        self.assertEqual(two['cache'], 'L1')
        path.write_text('password="second-secret"')
        engine.review(self.project, config, file='a.py')
        (self.project / '.devpulse').mkdir()
        (self.project / '.devpulse/MEMORY.md').write_text('New convention')
        engine.review(self.project, config, file='a.py')
        self.assertEqual(len(calls), 3)
        self.assertNotIn('first-secret', calls[0])
        self.assertNotEqual(one['session'], two['session'])

    def test_parallel_identical_reviews_coalesce(self):
        calls = []

        def provider(config, prompt):
            calls.append(1)
            time.sleep(0.05)
            return {'summary': 'Reviewed', 'findings': []}

        (self.project / 'a.py').write_text('print(1)')
        config = Config(providers=[ProviderConfig(name='local', model='test')])
        engine = Engine(self.state, transport=provider)
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(
                pool.map(lambda _: engine.review(self.project, config, file='a.py'), range(4))
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 4)

    def test_provider_failover_and_circuit_breaker(self):
        calls = []

        def provider(config, prompt):
            calls.append(config.name)
            if config.name == 'broken':
                raise ProviderError('Unavailable', retryable=True)
            return {'summary': 'Reviewed', 'findings': []}

        (self.project / 'a.py').write_text('print(1)')
        config = Config(
            providers=[
                ProviderConfig(name='broken', model='test'),
                ProviderConfig(name='local', model='test'),
            ]
        )
        engine = Engine(self.state, transport=provider)
        for _ in range(4):
            result = engine.review(self.project, config, file='a.py', no_cache=True)
        self.assertEqual(result['provider'], 'local')
        self.assertEqual(calls.count('broken'), 3)

    def test_untrusted_provider_schema_is_rejected(self):
        for result in [
            {'summary': 'fine'},
            {'summary': 'x', 'findings': [{'severity': 'urgent'}]},
            {'summary': 'x', 'findings': [], 'command': 'rm -rf .'},
        ]:
            with self.assertRaises(ProviderError):
                validate_result(result)

    def test_secret_output_with_quotes_remains_valid_json(self):
        (self.project / 'a.py').write_text('print(1)')

        def provider(config, prompt):
            return {'summary': 'Found password="quoted-password"', 'findings': []}

        result = Engine(self.state, transport=provider).review(
            self.project, Config(providers=[ProviderConfig()]), file='a.py'
        )
        self.assertNotIn('quoted-password', result['summary'])

    def test_context_secret_change_invalidates_cache(self):
        calls = []

        def provider(config, prompt):
            calls.append(prompt)
            return {'summary': 'Reviewed', 'findings': []}

        (self.project / 'a.py').write_text('print(1)')
        base = self.project / '.devpulse'
        base.mkdir()
        memory = base / 'MEMORY.md'
        memory.write_text('password="one-secret"')
        engine = Engine(self.state, transport=provider)
        config = Config(providers=[ProviderConfig()])
        engine.review(self.project, config, file='a.py')
        memory.write_text('password="two-secret"')
        engine.review(self.project, config, file='a.py')
        self.assertEqual(len(calls), 2)

    def test_all_provider_failure_explains_missing_key(self):
        (self.project / 'a.py').write_text('print(1)')
        config = Config(
            providers=[
                ProviderConfig(
                    name='cloud',
                    kind='openai-compatible',
                    model='test',
                    base_url='https://example.com/v1',
                    api_key_env='DEVPULSE_NONEXISTENT_TEST_KEY',
                )
            ]
        )
        with self.assertRaisesRegex(ProviderError, 'DEVPULSE_NONEXISTENT_TEST_KEY'):
            Engine(self.state).review(self.project, config, file='a.py')

    def test_path_escape_is_rejected(self):
        outside = self.root / 'outside.py'
        outside.write_text('secret')
        with self.assertRaises(ValueError):
            collect(self.project, file='../outside.py')

    def test_many_local_findings_are_bounded_and_omission_is_explicit(self):
        (self.project / 'many.py').write_text('eval(x)\n' * 10000)
        result = Engine(self.state).review(self.project, Config(), mode='offline', file='many.py')
        self.assertLess(len(json.dumps(result).encode()), 1024 * 1024)
        self.assertTrue(any(f['rule'] == 'findings-truncated' for f in result['findings']))

    def test_config_rejects_wrong_types_as_value_errors(self):
        base = self.project / '.devpulse'
        base.mkdir()
        for value in [
            {'providers': [{'base_url': 123}]},
            {'providers': None},
            {'providers': ['invalid']},
        ]:
            (base / 'config.json').write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_config(self.project)

    def test_clean_code_with_runtime_key_does_not_report_secret(self):
        (self.project / 'a.py').write_text('print(1)')
        os.environ['DEVPULSE_TEST_KEY'] = 'private-runtime-key'
        self.addCleanup(os.environ.pop, 'DEVPULSE_TEST_KEY', None)
        config = Config(providers=[ProviderConfig(api_key_env='DEVPULSE_TEST_KEY')])

        def provider(config, prompt):
            return {'summary': 'Reviewed', 'findings': []}

        result = Engine(self.state, transport=provider).review(self.project, config, file='a.py')
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['redacted_values'], 0)

    def test_staged_source_uses_index_not_worktree(self):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        path = self.project / 'a.py'
        path.write_text('print("staged")\n')
        subprocess.run(['git', '-C', str(self.project), 'add', '--', 'a.py'], check=True)
        path.write_text('print("worktree")\n')
        source = collect(self.project)
        self.assertIn('staged', source['text'])
        self.assertNotIn('worktree', source['files'][0]['content'])

    def test_diff_subdirectory_cannot_silently_skip_repository_rules(self):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        child = self.project / 'src'
        child.mkdir()
        with self.assertRaisesRegex(ValueError, 'repository root'):
            collect(child)


if __name__ == '__main__':
    unittest.main()
