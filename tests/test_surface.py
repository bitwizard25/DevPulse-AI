import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from devpulse.domain.errors import ProviderError
from devpulse.domain.models import ProviderConfig
from devpulse.infrastructure.providers import complete
from devpulse.infrastructure.state import State
from devpulse.interfaces.gateway import Gateway, gateway_request


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'state'
        self.project = self.root / 'project'
        self.project.mkdir()

    def cli(self, *args):
        env = {**os.environ, 'DEVPULSE_HOME': str(self.home), 'PYTHONUTF8': '1'}
        return subprocess.run(
            [sys.executable, '-m', 'devpulse', '--project', str(self.project), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

    def test_cli_init_memory_review_and_history(self):
        self.assertEqual(self.cli('init', '--provider', 'offline').returncode, 0)
        self.assertEqual(
            self.cli('memory', 'add', 'Use SQL parameters. password="do-not-store"').returncode, 0
        )
        self.assertNotIn('do-not-store', (self.project / '.devpulse/MEMORY.md').read_text())
        (self.project / 'bad.py').write_text('def bad(:\n')
        result = self.cli('review', '--offline', '--direct', '--file', 'bad.py', '--json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['findings'][0]['rule'], 'python-syntax')
        sessions = self.cli('sessions', '--json')
        self.assertEqual(json.loads(sessions.stdout)[0]['status'], 'completed')

    def test_cli_error_is_actionable_without_traceback(self):
        result = self.cli('review', '--offline', '--direct')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('Git', result.stderr)

    def test_cli_gateway_daemon_lifecycle(self):
        try:
            result = self.cli('gateway', 'start')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(self.cli('gateway', 'status').stdout)['status'], 'ready')
        finally:
            self.cli('gateway', 'stop')
            import time

            for _ in range(40):
                if not (self.home / 'gateway.json').exists():
                    break
                time.sleep(0.1)
        self.assertFalse((self.home / 'gateway.json').exists())

    def test_gateway_auth_review_and_exclusive_ownership(self):
        (self.project / 'a.py').write_text('print(1)')
        with Gateway(State(self.home), port=0) as gateway:
            thread = threading.Thread(target=gateway.serve, daemon=True)
            thread.start()
            with self.assertRaises(ValueError):
                with Gateway(State(self.home), port=0):
                    pass
            status = gateway_request(self.home, '/health')
            self.assertEqual(status['status'], 'ready')
            result = gateway_request(
                self.home,
                '/review',
                {'project': str(self.project), 'mode': 'offline', 'file': 'a.py'},
            )
            self.assertEqual(result['mode'], 'offline')
            with self.assertRaisesRegex(ProviderError, 'Git'):
                gateway_request(
                    self.home, '/review', {'project': str(self.project), 'mode': 'offline'}
                )
            from urllib import error, request

            with self.assertRaises(error.HTTPError) as error_info:
                request.urlopen(f'http://127.0.0.1:{gateway.port}/health', timeout=2)
            self.assertEqual(error_info.exception.code, 401)
            error_info.exception.close()
            gateway.stop()
            thread.join(timeout=3)
        self.assertFalse((self.home / 'gateway.json').exists())

    def test_real_provider_adapter_contract_and_auth(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, self.headers.get('Authorization'), body))
                content = json.dumps({'summary': 'No findings', 'findings': []})
                response = (
                    {'message': {'content': content}}
                    if self.path == '/api/chat'
                    else {'choices': [{'message': {'content': content}}]}
                )
                raw = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        self.assertEqual(
            complete(ProviderConfig(base_url=base), 'source')['summary'], 'No findings'
        )
        os.environ['DEVPULSE_TEST_API_KEY'] = 'test-key'
        self.addCleanup(os.environ.pop, 'DEVPULSE_TEST_API_KEY', None)
        complete(
            ProviderConfig(
                kind='openai-compatible', base_url=base + '/v1', api_key_env='DEVPULSE_TEST_API_KEY'
            ),
            'source',
        )
        self.assertEqual(received[0][0], '/api/chat')
        self.assertIs(received[0][2]['stream'], False)
        self.assertEqual(received[1][0], '/v1/chat/completions')
        self.assertEqual(received[1][1], 'Bearer test-key')


if __name__ == '__main__':
    unittest.main()
