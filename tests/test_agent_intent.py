import unittest

from devpulse.domain.agent_intent import (
    is_read_only_project_review,
    requests_project_review,
    requests_test_execution,
)


class AgentIntentTests(unittest.TestCase):
    def test_explicit_whole_project_reviews_use_the_review_route(self):
        for task in (
            'Review the entire repository for security issues.',
            'Can you audit our whole codebase?',
            'Review the entire code base.',
            'Review the entire repository for security issues. Do not edit files.',
            'Scan all project files for concrete bugs.',
            'Review repo code',
        ):
            with self.subTest(task=task):
                self.assertTrue(is_read_only_project_review(task))

    def test_file_reviews_and_edit_requests_remain_agent_tasks(self):
        for task in (
            'Review billing.py for SQL injection.',
            'Review the whole repo and fix the security bugs.',
            'Fix the retry condition in the project.',
            'Explain how this repository is structured.',
        ):
            with self.subTest(task=task):
                self.assertFalse(is_read_only_project_review(task))

    def test_project_review_tool_remains_available_when_review_is_followed_by_edits(self):
        task = 'Review the entire repo and fix the security issues you find.'
        self.assertTrue(requests_project_review(task))
        self.assertFalse(is_read_only_project_review(task))

    def test_execution_and_targeted_requests_are_not_project_reviews(self):
        for task in (
            'Check all tests pass.',
            'Check the repository tests and report failures.',
            'Review all changes in billing.py.',
            'Review the project configuration file.',
            'Scan all Python files in src/billing for syntax errors.',
            'Explain how to review the entire repo.',
            'Do not review the whole repository.',
        ):
            with self.subTest(task=task):
                self.assertFalse(requests_project_review(task))
                self.assertFalse(is_read_only_project_review(task))

    def test_explicit_test_execution_is_distinguished_from_explanations_and_negations(self):
        for task in (
            'Run the tests.',
            'Check all tests pass.',
            'Fix retry and run unit tests.',
            'Can you verify that all tests pass?',
        ):
            with self.subTest(task=task):
                self.assertTrue(requests_test_execution(task))
        for task in (
            'Explain how to run tests.',
            'Can you explain how to run tests?',
            'Please show me how to run tests.',
            'Do not run tests.',
            "Don't execute the tests.",
            'Write tests for retry.py.',
        ):
            with self.subTest(task=task):
                self.assertFalse(requests_test_execution(task))
        self.assertFalse(is_read_only_project_review('Review the whole repo and run the tests.'))


if __name__ == '__main__':
    unittest.main()
