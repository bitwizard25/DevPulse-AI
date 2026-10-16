import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class McpCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='devpulse-mcp-test-')
        self.root = Path(self.temp_dir.name)
        (self.root / '.devpulse').mkdir()
        (self.root / '.devpulse/RULES.md').write_text(
            '# Project Rules\nAlways write tests.\n', encoding='utf-8'
        )
        (self.root / '.devpulse/MEMORY.md').write_text(
            '# Architecture Decisions\nUse clean architecture.\n', encoding='utf-8'
        )
        (self.root / '.devpulse/config.json').write_text(
            json.dumps({'providers': [{'name': 'off', 'kind': 'offline'}]}),
            encoding='utf-8',
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mcp_stdio_roundtrip(self):
        checkout = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            'PYTHONPATH': str(checkout),
            'PYTHONUTF8': '1',
        }
        cmd = [
            sys.executable,
            '-m',
            'devpulse',
            '--project',
            str(self.root),
            'mcp',
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            # 1. Send initialize
            init_req = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
            proc.stdin.write(init_req + '\n')
            proc.stdin.flush()
            line = proc.stdout.readline()
            res = json.loads(line)
            self.assertEqual(res['id'], 1)
            self.assertEqual(res['result']['serverInfo']['name'], 'devpulse')

            # 2. Call devpulse_verify
            verify_req = json.dumps(
                {
                    'jsonrpc': '2.0',
                    'id': 2,
                    'method': 'tools/call',
                    'params': {
                        'name': 'devpulse_verify',
                        'arguments': {'code': 'def good(): return True\n'},
                    },
                }
            )
            proc.stdin.write(verify_req + '\n')
            proc.stdin.flush()
            line = proc.stdout.readline()
            res2 = json.loads(line)
            self.assertEqual(res2['id'], 2)
            content = json.loads(res2['result']['content'][0]['text'])
            self.assertEqual(content['status'], 'clean')

            # 3. Read resource devpulse://rules
            res_req = json.dumps(
                {
                    'jsonrpc': '2.0',
                    'id': 3,
                    'method': 'resources/read',
                    'params': {'uri': 'devpulse://rules'},
                }
            )
            proc.stdin.write(res_req + '\n')
            proc.stdin.flush()
            line = proc.stdout.readline()
            res3 = json.loads(line)
            self.assertIn('Always write tests', res3['result']['contents'][0]['text'])

        finally:
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
