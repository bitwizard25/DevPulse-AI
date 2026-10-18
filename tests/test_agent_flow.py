import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from devpulse.application.agent import AgentSession
from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_sessions import SQLiteAgentSessions
from devpulse.infrastructure.agent_tools import ProjectTools
from devpulse.infrastructure.state import State
from devpulse.interfaces.cli import main


@contextlib.contextmanager
def model_server(decide):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, body))
            decision = decide(len(requests), body['messages'])
            content = json.dumps(decision) if isinstance(decision, dict) else decision
            value = (
                {'message': {'content': content}}
                if self.path == '/api/chat'
                else {'choices': [{'message': {'content': content}}]}
            )
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def decision(name=None, arguments=None, call_id='step', message='Working'):
    return {
        'message': message,
        'tool_calls': [{'id': call_id, 'name': name, 'arguments': arguments}] if name else [],
        'final': not bool(name),
    }


def latest_result(messages):
    for message in reversed(messages):
        try:
            value = json.loads(message['content'])
            if 'tool_call_id' in value:
                return value['result']
            if value.get('tool_results'):
                return value['tool_results'][-1]['result']
        except (ValueError, TypeError):
            continue
    raise AssertionError('Latest tool evidence missing from model context.')


class AgentFlowTests(unittest.TestCase):
    def test_natural_language_project_review_runs_directly_without_agent_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.devpulse').mkdir()
            reviews = []
            findings = [
                {
                    'rule_id': 'unsafe-query',
                    'severity': 'error',
                    'path': 'billing.py',
                    'line': 14,
                    'message': 'User input is concatenated into SQL.',
                }
            ]

            def reviewer():
                reviews.append(root)
                return {
                    'summary': 'One unsafe query found.',
                    'findings': findings,
                    'provider': 'fixture',
                    'model': 'fixture-model',
                    'mode': 'ai',
                }

            def model(messages):
                self.fail('Explicit project review should use the deterministic review route.')

            tools = ProjectTools(
                root, lambda *_: self.fail('Review must not request approval.'), Vault(), reviewer
            )
            session = AgentSession(model, tools, Vault().scrub, context_budget_bytes=1000)
            answer = session.run(
                'Review the entire repository for security issues.',
                'fixture',
                'irrelevant ' * 3000,
                references=[{'text': 'irrelevant ' * 3000}],
            )

            self.assertIn('billing.py:14', answer)
            self.assertIn('[ERROR]', answer)
            self.assertEqual(reviews, [root])

    def test_final_answer_with_redundant_tool_request_finishes_without_running_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            (root / '.devpulse').mkdir()
            (root / 'retry.py').write_text('return attempts < 10\n')
            state_home = Path(directory) / 'state'

            def decide(step, _messages):
                if step == 1:
                    return decision('read_file', {'path': 'retry.py'}, 'read')
                if step == 2:
                    return decision(
                        'read_file',
                        {'path': 'retry.py', 'start_line': 1, 'limit': 2},
                        'read-again',
                    )
                return {
                    'message': 'Retry when attempts is less than 10.',
                    'tool_calls': [
                        {
                            'id': 'read-again',
                            'name': 'read_file',
                            'arguments': {'path': 'retry.py'},
                        }
                    ],
                    'final': True,
                }

            with model_server(decide) as (url, requests):
                (root / '.devpulse/config.json').write_text(
                    json.dumps(
                        {
                            'providers': [
                                {
                                    'name': 'fixture',
                                    'kind': 'ollama',
                                    'base_url': url,
                                    'model': 'fixture-model',
                                }
                            ]
                        }
                    )
                )
                out, err = io.StringIO(), io.StringIO()
                with (
                    patch.dict(os.environ, {'DEVPULSE_HOME': str(state_home)}),
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                ):
                    code = main(
                        [
                            '--project',
                            str(root),
                            'run',
                            'Read retry.py and report the condition.',
                            '--json',
                        ]
                    )

            self.assertEqual(code, 0, err.getvalue())
            self.assertIn('less than 10', json.loads(out.getvalue())['message'])
            self.assertEqual(len(requests), 3)
            sessions = SQLiteAgentSessions(State(state_home))
            turn = sessions.turns(json.loads(out.getvalue())['session_id'])[0]
            self.assertEqual(turn['status'], 'succeeded')
            actions = sessions.actions(turn['id'])
            self.assertEqual([action['name'] for action in actions], ['read_file', 'read_file'])
            self.assertNotIn('provenance', json.loads(actions[0]['result']))
            self.assertEqual(json.loads(actions[1]['result'])['provenance'], 'reused prior read')

    def test_same_coding_task_works_with_ollama_and_api_and_resumes(self):
        for kind in ('ollama', 'openai-compatible'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'project'
                root.mkdir()
                (root / '.devpulse').mkdir()
                state_home = Path(directory) / 'state'
                (root / 'AGENTS.md').write_text('Keep public APIs stable.')
                (root / 'retry.py').write_text(
                    'password="private-fixture-value"\ndef retry(attempts):\n    return attempts < 10\n'
                )

                def decide(step, messages):
                    self.assertIn('Keep public APIs stable.', json.dumps(messages))
                    self.assertNotIn('private-fixture-value', json.dumps(messages))
                    if step == 1:
                        return decision('read_file', {'path': 'retry.py'}, 'read')
                    if step == 2:
                        result = latest_result(messages)
                        return decision(
                            'edit_file',
                            {
                                'path': 'retry.py',
                                'old_text': 'return attempts < 10',
                                'new_text': 'return attempts < 3',
                                'expected_fingerprint': result['fingerprint'],
                            },
                            'edit',
                        )
                    if step == 3:
                        return decision(
                            'run_command',
                            {
                                'argv': [
                                    sys.executable,
                                    '-c',
                                    'from retry import retry; assert retry(2); assert not retry(3); print("verified")',
                                ]
                            },
                            'check',
                        )
                    if step == 4:
                        result = latest_result(messages)
                        self.assertEqual(result['exit_code'], 0)
                        self.assertIn('verified', result['output'])
                    return decision(message='Updated retry limit and verified behavior.')

                with model_server(decide) as (url, requests):
                    config = {
                        'providers': [
                            {
                                'name': 'fixture',
                                'kind': kind,
                                'base_url': url if kind == 'ollama' else url + '/v1',
                                'model': 'fixture-model',
                                'api_key_env': 'DEVPULSE_FIXTURE_KEY',
                                'context_window_tokens': 16384,
                            }
                        ]
                    }
                    (root / '.devpulse/config.json').write_text(json.dumps(config))
                    env = {
                        'DEVPULSE_HOME': str(state_home),
                        'DEVPULSE_FIXTURE_KEY': 'fixture-private-api-credential',
                    }
                    out, err = io.StringIO(), io.StringIO()
                    with (
                        patch.dict(os.environ, env),
                        contextlib.redirect_stdout(out),
                        contextlib.redirect_stderr(err),
                    ):
                        code = main(
                            [
                                '--project',
                                str(root),
                                'run',
                                'Fix retry bound to 3',
                                '--allow-edits',
                                '--allow-commands',
                                '--json',
                            ]
                        )
                    self.assertEqual(code, 0, err.getvalue())
                    result = json.loads(out.getvalue())
                    self.assertIn('verified', result['message'])
                    self.assertIn('private-fixture-value', (root / 'retry.py').read_text())
                    self.assertIn('return attempts < 3', (root / 'retry.py').read_text())
                    sessions = SQLiteAgentSessions(State(state_home))
                    turn = sessions.turns(result['session_id'])[0]
                    self.assertEqual(turn['status'], 'succeeded')
                    self.assertEqual(
                        [item['status'] for item in sessions.actions(turn['id'])], ['completed'] * 3
                    )
                    out = io.StringIO()
                    with patch.dict(os.environ, env), contextlib.redirect_stdout(out):
                        self.assertEqual(
                            main(
                                [
                                    '--project',
                                    str(root),
                                    'run',
                                    'Summarize the change',
                                    '--session',
                                    result['session_id'],
                                    '--json',
                                ]
                            ),
                            0,
                        )
                    self.assertEqual(len(sessions.turns(result['session_id'])), 2)
                    self.assertIn('Fix retry bound to 3', json.dumps(requests[-1]))
                    db_bytes = (state_home / 'state.db').read_bytes()
                    self.assertNotIn(b'private-fixture-value', db_bytes)
                    self.assertNotIn(b'fixture-private-api-credential', db_bytes)

    def test_interactive_permission_choice_applies_for_the_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.devpulse').mkdir()

            def decide(step, messages):
                return (
                    decision('write_file', {'path': 'new.py', 'content': 'print(1)\n'}, 'create')
                    if step == 1
                    else decision(message='Created file.')
                )

            with model_server(decide) as (url, _):
                (root / '.devpulse/config.json').write_text(
                    json.dumps(
                        {
                            'providers': [
                                {'name': 'fixture', 'base_url': url, 'context_window_tokens': 16384}
                            ]
                        }
                    )
                )
                inputs = iter(['/permissions edit', 'Create a new Python file', '/quit'])
                with (
                    patch.dict(os.environ, {'DEVPULSE_HOME': str(root / 'state')}),
                    patch('sys.stdin.isatty', return_value=True),
                    patch('builtins.input', side_effect=lambda *_: next(inputs)),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(['--project', str(root)]), 0)
                self.assertEqual((root / 'new.py').read_text(), 'print(1)\n')
                store = SQLiteAgentSessions(State(root / 'state'))
                session = store.latest(store.state.identity(str(root.resolve())))
                self.assertEqual(store.get(session['id'])['permission'], 'edit')
