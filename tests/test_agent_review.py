import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devpulse.bootstrap import make_agent_runtime, make_agent_session
from devpulse.domain.models import Config, ProviderConfig
from devpulse.domain.privacy import Vault
from devpulse.infrastructure.state import State


class AgentReviewTests(unittest.TestCase):
    def test_runtime_composes_project_review_into_task_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            config = Config(providers=[ProviderConfig(name='fixture', model='fixture-model')])
            state = State(Path(directory) / 'state')
            expected = {'summary': 'No findings.', 'findings': [], 'mode': 'ai'}

            with patch('devpulse.bootstrap.make_engine') as make_engine:
                make_engine.return_value.review.return_value = expected
                runtime = make_agent_runtime(state, config)

                self.assertEqual(runtime.review_project(root), expected)
                make_engine.return_value.review.assert_called_once_with(root, config, file='all')

                session = make_agent_session(
                    runtime, config, root, None, lambda *_: True, lambda _: None, Vault()
                )
                tools = {tool['name'] for tool in session.tools.describe()}
                self.assertIn('review_project', tools)
                self.assertEqual(
                    session.tools.execute('review_project', {}),
                    {
                        'status': 'completed',
                        'summary': 'No findings.',
                        'findings': [],
                        'omitted_findings': 0,
                        'provider': None,
                        'model': None,
                        'mode': 'ai',
                        'source': {},
                    },
                )


if __name__ == '__main__':
    unittest.main()
