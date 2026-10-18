import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.domain.hardware import HardwareProfile
from evaluations.cases import CASES
from evaluations.runner import grade_case, local_config, prepare_case


class AgentEvaluationTests(unittest.TestCase):
    def test_local_evaluation_uses_the_same_constrained_budget_as_setup(self):
        profile = HardwareProfile(8 * 1024**3, 5 * 1024**3, 4 * 1024**3, 'Fixture GPU', 'Windows')
        with patch('evaluations.runner.probe_hardware', return_value=profile):
            provider = local_config('fixture-model')['providers'][0]
        self.assertEqual(provider['model'], 'fixture-model')
        self.assertEqual(provider['context_window_tokens'], 4096)
        self.assertEqual(provider['output_tokens'], 512)

    @staticmethod
    def successful_test_action():
        return {
            'name': 'run_command',
            'status': 'completed',
            'result': {'exit_code': 0, 'output': 'Ran 1 test in 0.001s\n\nOK\n'},
        }

    def test_retry_grader_rejects_baseline_and_accepts_behavioral_fix(self):
        case = next(item for item in CASES if item.id == 'retry-bound')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_case(case, root)
            actions = [self.successful_test_action()]
            self.assertFalse(grade_case(case, root, 'Fixed.', actions)['passed'])
            (root / 'retry.py').write_text(
                'def should_retry(attempts):\n    return 0 <= attempts < 3\n', encoding='utf-8'
            )
            self.assertTrue(grade_case(case, root, 'Fixed.', actions)['passed'])

    def test_claimed_verification_without_a_successful_command_does_not_pass(self):
        case = next(item for item in CASES if item.id == 'run-tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_case(case, root)
            result = grade_case(case, root, 'All tests passed.', [])
            self.assertFalse(result['passed'])
            self.assertIn('required_tool', result['failures'])

    def test_modified_acceptance_test_does_not_pass(self):
        case = next(item for item in CASES if item.id == 'run-tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_case(case, root)
            (root / 'test_math.py').write_text('pass\n', encoding='utf-8')
            actions = [self.successful_test_action()]
            result = grade_case(case, root, 'All tests passed.', actions)
            self.assertFalse(result['passed'])
            self.assertIn('unexpected_changes', result['failures'])

    def test_unrelated_successful_command_is_not_test_execution(self):
        case = next(item for item in CASES if item.id == 'run-tests')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_case(case, root)
            actions = [
                {
                    'name': 'run_command',
                    'status': 'completed',
                    'result': {'exit_code': 0, 'output': 'hello'},
                }
            ]
            self.assertFalse(grade_case(case, root, 'Tests passed.', actions)['passed'])

    def test_review_must_find_seeded_issue_without_editing_source(self):
        case = next(item for item in CASES if item.id == 'project-review')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_case(case, root)
            actions = [{'name': 'review_project', 'status': 'completed', 'result': {}}]
            self.assertFalse(grade_case(case, root, 'No actionable findings.', actions)['passed'])
            self.assertTrue(
                grade_case(case, root, 'SQL injection at billing.py:2.', actions)['passed']
            )


if __name__ == '__main__':
    unittest.main()
