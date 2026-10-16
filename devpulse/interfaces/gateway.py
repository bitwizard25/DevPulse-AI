"""Exclusive local gateway lifecycle and discovery client."""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..bootstrap import make_runtime
from ..domain.errors import ProviderError
from ..infrastructure.files import ProcessLock, atomic_write
from ..infrastructure.providers import complete, http_json
from ..infrastructure.state import State
from .gateway_http import BoundedServer, make_handler


class Gateway:
    def __init__(self, state: State, port: int = 0, *, transport=complete):
        self.state, self.port = state, port
        self.token = secrets.token_urlsafe(32)
        runtime = make_runtime(state, transport)
        self.engine, self.jobs = runtime.engine, runtime.jobs
        self.service, self.worker = runtime.service, runtime.worker
        self.lock = ProcessLock(state.home / 'gateway.lock')
        self.server = None
        self._serving = threading.Event()
        self.stopping = threading.Event()
        self._wait_slots = threading.BoundedSemaphore(4)
        self._wait_lock = threading.Lock()
        self._waiters = 0

    @property
    def waiting_reviews(self):
        with self._wait_lock:
            return self._waiters

    def begin_wait(self):
        if not self._wait_slots.acquire(blocking=False):
            return False
        with self._wait_lock:
            self._waiters += 1
        return True

    def end_wait(self):
        with self._wait_lock:
            self._waiters -= 1
        self._wait_slots.release()

    def __enter__(self):
        self.lock.__enter__()
        try:
            self.server = BoundedServer(('127.0.0.1', self.port), make_handler(self))
            self.port = self.server.server_port
            self.state.recover()
            atomic_write(
                self.state.home / 'gateway.json',
                json.dumps({'port': self.port, 'token': self.token, 'pid': os.getpid()}),
            )
        except Exception:
            if self.server:
                self.server.server_close()
            self.lock.__exit__(None, None, None)
            raise
        return self

    def serve(self):
        self.worker.start()
        self._serving.set()
        try:
            self.server.serve_forever(poll_interval=0.1)
        finally:
            self._serving.clear()

    def stop(self):
        self.stopping.set()
        self.worker.request_stop()
        if self._serving.is_set():
            self.server.shutdown()

    def __exit__(self, *args):
        try:
            self.stop()
            if self.server:
                self.server.server_close()
            self.worker.stop()
            (self.state.home / 'gateway.json').unlink(missing_ok=True)
        finally:
            self.lock.__exit__(*args)


def gateway_request(home: Path, path: str, payload: dict | None = None) -> dict:
    try:
        descriptor = json.loads((home / 'gateway.json').read_text('utf-8'))
        port = descriptor['port']
        token = descriptor['token']
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str):
            raise ValueError('Invalid gateway descriptor.')
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Gateway is not running. Use devpulse gateway start.') from None
    # URL is built from a validated port, never an arbitrary descriptor host.
    return http_json(
        f'http://127.0.0.1:{port}{path}',
        payload=payload,
        headers={'Authorization': 'Bearer ' + token},
        timeout=1250 if path == '/review' else 3,
        local_error_details=True,
    )


def ensure_gateway(home: Path) -> dict:
    try:
        return gateway_request(home, '/health')
    except (ProviderError, ValueError):
        pass
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {**os.environ, 'DEVPULSE_HOME': str(home)}
    # Preserve source-checkout importability without relying on the client's cwd.
    package_root = str(Path(__file__).resolve().parents[2])
    env['PYTHONPATH'] = package_root + os.pathsep + env.get('PYTHONPATH', '')
    kwargs = (
        {'creationflags': subprocess.CREATE_NO_WINDOW}
        if os.name == 'nt'
        else {'start_new_session': True}
    )
    child = subprocess.Popen(
        [sys.executable, '-m', 'devpulse', 'gateway', 'run'],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    for _ in range(60):
        time.sleep(0.1)
        try:
            return gateway_request(home, '/health')
        except (ProviderError, ValueError):
            # A losing starter can exit while the owner is still publishing its descriptor.
            child.poll()
    raise ValueError(
        'Gateway did not start. Run devpulse gateway run in the foreground to see the error.'
    )
