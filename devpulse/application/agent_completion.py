"""Completion evidence for explicit user requests to execute tests."""

from ..domain.agent_intent import requests_test_execution
from ..domain.test_commands import has_test_summary, is_test_command

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
                if not has_test_summary(self.result.get('output', '')):
                    if code:
                        return (
                            f'\nThe last test command exited {code} before producing a test '
                            'execution summary, so it did not establish whether tests pass. '
                            'Check existing paths with list_files and run from the project root. '
                            'For Python unittest files named test_*.py, use '
                            '`python -m unittest discover -v`. Do not use verify_file as a test runner.'
                        )
                    return (
                        '\nThe last command exited 0 but produced no test execution summary. '
                        'Use the project test runner; importing test definitions does not run them. '
                        'For unittest, use python -m unittest discover -v and inspect the test count.'
                    )
                return (
                    f'\nA test runner result is observed; latest exit code: {code}. '
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
            if self.tests_requested
            else ''
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
                and has_test_summary(self.result.get('output', ''))
            ):
                return None
        if self.repairs >= MAX_COMPLETION_REPAIRS:
            raise ValueError(
                'Requested tests were not executed; the model ended without test evidence.'
            )
        self.repairs += 1
        return {
            'status': 'incomplete',
            'reason': 'Requested tests were not executed. The previous command produced no test execution summary. Inspect existing paths, run the correct project test runner from the project root, then report its output and exit code. For Python unittest files named test_*.py, use python -m unittest discover -v. Do not use verify_file as a test runner or repeat a missing path.',
        }

    def render(self, message):
        if self.result is None:
            return message
        if (
            self.result.get('status') != 'completed'
            or type(self.result.get('exit_code')) is not int
        ):
            return 'Test verification was not completed: ' + self.result.get(
                'error', self.result.get('status', 'no command result')
            )
        if self.result.get('timed_out'):
            return 'The test command timed out; test verification is incomplete.'
        code = self.result['exit_code']
        if not has_test_summary(self.result.get('output', '')):
            if code:
                return (
                    f'The test command failed before producing a test execution summary '
                    f'(exit code {code}); test results are unverified.\n'
                    + self.result.get('output', '')[:4000]
                )
            return 'The command exited 0, but no test execution summary was observed. Test results are unverified.'
        if code:
            return (
                f'The requested test command failed. Test command exit code: {code}.\n'
                + self.result.get('output', '')[:4000]
            )
        return message + f'\n\nTest command exit code: {code}.'
