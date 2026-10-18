"""Recognize test runner invocations for evidence checks, never command approval."""

import re
from pathlib import PurePosixPath


def has_test_summary(output: str) -> bool:
    """Require visible test execution, rather than a successful import or syntax check."""
    return bool(
        re.search(
            r'\bRan [1-9]\d* tests?\b|\b[1-9]\d* (?:passed|failed)\b'
            r'|^# tests [1-9]\d*\b|^ok[ \t]+\S+'
            r'|\bPassed:\s*[1-9]\d*\b|out of [1-9]\d*',
            output,
            re.MULTILINE,
        )
    )


def is_test_command(argv) -> bool:
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        return False
    args = [part.lower() for part in argv]
    if any(
        part in ('-h', '--help', '--version', '--collect-only', '--list-tests') for part in args
    ):
        return False
    executable = PurePosixPath(args[0].replace('\\', '/')).name
    executable = re.sub(r'\.(exe|cmd|bat)$', '', executable)
    if executable in ('uv', 'poetry', 'pipenv', 'pdm') and args[1:2] == ['run']:
        return is_test_command(argv[2:])
    if executable in ('npm', 'pnpm', 'yarn') and args[1:2] == ['exec']:
        return is_test_command(argv[2:])
    if executable == 'yarn' and args[1:2] in (['jest'], ['vitest'], ['mocha']):
        return is_test_command(argv[1:])
    if executable in (
        'pytest',
        'py.test',
        'jest',
        'vitest',
        'ctest',
        'mocha',
        'rspec',
        'phpunit',
        'pest',
    ):
        return True
    if executable == 'npx':
        return any(part in ('jest', 'vitest', 'mocha') for part in args[1:])
    if executable == 'node':
        return '--test' in args[1:]
    if executable in ('tox', 'nox'):
        if any(part in ('--showconfig', '--list', '-l', 'list') for part in args[1:]):
            return False
        return executable == 'tox' or any(part.startswith('test') for part in args[1:])
    if executable == 'mvn' and 'verify' in args[1:]:
        return True
    if executable == 'coverage' or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?|py', executable):
        return any(
            part == '-m' and index + 1 < len(args) and args[index + 1] in ('unittest', 'pytest')
            for index, part in enumerate(args)
        ) or any(
            PurePosixPath(part.replace('\\', '/')).name.startswith(('test_', 'run_tests'))
            and part.endswith('.py')
            for part in args[1:]
        )
    if executable in (
        'npm',
        'pnpm',
        'yarn',
        'bun',
        'go',
        'cargo',
        'dotnet',
        'mvn',
        'gradle',
        'gradlew',
        'make',
    ):
        return any(
            part == 'test' or part.startswith('test:') or part == 'check' for part in args[1:]
        )
    return bool(re.fullmatch(r'(?:run[_-]?)?tests?(?:\.(?:sh|ps1|py))?', executable))
