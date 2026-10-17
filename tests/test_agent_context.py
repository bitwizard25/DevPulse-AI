import json
import unittest

from devpulse.application.agent import AgentSession
from devpulse.application.agent_context import AgentContext
from devpulse.domain.agent import AgentDecision
from devpulse.domain.agent_tools import TOOL_SPECS
from devpulse.domain.privacy import Vault


class LargeTools:
    def describe(self):
        return [
            {'name': 'read_file', 'description': 'Read source', 'inputSchema': {'type': 'object'}}
        ]

    def execute(self, name, arguments):
        return {'path': 'a.py', 'content': 'x' * 7000}


class AgentContextTests(unittest.TestCase):
    def test_task_and_rules_survive_large_tool_results(self):
        requests = []
        events = []

        def model(messages):
            requests.append(messages)
            return json.dumps(
                {
                    'message': 'inspect' if len(requests) < 4 else 'done',
                    'tool_calls': [
                        {
                            'id': str(len(requests)),
                            'name': 'read_file',
                            'arguments': {'path': 'a.py'},
                        }
                    ]
                    if len(requests) < 4
                    else [],
                    'final': len(requests) == 4,
                }
            )

        session = AgentSession(
            model, LargeTools(), Vault().scrub, context_budget_bytes=6500, on_event=events.append
        )
        self.assertEqual(
            session.run('Fix retry bound to 3', 'example', 'Keep the public API unchanged.'), 'done'
        )
        for request in requests:
            text = json.dumps(request, ensure_ascii=False)
            self.assertIn('Fix retry bound to 3', text)
            self.assertIn('Keep the public API unchanged.', text)
            self.assertLessEqual(len(json.dumps(request, ensure_ascii=True).encode()), 6500)
        self.assertTrue(
            any(event['type'] == 'context' and event['omitted_messages'] for event in events)
        )

    def test_oversized_mandatory_guidance_fails_before_model(self):
        called = []

        def model(messages):
            called.append(messages)
            return '{"message":"done","tool_calls":[],"final":true}'

        session = AgentSession(model, LargeTools(), Vault().scrub, context_budget_bytes=50000)
        with self.assertRaisesRegex(ValueError, 'context|guidance|budget'):
            session.run('task', 'example', 'mandatory\n' * 5000)
        self.assertEqual(called, [])

    def test_duplicate_tool_call_ids_are_rejected(self):
        raw = json.dumps(
            {
                'message': '',
                'tool_calls': [
                    {'id': 'same', 'name': 'read_file', 'arguments': {'path': 'a.py'}},
                    {
                        'id': 'same',
                        'name': 'write_file',
                        'arguments': {'path': 'b.py', 'content': 'bad'},
                    },
                ],
                'final': False,
            }
        )
        with self.assertRaisesRegex(ValueError, 'unique|duplicate'):
            AgentDecision.parse(raw)

    def test_small_provider_budget_is_never_silently_increased(self):
        called = []
        session = AgentSession(
            lambda messages: called.append(messages),
            LargeTools(),
            Vault().scrub,
            context_budget_bytes=1000,
        )
        with self.assertRaisesRegex(ValueError, 'budget'):
            session.run('Inspect project', 'example')
        self.assertEqual(called, [])

    def test_escaped_latest_tool_evidence_is_retained_when_compacted(self):
        observations = [{'id': 'read-latest', 'name': 'read_file', 'result': {
            'path': 'source.py', 'content': 'line = "quoted text"\n' * 800,
            'fingerprint': '1' * 64, 'truncated': True,
        }}]
        messages, _ = AgentContext(8192).build('Fix the retry limit', 'example', '', TOOL_SPECS, [], observations)
        evidence = [json.loads(item['content']) for item in messages[3:]]
        latest = next((item for item in evidence if item.get('tool_call_id') == 'read-latest'), None)
        self.assertIsNotNone(latest, 'Compaction dropped the entire latest observation.')
        self.assertEqual(latest['result']['fingerprint'], '1' * 64)
        self.assertIn('content', latest['result'])
        self.assertLessEqual(len(json.dumps(messages, ensure_ascii=True)), 8192)
