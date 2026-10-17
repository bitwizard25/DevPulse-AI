"""Bounded project discovery and file access shared by coding tools."""

import os
from pathlib import Path

from .context import safe_path
from .source import MAX_SOURCE, git

EXCLUDED = frozenset(
    {
        '.git',
        '.venv',
        'venv',
        '.uv-cache',
        '.devpulse',
        '.aws',
        '.ssh',
        '.docker',
        'node_modules',
        '__pycache__',
        'dist',
        'build',
        '.next',
        'coverage',
        'vendor',
    }
)
CREDENTIALS = frozenset(
    {
        '.env',
        '.npmrc',
        '.pypirc',
        '.netrc',
        '.htpasswd',
        'id_rsa',
        'id_ed25519',
        'credentials.json',
        'credentials',
    }
)


class AgentWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or not value or len(value) > 1000:
            raise ValueError('Path must be a non-empty project-relative string.')
        if Path(value).is_absolute():
            raise ValueError('Use a project-relative path.')
        target = safe_path(self.root, self.root / value)
        relative = target.relative_to(self.root)
        if any(part.casefold() in EXCLUDED for part in relative.parts):
            raise ValueError('This path is excluded from agent access.')
        if (
            target.name.casefold() in CREDENTIALS
            or target.name.casefold().startswith('.env.')
            or target.suffix.casefold() in {'.pem', '.key', '.p12', '.pfx', '.db', '.sqlite'}
        ):
            raise ValueError('Secret and credential files are excluded from agent access.')
        return target

    @staticmethod
    def read(path: Path) -> bytes:
        with path.open('rb') as handle:
            raw = handle.read(MAX_SOURCE + 1)
        if len(raw) > MAX_SOURCE or b'\0' in raw:
            raise ValueError('File is binary or exceeds the 512 KB tool limit.')
        try:
            raw.decode('utf-8')
        except UnicodeError:
            raise ValueError('Coding tools require UTF-8 text.') from None
        return raw

    def files(self):
        try:
            names = [
                name.decode('utf-8')
                for name in git(
                    self.root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'
                ).split(b'\0')
                if name
            ]
        except (ValueError, OSError, UnicodeError):
            names = self._walk()
        seen = set()
        for name in names:
            try:
                path = self.path(name)
            except ValueError:
                continue
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            yield path.relative_to(self.root), path
            if len(seen) >= 5000:
                return

    def _walk(self):
        for directory, directories, files in os.walk(self.root, followlinks=False):
            base = Path(directory)
            directories[:] = sorted(
                name
                for name in directories
                if name.casefold() not in EXCLUDED and not (base / name).is_symlink()
            )
            for name in sorted(files):
                yield (base / name).relative_to(self.root).as_posix()
