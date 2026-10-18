import json
import unittest
from unittest.mock import patch

from devpulse.domain.agent_tools import TOOL_SPECS
from devpulse.domain.models import ProviderConfig
from devpulse.infrastructure.providers import complete, complete_agent


class ProviderStructuredTests(unittest.TestCase):
    @patch('devpulse.infrastructure.providers.http_json')
    def test_ollama_task_transport_requests_the_decision_and_tool_argument_schema(self, http):
        decision = {'message': 'Done', 'tool_calls': [], 'final': True}
        http.return_value = {'message': {'content': json.dumps(decision)}}
        complete_agent(ProviderConfig(), [{'role': 'user', 'content': 'Check all tests.'}])
        schema = http.call_args.kwargs['payload']['format']
        self.assertIsInstance(schema, dict)
        self.assertEqual(set(schema['required']), {'message', 'tool_calls', 'final'})
        self.assertFalse(schema['additionalProperties'])
        calls = schema['properties']['tool_calls']
        self.assertEqual(calls['maxItems'], 1)
        variants = {item['properties']['name']['const']: item for item in calls['items']['anyOf']}
        for tool in TOOL_SPECS:
            variant = variants[tool['name']]
            self.assertFalse(variant['additionalProperties'])
            self.assertEqual(variant['properties']['arguments'], tool['inputSchema'])

    @patch('devpulse.infrastructure.providers.http_json')
    def test_review_transport_does_not_use_task_decision_schema(self, http):
        http.return_value = {
            'message': {'content': json.dumps({'summary': 'Clean.', 'findings': []})}
        }
        complete(ProviderConfig(), 'Review this code.')
        self.assertEqual(http.call_args.kwargs['payload']['format'], 'json')


if __name__ == '__main__':
    unittest.main()
