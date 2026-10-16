import tempfile
import unittest
from pathlib import Path

from devpulse.application.context import ContextPlanner
from devpulse.bootstrap import make_engine
from devpulse.domain.models import Config, ProviderConfig
from devpulse.infrastructure.state import State
from devpulse.infrastructure.tokens import ConservativeTokenCounter


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.planner = ContextPlanner(ConservativeTokenCounter())
        self.provider = ProviderConfig(
            context_window_tokens=8192, output_tokens=2048, safety_tokens=1024
        )

    def test_mandatory_source_and_rules_are_never_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, 'Split'):
            self.planner.plan(
                {'mandatory': 'rules', 'candidates': []}, 'x' * 10000, 'file', [self.provider]
            )

    def test_optional_chunks_have_provenance_and_explicit_omission(self):
        context = {
            'mandatory': 'Use SQL parameters.',
            'candidates': [
                {
                    'path': 'MEMORY.md',
                    'kind': 'memory',
                    'start': 1,
                    'end': 20,
                    'text': 'SQL ' * 2000,
                },
                {
                    'path': 'billing.py',
                    'kind': 'code',
                    'start': 10,
                    'end': 30,
                    'text': 'invoice ' * 1000,
                },
            ],
        }
        planned = self.planner.plan(context, 'print(1)', 'file', [self.provider])
        self.assertTrue(planned['context']['omitted'])
        self.assertLessEqual(planned['context']['estimated_input_tokens'], 5120)
        self.assertFalse(planned['context']['token_count_exact'])
        self.assertIn('Use SQL parameters.', planned['prompt'])
        self.assertTrue(planned['context']['selected'])

    def test_smaller_fallback_window_limits_shared_prompt(self):
        small = ProviderConfig(
            name='small', context_window_tokens=4096, output_tokens=1024, safety_tokens=1024
        )
        with self.assertRaises(ValueError):
            self.planner.plan(
                {'mandatory': '', 'candidates': []}, 'x' * 2400, 'file', [self.provider, small]
            )

    def test_index_skip_diagnostics_cannot_overflow_review_transport(self):
        planned = self.planner.plan(
            {'mandatory': '', 'candidates': [], 'index': {'skipped': ['long-path-' * 100] * 5000}},
            'print(1)',
            'file',
            [self.provider],
        )
        import json

        self.assertLess(len(json.dumps(planned['context']).encode()), 100000)
        self.assertEqual(planned['context']['index']['skipped_count'], 5000)

    def test_related_code_is_in_snapshot_with_path_and_line_range(self):
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            (project / 'billing.py').write_text(
                'def calculate_invoice_total(items):\n    return sum(items)\n'
            )
            (project / 'changed.py').write_text('print(calculate_invoice_total([1, 2]))\n')
            subprocess.run(['git', '-C', str(project), 'add', '--', 'billing.py'], check=True)
            engine = make_engine(State(root / 'state'))
            prepared = engine.prepare(project, Config(providers=[self.provider]), file='changed.py')
            self.assertIn('billing.py', prepared.prompt)
            self.assertTrue(
                any(item['path'] == 'billing.py' for item in prepared.context['selected'])
            )


if __name__ == '__main__':
    unittest.main()
