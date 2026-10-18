import json
import tempfile
import unittest
from pathlib import Path

from devpulse.application.agent import AgentSession
from devpulse.domain.privacy import Vault
from devpulse.infrastructure.agent_tools import ProjectTools


def reply(message='Done', name=None, arguments=None):
    return json.dumps(
        {
            'message': message,
            'tool_calls': [{'id': 'step', 'name': name, 'arguments': arguments}] if name else [],
            'final': name is None,
        }
    )


class Tools:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {'status': 'completed', 'exit_code': 0, 'output': 'Ran 1 test\nOK'}

    def describe(self):
        return [{'name': 'run_command'}]

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


class AgentCompletionTests(unittest.TestCase):
    def test_premature_test_claim_is_rejected_then_model_can_execute_tests(self):
        tools, requests, events = Tools(), [], []

        def model(messages):
            requests.append(json.dumps(messages))
            if len(requests) == 1:
                return reply('All tests passed.')
            if len(requests) == 2:
                return reply(
                    'Running tests.', 'run_command', {'argv': ['python', '-m', 'unittest']}
                )
            return reply('One test passed.')

        session = AgentSession(model, tools, Vault().scrub, on_event=events.append)
        answer = session.run('Check all tests pass and report the actual result.', 'sample')
        self.assertEqual(len(tools.calls), 1)
        self.assertIn('not executed', requests[1])
        self.assertIn('One test passed.', answer)
        self.assertFalse(any(item.get('text') == 'All tests passed.' for item in events))

    def test_repeated_unverified_final_answers_fail_instead_of_succeeding(self):
        tools = Tools()
        session = AgentSession(lambda _: reply('All tests passed.'), tools, Vault().scrub)
        with self.assertRaisesRegex(ValueError, 'tests.*not.*executed'):
            session.run('Run the tests.', 'sample')
        self.assertEqual(tools.calls, [])

    def test_unrelated_command_cannot_satisfy_requested_test_execution(self):
        tools = Tools()
        responses = iter(
            [
                reply('Print status.', 'run_command', {'argv': ['echo', 'tests passed']}),
                reply('All tests passed.'),
                reply('All tests passed.'),
                reply('All tests passed.'),
            ]
        )
        session = AgentSession(lambda _: next(responses), tools, Vault().scrub)
        with self.assertRaisesRegex(ValueError, 'tests.*not.*executed'):
            session.run('Run the tests.', 'sample')

    def test_failed_test_exit_remains_visible_even_if_model_claims_success(self):
        tools = Tools({'status': 'completed', 'exit_code': 1, 'output': 'FAILED (failures=1)'})
        responses = iter(
            [
                reply('Run tests.', 'run_command', {'argv': ['python', '-m', 'unittest']}),
                reply('All tests passed.'),
            ]
        )
        session = AgentSession(lambda _: next(responses), tools, Vault().scrub)
        answer = session.run('Run the tests and report the actual result.', 'sample')
        self.assertIn('exit code: 1', answer)
        self.assertNotIn('All tests passed.', answer)

    def test_denied_test_command_is_not_retried_by_the_completion_guard(self):
        tools = Tools({'status': 'denied'})
        responses = iter(
            [
                reply('Run tests.', 'run_command', {'argv': ['python', '-m', 'unittest']}),
                reply('All tests passed.'),
            ]
        )
        session = AgentSession(lambda _: next(responses), tools, Vault().scrub)
        with self.assertRaisesRegex(ValueError, 'permission was denied'):
            session.run('Run the tests.', 'sample')
        self.assertEqual(len(tools.calls), 1)

    def test_test_failure_is_reported_even_when_user_only_requested_a_code_fix(self):
        tools = Tools({'status': 'completed', 'exit_code': 1, 'output': 'FAILED (failures=1)'})
        responses = iter(
            [
                reply('Verify change.', 'run_command', {'argv': ['python', '-m', 'unittest']}),
                reply('Fixed; all tests passed.'),
            ]
        )
        session = AgentSession(lambda _: next(responses), tools, Vault().scrub)
        answer = session.run('Fix the retry condition.', 'sample')
        self.assertIn('exit code: 1', answer)
        self.assertNotIn('all tests passed', answer)

    def test_empty_or_zero_test_output_cannot_be_reported_as_passing(self):
        for output in ('', 'Ran 0 tests\nOK'):
            with self.subTest(output=output):
                tools = Tools({'status': 'completed', 'exit_code': 0, 'output': output})
                responses = iter(
                    [
                        reply(
                            'Run test file.', 'run_command', {'argv': ['python', 'test_math.py']}
                        ),
                        reply('All tests passed.'),
                        reply('All tests passed.'),
                        reply('All tests passed.'),
                    ]
                )
                session = AgentSession(
                    lambda _, responses=responses: next(responses), tools, Vault().scrub
                )
                with self.assertRaisesRegex(ValueError, 'tests.*not.*executed'):
                    session.run('Run all tests.', 'sample')

    def test_empty_literal_file_filter_provides_real_paths_and_recovery_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test_math.py').write_text('pass\n')
            tools = ProjectTools(root, lambda *_: False, Vault())
            result = tools.execute('list_files', {'query': 'test files'})
            self.assertEqual(result['paths'], [])
            self.assertIn('literal', result['hint'])
            self.assertIn('test_math.py', result['sample_paths'])


if __name__ == '__main__':
    unittest.main()
