import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from devpulse.domain.models import Config, ProviderConfig
from devpulse.infrastructure.state import State
from devpulse.interfaces.gateway import Gateway, gateway_request


class JobInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'state'
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / '.devpulse').mkdir()
        (self.project / '.devpulse/config.json').write_text(
            json.dumps(Config(providers=[ProviderConfig()]).as_dict())
        )
        (self.project / 'a.py').write_text('print(1)')

    def test_authenticated_job_submission_inspection_and_cancel(self):
        entered, release = threading.Event(), threading.Event()

        def provider(config, prompt):
            entered.set()
            release.wait(5)
            return {'summary': 'Reviewed', 'findings': []}

        with Gateway(State(self.home), transport=provider) as gateway:
            thread = threading.Thread(target=gateway.serve, daemon=True)
            thread.start()
            try:
                response = gateway_request(
                    self.home, '/jobs', {'project': str(self.project), 'file': 'a.py'}
                )
                job_id = response['id']
                self.assertTrue(entered.wait(5))
                state = gateway_request(self.home, '/jobs/' + job_id)
                self.assertEqual(state['status'], 'running')
                self.assertNotIn('snapshot', state)
                gateway_request(self.home, '/jobs/' + job_id + '/cancel', {})
                release.set()
                for _ in range(50):
                    state = gateway_request(self.home, '/jobs/' + job_id)
                    if state['status'] == 'cancelled':
                        break
                    time.sleep(0.05)
                self.assertEqual(state['status'], 'cancelled')
                self.assertIsNone(state['result'])
            finally:
                release.set()
                gateway.stop()
                thread.join(5)

    def test_cli_memory_search_and_context_preview(self):
        (self.project / '.devpulse/MEMORY.md').write_text(
            'Use SQL parameters for database queries.'
        )
        env = {**os.environ, 'DEVPULSE_HOME': str(self.home)}

        def cli(*args):
            return subprocess.run(
                [sys.executable, '-m', 'devpulse', '--project', str(self.project), *args],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )

        search = cli('memory', 'search', 'SQL database', '--json')
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertEqual(json.loads(search.stdout)[0]['path'], '.devpulse/MEMORY.md')
        context = cli('context', '--file', 'a.py', '--json')
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertIn('estimated_input_tokens', json.loads(context.stdout)['context'])

    def test_blocking_reviews_leave_capacity_for_control_requests(self):
        release = threading.Event()

        def provider(config, prompt):
            release.wait(10)
            return {'summary': 'Reviewed', 'findings': []}

        with Gateway(State(self.home), transport=provider) as gateway:
            thread = threading.Thread(target=gateway.serve, daemon=True)
            thread.start()
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                futures = [
                    pool.submit(
                        gateway_request,
                        self.home,
                        '/review',
                        {'project': str(self.project), 'file': 'a.py'},
                    )
                    for _ in range(4)
                ]
                try:
                    for _ in range(100):
                        health = gateway_request(self.home, '/health')
                        if health.get('waiting_reviews') == 4:
                            break
                        time.sleep(0.02)
                    self.assertEqual(health.get('waiting_reviews'), 4)
                    from devpulse.domain.errors import ProviderError

                    with self.assertRaisesRegex(ProviderError, '429'):
                        gateway_request(
                            self.home, '/review', {'project': str(self.project), 'file': 'a.py'}
                        )
                    self.assertEqual(gateway_request(self.home, '/health')['status'], 'ready')
                    for _ in range(100):
                        jobs = gateway_request(self.home, '/jobs')['jobs']
                        if jobs:
                            break
                        time.sleep(0.02)
                    self.assertTrue(jobs)
                    gateway_request(self.home, '/jobs/' + jobs[0]['id'] + '/cancel', {})
                finally:
                    release.set()
                    for future in futures:
                        try:
                            future.result(timeout=10)
                        except Exception:
                            pass
                    gateway.stop()
                    thread.join(5)

    def test_memory_and_query_preview_protect_configured_runtime_keys(self):
        config = Config(
            providers=[
                ProviderConfig(
                    kind='openai-compatible',
                    model='test',
                    base_url='https://example.com/v1',
                    api_key_env='DEVPULSE_PRIVACY_KEY',
                )
            ]
        )
        (self.project / '.devpulse/config.json').write_text(json.dumps(config.as_dict()))
        (self.project / '.devpulse/MEMORY.md').write_text('SQL credentialvalue database')
        env = {
            **os.environ,
            'DEVPULSE_HOME': str(self.home),
            'DEVPULSE_PRIVACY_KEY': 'credentialvalue',
        }
        for command in [
            ('memory', 'search', 'SQL', '--json'),
            ('memory', 'reindex'),
            ('context', '--query', 'SQL', '--json'),
        ]:
            result = subprocess.run(
                [sys.executable, '-m', 'devpulse', '--project', str(self.project), *command],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('credentialvalue', result.stdout)
            with State(self.home).connect() as db:
                self.assertFalse(
                    any(
                        'credentialvalue' in row[0] for row in db.execute('SELECT text FROM chunks')
                    )
                )

    def test_offline_direct_rejects_detach_instead_of_ignoring_it(self):
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'devpulse',
                '--project',
                str(self.project),
                'review',
                '--offline',
                '--detach',
                '--file',
                'a.py',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('detach', result.stderr.lower())

    def test_active_attempt_heartbeats_and_manual_retry_inspects_results(self):
        from devpulse.domain.errors import ProviderError

        release, entered = threading.Event(), threading.Event()
        should_fail = [True]

        def provider(config, prompt):
            entered.set()
            release.wait(10)
            if should_fail[0]:
                raise ProviderError('invalid response', retryable=False)
            return {'summary': 'Manual retry succeeded', 'findings': []}

        with Gateway(State(self.home), transport=provider) as gateway:
            thread = threading.Thread(target=gateway.serve, daemon=True)
            thread.start()
            try:
                job = gateway_request(
                    self.home, '/jobs', {'project': str(self.project), 'file': 'a.py'}
                )
                self.assertTrue(entered.wait(5))
                first = gateway_request(self.home, '/jobs/' + job['id'])['heartbeat']
                for _ in range(130):
                    active = gateway_request(self.home, '/jobs/' + job['id'])
                    if active['heartbeat'] > first:
                        break
                    time.sleep(0.05)
                self.assertGreater(active['heartbeat'], first)
                release.set()
                for _ in range(100):
                    failed = gateway_request(self.home, '/jobs/' + job['id'])
                    if failed['status'] == 'failed':
                        break
                    time.sleep(0.02)
                self.assertEqual(failed['attempts'], 1)
                should_fail[0] = False
                retry = gateway_request(self.home, '/jobs/' + job['id'] + '/retry', {})
                self.assertNotEqual(retry['id'], job['id'])
                for _ in range(100):
                    completed = gateway_request(self.home, '/jobs/' + retry['id'])
                    if completed['status'] == 'succeeded':
                        break
                    time.sleep(0.02)
                self.assertEqual(completed['result']['summary'], 'Manual retry succeeded')
            finally:
                release.set()
                gateway.stop()
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
