"""Explicit, Git-trackable project memory. No inferred memory or hidden edits."""

import json
from pathlib import Path

from ..domain.models import Config, ProviderConfig
from ..domain.privacy import Vault
from .context import safe_path
from .files import ProcessLock, atomic_write

RULES = """# Project review rules

- Prefer small, maintainable changes that follow existing conventions.
- Report concrete correctness and security issues with file and line references.
- Never claim a test passed without executing it.
"""
MEMORY = """# Project memory

Record stable architecture decisions and constraints here. This file is included in reviews.
Do not store credentials or paste private logs.
"""
SKILL = """---
name: security-review
description: Review changed code for concrete security risks.
---

Check untrusted input boundaries, parameterized queries, authentication, and command execution.
Explain the trigger and impact of each issue. Avoid speculative findings.
"""


def initialize(root: Path, *, provider: str, model: str, base_url: str | None, api_key_env: str):
    base = safe_path(root, root / '.devpulse')
    base.mkdir(parents=True, exist_ok=True)
    with ProcessLock(base / 'project.lock'):
        providers = []
        if provider != 'offline':
            default_url = (
                'http://127.0.0.1:11434' if provider == 'ollama' else 'https://api.openai.com/v1'
            )
            providers = [
                ProviderConfig(
                    name=provider,
                    kind=provider,
                    model=model,
                    base_url=base_url or default_url,
                    api_key_env=api_key_env,
                ).validate()
            ]
        files = {
            'config.json': json.dumps(Config(providers=providers).as_dict(), indent=2) + '\n',
            'RULES.md': RULES,
            'MEMORY.md': MEMORY,
            'skills/security/SKILL.md': SKILL,
            '.gitignore': 'config.json\nproject.lock\n*.tmp\n',
        }
        created = []
        for name, content in files.items():
            path = safe_path(root, base / name)
            if not path.exists():
                atomic_write(path, content)
                created.append(str(path.relative_to(root)))
        return created


def read_memory(root: Path, vault: Vault | None = None) -> str:
    path = safe_path(root, root / '.devpulse/MEMORY.md')
    if not path.exists():
        raise ValueError('Project memory is not initialized. Run devpulse init.')
    if path.stat().st_size > 128000:
        raise ValueError('Memory exceeds 128 KB; curate MEMORY.md before continuing.')
    return (vault or Vault()).scrub(path.read_text('utf-8'))


def add_memory(root: Path, text: str, vault: Vault | None = None):
    vault = vault or Vault()
    if not text.strip() or len(text.encode()) > 4000:
        raise ValueError('Memory entries must contain between 1 and 4000 bytes.')
    base = safe_path(root, root / '.devpulse')
    if not base.is_dir():
        raise ValueError('Run devpulse init before adding project memory.')
    with ProcessLock(base / 'project.lock'):
        previous = read_memory(root, vault)
        content = previous.rstrip() + '\n\n- ' + vault.scrub(text.strip()) + '\n'
        if len(content.encode()) > 128000:
            raise ValueError('Memory exceeds 128 KB; curate MEMORY.md before continuing.')
        atomic_write(safe_path(root, base / 'MEMORY.md'), content)
