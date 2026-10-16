"""Guard the dependency direction that keeps adapters replaceable."""

import ast
import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_inner_layers_do_not_import_adapters_or_entry_points(self):
        root = Path(__file__).resolve().parents[1] / 'devpulse'
        for layer in ('domain', 'application'):
            for path in (root / layer).glob('*.py'):
                tree = ast.parse(path.read_text('utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        imported = node.module or ''
                        forbidden = ('infrastructure', 'interfaces', 'bootstrap')
                        self.assertFalse(
                            any(part in imported.split('.') for part in forbidden),
                            f'{path.name} imports {imported}',
                        )
                        if layer == 'domain':
                            self.assertNotIn('application', imported.split('.'))
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn(
                                alias.name.split('.')[0],
                                {'sqlite3', 'subprocess', 'requests', 'httpx'},
                            )


if __name__ == '__main__':
    unittest.main()
