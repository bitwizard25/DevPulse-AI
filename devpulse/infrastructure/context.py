"""Deterministic, bounded context assembled from explicit project memory."""

import hashlib
from pathlib import Path

from ..domain.privacy import Vault


def safe_path(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Path escapes the project directory.')
    return resolved


def read_rules(root: Path, vault: Vault) -> dict:
    path = safe_path(root, root / '.devpulse/RULES.md')
    if not path.is_file():
        return {'text': '', 'fingerprint': '', 'sources': []}
    with path.open('rb') as handle:
        raw = handle.read(128001)
    if len(raw) > 128000:
        raise ValueError('Project rules exceed 128 KB; curate RULES.md before continuing.')
    return {
        'text': '\n--- .devpulse/RULES.md ---\n'
        + vault.scrub(raw.decode('utf-8', errors='replace')),
        'fingerprint': hashlib.sha256(raw).hexdigest(),
        'sources': ['.devpulse/RULES.md'],
    }


def assemble(root: Path, vault: Vault, budget: int = 24000) -> dict:
    parts = []
    sources = []
    remaining = budget
    truncated = False
    fingerprint = hashlib.sha256()
    base = safe_path(root, root / '.devpulse')
    candidates = [base / 'RULES.md', base / 'MEMORY.md']
    skills = safe_path(root, base / 'skills')
    if skills.is_dir():
        candidates += sorted(skills.glob('*/SKILL.md'))[:20]
    for path in candidates:
        path = safe_path(root, path)
        if not path.is_file():
            continue
        if remaining <= 0:
            truncated = True
            break
        with path.open('rb') as handle:
            raw = handle.read(128001)
        if len(raw) > 128000:
            raise ValueError(
                'Context file exceeds 128 KB; split or curate project memory and skills.'
            )
        fingerprint.update(str(path.relative_to(root)).encode())
        fingerprint.update(raw)
        # Scrub before truncation so a cut token cannot expose its prefix.
        text = vault.scrub(raw.decode('utf-8', errors='replace'))
        block = f'\n--- {path.relative_to(root)} ---\n{text}'
        encoded = block.encode('utf-8')
        used = encoded[:remaining].decode('utf-8', errors='ignore')
        parts.append(used)
        sources.append(str(path.relative_to(root)))
        remaining -= len(used.encode('utf-8'))
        truncated |= len(encoded) > len(used.encode('utf-8')) or len(raw) > budget
    return {
        'text': ''.join(parts),
        'sources': sources,
        'truncated': truncated,
        'budget_bytes': budget,
        'fingerprint': fingerprint.hexdigest(),
    }
