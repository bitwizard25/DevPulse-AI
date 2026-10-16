"""Exercise actual process death; thread-only tests cannot establish restart recovery."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from devpulse.domain.errors import ProviderError
from devpulse.domain.models import Config, ProviderConfig
from devpulse.interfaces.gateway import gateway_request


class ProcessRecoveryTests(unittest.TestCase):
    def test_killed_gateway_replays_immutable_redacted_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        prompts = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                prompts.append(body['messages'][1]['content'])
                if len(prompts) == 1:
                    entered.set()
                    release.wait(20)
                raw = json.dumps(
                    {
                        'message': {
                            'content': json.dumps({'summary': 'Recovered review', 'findings': []})
                        }
                    }
                ).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass  # The first gateway was intentionally killed.

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, project = root / 'state', root / 'project'
            project.mkdir()
            (project / '.devpulse').mkdir()
            source = project / 'a.py'
            source.write_text('password="original-private-value"\nprint(1)')
            server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
            server.daemon_threads = True
            serving = threading.Thread(target=server.serve_forever, daemon=True)
            serving.start()
            config = Config(
                providers=[ProviderConfig(base_url=f'http://127.0.0.1:{server.server_port}')]
            )
            (project / '.devpulse/config.json').write_text(json.dumps(config.as_dict()))
            env = {
                **os.environ,
                'DEVPULSE_HOME': str(home),
                'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
                'PYTHONUTF8': '1',
            }
            children = []

            def start():
                kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
                child = subprocess.Popen(
                    [sys.executable, '-m', 'devpulse', 'gateway', 'run'],
                    cwd=project,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **kwargs,
                )
                children.append(child)
                for _ in range(100):
                    try:
                        if gateway_request(home, '/health')['status'] == 'ready':
                            return child
                    except (ValueError, ProviderError):
                        pass
                    if child.poll() is not None:
                        self.fail('Gateway exited before becoming ready.')
                    time.sleep(0.05)
                self.fail('Gateway did not become ready.')

            try:
                child = start()
                submitted = subprocess.run(
                    [
                        sys.executable,
                        '-m',
                        'devpulse',
                        'review',
                        '--detach',
                        '--file',
                        'a.py',
                        '--json',
                    ],
                    cwd=project,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(submitted.returncode, 0, submitted.stderr)
                job_id = json.loads(submitted.stdout)['id']
                self.assertTrue(entered.wait(10))
                self.assertEqual(gateway_request(home, '/jobs/' + job_id)['attempts'], 1)
                child.kill()
                child.wait(timeout=10)
                source.write_text('print("changed-after-crash")')
                replacement = start()
                for _ in range(100):
                    job = gateway_request(home, '/jobs/' + job_id)
                    if job['status'] == 'succeeded':
                        break
                    time.sleep(0.05)
                self.assertEqual(job['status'], 'succeeded', job)
                self.assertEqual(job['attempts'], 2)
                self.assertEqual(prompts[0], prompts[1])
                self.assertNotIn('changed-after-crash', prompts[1])
                self.assertNotIn('original-private-value', prompts[1])
                result = subprocess.run(
                    [sys.executable, '-m', 'devpulse', 'jobs', 'wait', job_id, '--json'],
                    cwd=project,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['job_id'], job_id)
                gateway_request(home, '/shutdown', {})
                replacement.wait(timeout=10)
            finally:
                release.set()
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=10)
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
