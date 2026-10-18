import unittest

from devpulse.domain.test_commands import is_test_command


class TestCommandTests(unittest.TestCase):
    def test_common_runners_and_environment_wrappers_are_recognized(self):
        for argv in (
            ['python', '-m', 'unittest', 'discover'],
            [r'C:\venv\Scripts\python.exe', '-m', 'pytest'],
            ['uv', 'run', 'pytest'],
            ['poetry', 'run', 'python', '-m', 'pytest'],
            ['coverage', 'run', '-m', 'pytest'],
            ['npm', 'test'],
            ['npm', 'run', 'test:unit'],
            ['pnpm', 'exec', 'vitest', 'run'],
            ['yarn', 'jest'],
            ['node', '--test'],
            ['cargo', 'test'],
            ['go', 'test', './...'],
            ['dotnet', 'test'],
            ['mvn', 'verify'],
            ['tox'],
            ['nox', '-s', 'tests'],
        ):
            with self.subTest(argv=argv):
                self.assertTrue(is_test_command(argv))

    def test_printing_building_and_listing_tests_are_not_test_execution(self):
        for argv in (
            ['echo', 'tests passed'],
            ['python', '-c', 'print("tests passed")'],
            ['python', '-m', 'ast', 'source.py'],
            ['npm', 'run', 'build'],
            ['pytest', '--collect-only'],
            ['pytest', '--help'],
            ['uv', '--help'],
            ['nox', '--list'],
            ['tox', '--showconfig'],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(is_test_command(argv))


if __name__ == '__main__':
    unittest.main()
