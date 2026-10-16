"""Run with an installed environment's Python; exercises the wheel outside the checkout."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@contextmanager
def local_provider():
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if 'wait_for_cancel' in body['messages'][1]['content']:
                entered.set()
                release.wait(10)
            raw = json.dumps(
                {'message': {'content': json.dumps({'summary': 'Fixture review', 'findings': []})}}
            ).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def main():
    checkout = Path(__file__).resolve().parents[1]
    import devpulse

    imported = Path(devpulse.__file__).resolve()
    if imported.parent == checkout / 'devpulse':
        raise RuntimeError(
            'Use the installed virtual environment; this smoke test must not import source code.'
        )
    wheel = checkout / f'dist/devpulse_ai-{devpulse.__version__}-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        assert not any('.uv-cache' in name or '.devpulse/' in name for name in archive.namelist())
        assert 'devpulse/interfaces/cli.py' in archive.namelist()
    with tempfile.TemporaryDirectory(prefix='devpulse-smoke-') as directory:
        root = Path(directory)
        project = root / 'project'
        project.mkdir()
        home = root / 'state'
        env = {**os.environ, 'DEVPULSE_HOME': str(home), 'PYTHONUTF8': '1'}
        env.pop('PYTHONPATH', None)
        executable = Path(sys.executable).parent / (
            'devpulse.exe' if os.name == 'nt' else 'devpulse'
        )

        def run(*args, expected=0):
            result = subprocess.run(
                [str(executable), *args],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != expected:
                raise AssertionError(
                    f'{args}: exit {result.returncode}: {result.stderr} {result.stdout}'
                )
            return result.stdout

        run('init', '--provider', 'offline')
        run('memory', 'add', 'Keep adapters outside the application layer.')
        assert json.loads(run('memory', 'search', 'adapters', '--json'))
        assert (
            'estimated_input_tokens'
            in json.loads(run('context', '--query', 'adapters', '--json'))['context']
        )
        (project / 'bad.py').write_text(
            'password="smoke-private-value"\ndef broken(:\n', encoding='utf-8'
        )
        output = run('review', '--offline', '--file', 'bad.py', '--json', expected=1)
        review = json.loads(output)
        assert any(item['rule'] == 'python-syntax' for item in review['findings'])
        assert 'smoke-private-value' not in output
        assert json.loads(run('sessions', '--json'))[0]['status'] == 'completed'
        assert b'smoke-private-value' not in (home / 'state.db').read_bytes()
        try:
            assert json.loads(run('gateway', 'start'))['status'] == 'ready'
            assert json.loads(run('gateway', 'status'))['status'] == 'ready'
            with local_provider() as (url, entered, release):
                config = {
                    'providers': [
                        {'name': 'fixture', 'kind': 'ollama', 'model': 'test', 'base_url': url}
                    ]
                }
                (project / '.devpulse/config.json').write_text(json.dumps(config), encoding='utf-8')
                (project / 'good.py').write_text('print(1)', encoding='utf-8')
                job = json.loads(run('review', '--detach', '--file', 'good.py', '--json'))
                completed = json.loads(run('jobs', 'wait', job['id'], '--json'))
                assert completed['job_id'] == job['id']
                assert json.loads(run('jobs', 'show', job['id']))['status'] == 'succeeded'
                assert json.loads(run('jobs', 'list', '--json'))
                (project / 'good.py').write_text('print("wait_for_cancel")', encoding='utf-8')
                cancelled = json.loads(run('review', '--detach', '--file', 'good.py', '--json'))
                assert entered.wait(5)
                assert json.loads(run('jobs', 'cancel', cancelled['id']))['cancel_requested']
                release.set()
                for _ in range(50):
                    status = json.loads(run('jobs', 'show', cancelled['id']))
                    if status['status'] == 'cancelled':
                        break
                    time.sleep(0.1)
                assert status['status'] == 'cancelled'
                assert status['result'] is None

                # Smoke test models profiler
                models_out = json.loads(run('models', '--json'))
                assert 'hardware' in models_out and 'ratings' in models_out

                # Smoke test verify gate (clean vs broken)
                assert run('verify', '--file', 'good.py') is not None
                run('verify', '--file', 'bad.py', expected=2)

                # Smoke test integrate command
                integrate_out = json.loads(run('integrate', '--all', '--json'))
                assert integrate_out['status'] == 'success'
                assert (project / '.agents/mcp_config.json').is_file()
                assert (project / 'CLAUDE.md').is_file()
                assert (project / 'AGENTS.md').is_file()
        finally:
            run('gateway', 'stop')
            for _ in range(50):
                if not (home / 'gateway.json').exists():
                    break
                time.sleep(0.1)
        assert not (home / 'gateway.json').exists()
        print(
            'Installed wheel smoke passed: CLI, memory search/context, redaction, syntax, history, durable jobs/results/cancellation, gateway lifecycle.'
        )


if __name__ == '__main__':
    main()
