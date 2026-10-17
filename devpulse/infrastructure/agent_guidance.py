"""Explicit root and directory-scoped repository instructions for the coding agent."""

import hashlib

from .context import safe_path


def _read(root, path, vault):
    path = safe_path(root, path)
    if not path.is_file():
        return None
    with path.open('rb') as handle:
        raw = handle.read(128001)
    if len(raw) > 128000:
        raise ValueError(
            'Repository instructions exceed 128 KB; curate them or use a larger model context.'
        )
    return {'path': path.relative_to(root).as_posix(), 'text': vault.scrub(raw.decode('utf-8'))}


def read_agent_guidance(root, vault):
    parts = [
        item
        for name in ('AGENTS.md', 'CLAUDE.md', '.devpulse/RULES.md')
        if (item := _read(root, root / name, vault)) is not None
    ]
    text = '\n'.join(f'--- {item["path"]} ---\n{item["text"]}' for item in parts)
    return {
        'text': vault.scrub(text),
        'sources': [item['path'] for item in parts],
        'fingerprint': hashlib.sha256(text.encode()).hexdigest(),
    }


def scoped_guidance(root, target, vault):
    directories = []
    directory = target.parent
    while directory != root:
        directories.append(directory)
        directory = directory.parent
    return [
        item
        for directory in reversed(directories)
        if (item := _read(root, directory / 'AGENTS.md', vault)) is not None
    ]
