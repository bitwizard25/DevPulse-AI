import subprocess
import tempfile
import unittest
from pathlib import Path

from devpulse.infrastructure.source import collect


class ProjectSourceTests(unittest.TestCase):
    def test_whole_project_review_includes_untracked_and_excludes_ignored_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'tracked.py').write_text('tracked_value = 1\n')
            subprocess.run(['git', '-C', str(root), 'add', '--', 'tracked.py'], check=True)
            (root / 'untracked.py').write_text('untracked_value = 2\n')
            (root / 'ignored.py').write_text('ignored_value = 3\n')
            (root / '.env').write_text('PRIVATE=never_review')
            (root / '.gitignore').write_text('ignored.py\n')

            source = collect(root, all_files=True)

            self.assertIn('tracked.py', source['text'])
            self.assertIn('untracked.py', source['text'])
            self.assertNotIn('ignored.py', source['text'])
            self.assertNotIn('never_review', source['text'])
            self.assertEqual(
                {item['path'] for item in source['files']},
                {'tracked.py', 'untracked.py'},
            )

    def test_whole_project_review_reports_file_limit_omissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            for index in range(151):
                (root / f'module_{index:03}.py').write_text(f'value_{index} = {index}\n')

            source = collect(root, all_files=True)

            self.assertEqual(len(source['files']), 150)
            self.assertEqual(source['files_in_prompt'], 150)
            self.assertEqual(source['files_omitted_from_prompt'], 1)


if __name__ == '__main__':
    unittest.main()
