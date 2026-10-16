"""Authenticated bounded HTTP transport. Review execution belongs to application services."""

import hmac
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from ..domain.errors import ProviderError
from ..domain.privacy import Vault
from ..infrastructure.config import load_config


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Busy\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Request data and exceptions can contain source; never log them.


def review_request(payload):
    if set(payload) - {'project', 'mode', 'file', 'worktree', 'no_cache', 'chaos'}:
        raise ValueError('Unknown review options.')
    if not isinstance(payload.get('project'), str) or not Path(payload['project']).is_absolute():
        raise ValueError('Project must be an absolute path.')
    root = Path(payload['project']).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Project must be a directory.')
    for field in ('worktree', 'no_cache', 'chaos'):
        if field in payload and type(payload[field]) is not bool:
            raise ValueError(f'{field} must be boolean.')
    if payload.get('file') is not None and not isinstance(payload['file'], str):
        raise ValueError('File must be a project-relative path.')
    return root, {key: value for key, value in payload.items() if key != 'project'}


def make_handler(owner):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def send_json(self, code, payload):
            raw = json.dumps(payload).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            auth = self.headers.get('Authorization', '').encode('utf-8')
            if self.headers.get('Origin') or not hmac.compare_digest(
                auth, ('Bearer ' + owner.token).encode()
            ):
                self.send_json(401, {'error': 'Gateway authentication required.'})
                return False
            return True

        def do_GET(self):
            self.handle_request(None)

        def do_POST(self):
            self.handle_request(True)

        def handle_request(self, post):
            if not self.authorized():
                return
            try:
                payload = self.read_payload() if post else None
                code, value = self.route(payload)
                self.send_json(code, value)
            except (
                ValueError,
                TypeError,
                OSError,
                ProviderError,
                subprocess.SubprocessError,
            ) as exc:
                self.send_json(400, {'error': Vault().scrub(str(exc))[:1000]})
            except Exception:
                self.send_json(500, {'error': 'Request failed. Raw input was not logged.'})

        def read_payload(self):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked requests are unsupported.')
            length = int(self.headers.get('Content-Length', '-1'))
            if not 0 <= length <= 16384:
                raise ValueError('Request must be JSON smaller than 16 KB.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Request must be a JSON object.')
            return payload

        def route(self, payload):
            url = urlsplit(self.path)
            if payload is None:
                if url.path == '/health':
                    return 200, {
                        'status': 'stopping' if owner.stopping.is_set() else 'ready',
                        'version': __version__,
                        'waiting_reviews': owner.waiting_reviews,
                    }
                if url.path == '/jobs':
                    query = parse_qs(url.query)
                    jobs = owner.jobs.list(
                        query.get('project', [None])[0], int(query.get('limit', ['20'])[0])
                    )
                    return 200, {'jobs': [job.public(include_result=False) for job in jobs]}
                match = re.fullmatch(r'/jobs/([0-9a-f]{32})', url.path)
                if match:
                    return 200, owner.jobs.get(match[1]).public()
            elif url.path == '/shutdown':
                threading.Thread(target=owner.stop, daemon=True).start()
                return 200, {'status': 'stopping'}
            elif owner.stopping.is_set():
                raise ValueError('Gateway is stopping; retry after restart.')
            elif url.path in ('/jobs', '/review'):
                return self.submit_review(payload, blocking=url.path == '/review')
            else:
                match = re.fullmatch(r'/jobs/([0-9a-f]{32})/(cancel|retry)', url.path)
                if match:
                    if payload:
                        raise ValueError('Job control requests do not accept options.')
                    job = (
                        owner.jobs.cancel(match[1])
                        if match[2] == 'cancel'
                        else owner.jobs.retry(match[1])
                    )
                    return 200, job.public(include_result=False)
            return 404, {'error': 'Unknown gateway endpoint.'}

        def submit_review(self, payload, *, blocking):
            if blocking and not owner.begin_wait():
                return 429, {
                    'error': 'Blocking review capacity reached. Submit with POST /jobs and poll its ID.'
                }
            try:
                root, options = review_request(payload)
                config = load_config(root)
                if blocking and options.get('mode') == 'offline':
                    return 200, owner.engine.review(root, config, **options)
                job = owner.service.submit(root, config, **options)
                if not blocking:
                    return 202, job.public(include_result=False)
                return 200, owner.service.wait(job.id, owner.stopping.is_set)
            finally:
                if blocking:
                    owner.end_wait()

    return Handler
