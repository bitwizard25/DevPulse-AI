import subprocess
import tempfile
import unittest
from pathlib import Path

from devpulse.domain.privacy import Vault
from devpulse.infrastructure.memory import SQLiteMemoryIndex
from devpulse.infrastructure.state import State


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.state = State(self.root / 'state')
        self.index = SQLiteMemoryIndex(self.state)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / '.devpulse').mkdir()

    def test_memory_refresh_handles_edits_deletion_and_project_isolation(self):
        memory = self.project / '.devpulse/MEMORY.md'
        memory.write_text('Use parameterized SQL for database queries.')
        self.index.refresh(self.project, Vault())
        project = self.state.identity(str(self.project))
        found = self.index.search(project, 'SQL database')
        self.assertEqual(found[0].path, '.devpulse/MEMORY.md')
        self.assertEqual(found[0].start, 1)
        self.assertEqual(self.index.search('another-project', 'SQL'), [])
        memory.write_text('Use dependency injection for adapters.')
        self.index.refresh(self.project, Vault())
        self.assertEqual(self.index.search(project, 'SQL database'), [])
        memory.unlink()
        self.index.refresh(self.project, Vault())
        self.assertEqual(self.index.search(project, 'dependency'), [])

    def test_secrets_are_scrubbed_before_indexing_or_chunking(self):
        secret = 'private-database-password'
        (self.project / '.devpulse/MEMORY.md').write_text(
            'Database password="' + secret + '"\n' + 'text ' * 800
        )
        self.index.refresh(self.project, Vault())
        with self.state.connect() as db:
            bodies = '\n'.join(row[0] for row in db.execute('SELECT text FROM chunks'))
        self.assertNotIn(secret, bodies)
        self.assertIn('__SECRET_', bodies)
        self.assertNotIn(secret.encode(), self.state.path.read_bytes())

    def test_indexing_unrelated_secrets_does_not_pollute_review_detection(self):
        (self.project / '.devpulse/MEMORY.md').write_text(
            'password="unrelated-index-private-value"'
        )
        vault = Vault()
        self.index.refresh(self.project, vault)
        self.assertEqual(vault.count, 0)

    def test_code_index_includes_nonignored_untracked_text_and_excludes_credentials(self):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        for filename, text in [
            ('billing.py', 'def calculate_invoice_total(items):\n    return sum(items)\n'),
            ('untracked.py', 'untracked_receipt_amount'),
            ('ignored.py', 'ignored_invoice_total'),
            ('.env', 'PRIVATE=must-not-index'),
            ('generated/cache.py', 'generated_invoice'),
            ('binary.bin', '\x00binary'),
        ]:
            path = self.project / filename
            path.parent.mkdir(exist_ok=True)
            path.write_text(text)
        subprocess.run(
            [
                'git',
                '-C',
                str(self.project),
                'add',
                '--',
                'billing.py',
                '.env',
                'generated/cache.py',
                'binary.bin',
            ],
            check=True,
        )
        (self.project / '.gitignore').write_text('ignored.py\n')
        report = self.index.refresh(self.project, Vault())
        found = self.index.search(
            self.state.identity(str(self.project)), 'invoice total', kind='code'
        )
        self.assertEqual(found[0].path, 'billing.py')
        untracked = self.index.search(
            self.state.identity(str(self.project)), 'untracked receipt', kind='code'
        )
        self.assertEqual(untracked[0].path, 'untracked.py')
        self.assertEqual(found[0].start, 1)
        with self.state.connect() as db:
            paths = {row[0] for row in db.execute('SELECT path FROM documents')}
        self.assertNotIn('.env', paths)
        self.assertIn('untracked.py', paths)
        self.assertNotIn('ignored.py', paths)
        self.assertNotIn('generated/cache.py', paths)
        self.assertNotIn('binary.bin', paths)
        self.assertTrue(report.skipped)

    def test_user_query_cannot_become_fts_syntax_or_sql(self):
        (self.project / '.devpulse/MEMORY.md').write_text('SQL adapter rules')
        self.index.refresh(self.project, Vault())
        found = self.index.search(self.state.identity(str(self.project)), '"SQL" OR (adapter) --')
        self.assertTrue(found)
        self.assertEqual(self.index.search(self.state.identity(str(self.project)), '***'), [])

    def test_secret_discovered_later_is_removed_from_earlier_filename(self):
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        (self.project / 'a-private-password.py').write_text('print(1)')
        (self.project / 'z.py').write_text('password="private-password"')
        subprocess.run(
            ['git', '-C', str(self.project), 'add', '--', 'a-private-password.py', 'z.py'],
            check=True,
        )
        self.index.refresh(self.project, Vault())
        with self.state.connect() as db:
            paths = [row[0] for row in db.execute('SELECT path FROM chunks')]
        self.assertFalse(any('private-password' in path for path in paths))


if __name__ == '__main__':
    unittest.main()
