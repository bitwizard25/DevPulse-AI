"""Completion evidence for explicit user requests to execute tests."""

import re

from ..domain.agent_intent import requests_test_execution
from ..domain.test_commands import is_test_command

MAX_COMPLETION_REPAIRS = 2


class CompletionGate:
    def __init__(self, task):
        self.tests_requested = requests_test_execution(task)
        self.result = None
        self.repairs = 0

    @property
    def guidance(self):
        if self.result is not None:
            if (
                self.result.get('status') == 'completed'
                and type(self.result.get('exit_code')) is int
            ):
                code = self.result['exit_code']
                return (
                    f'\nRequested test execution is observed; latest exit code: {code}. '
                    'Complete any remaining user work and report the actual result. '
                    'Do not restart discovery or repeat unchanged completed checks.'
                )
            if self.result.get('status') == 'not_found':
                return (
                    '\nThe last test executable was not found. Use the active interpreter '
                    'and project runner information in the tool result; do not repeat the missing command.'
                )
        return (
            '\nRequested tests must run with run_command before finishing. verify_file checks syntax only.'
            if self.tests_requested else ''
        )

    def observe(self, name, arguments, result):
        if name == 'run_command' and is_test_command(arguments.get('argv')):
            self.result = result

    def check(self):
        if not self.tests_requested:
            return None
        if self.result is not None:
            if self.result.get('status') == 'denied':
                raise ValueError(
                    'Requested tests were not executed: command permission was denied.'
                )
            if self.result.get('timed_out'):
                raise ValueError('Requested tests did not finish: the command timed out.')
            if (
                self.result.get('status') == 'completed'
                and type(self.result.get('exit_code')) is int
                and not re.search(
                    r'Ran 0 tests?\b|no tests ran', self.result.get('output', ''), re.I
                )
            ):
                return None
        if self.repairs >= MAX_COMPLETION_REPAIRS:
            raise ValueError(
                'Requested tests were not executed; the model ended without test evidence.'
            )
        self.repairs += 1
        return {
            'status': 'incomplete',
            'reason': 'Requested tests were not executed. Use run_command with the project test runner, inspect its output and exit code, then report the actual result. Do not substitute syntax checks or another plan.',
        }

    def render(self, message):
        if self.result is None:
            return message
        if self.result.get('status') != 'completed' or type(self.result.get('exit_code')) is not int:
            return 'Test verification was not completed: ' + self.result.get('error', self.result.get('status', 'no command result'))
        if self.result.get('timed_out'):
            return 'The test command timed out; test verification is incomplete.'
        code = self.result['exit_code']
        if code:
            return (
                f'The requested test command failed. Test command exit code: {code}.\n'
                + self.result.get('output', '')[:4000]
            )
        return message + f'\n\nTest command exit code: {code}.'
