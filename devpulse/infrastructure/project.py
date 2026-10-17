"""Explicit, Git-trackable project memory. No inferred memory or hidden edits."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import NamedTuple

from ..domain.hardware import ProviderTokenBudget, initial_token_budget
from ..domain.models import Config, ProviderConfig
from ..domain.privacy import Vault
from .context import relative_to_root, safe_path
from .files import ProcessLock, atomic_write
from .hardware import probe_hardware

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

class CloudPreset(NamedTuple):
    name: str
    model: str
    base_url: str
    api_key_env: str


CLOUD_PRESETS = {
    'openai-compatible': CloudPreset(
        'openai', 'gpt-6-luna-fast', 'https://api.openai.com/v1', 'OPENAI_API_KEY'
    ),
    'anthropic': CloudPreset(
        'anthropic', 'claude-sonnet-5', 'https://api.anthropic.com/v1', 'ANTHROPIC_API_KEY'
    ),
    'google': CloudPreset(
        'google',
        'gemini-3.8-flash',
        'https://generativelanguage.googleapis.com/v1beta',
        'GOOGLE_API_KEY',
    ),
}


def _initial_provider_token_limits(provider_kind: str) -> dict:
    budget = (
        initial_token_budget(probe_hardware(), local=True)
        if provider_kind == 'ollama'
        else ProviderTokenBudget()
    )
    return asdict(budget)


def initialize(
    root: Path,
    *,
    provider: str = 'offline',
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
):
    base = safe_path(root, root / '.devpulse')
    base.mkdir(parents=True, exist_ok=True)
    with ProcessLock(base / 'project.lock'):
        providers = []
        if provider != 'offline':
            default_url = (
                'http://127.0.0.1:11434'
                if provider == 'ollama'
                else CLOUD_PRESETS.get(
                    provider,
                    CloudPreset(provider, 'qwen2.5-coder:7b', 'https://api.openai.com/v1', ''),
                ).base_url
            )
            preset = CLOUD_PRESETS.get(provider)
            provider_name = preset.name if preset else provider
            default_key = preset.api_key_env if preset else ''
            providers = [
                ProviderConfig(
                    name=provider_name,
                    kind=provider,
                    model=model or (preset.model if preset else 'qwen2.5-coder:7b'),
                    base_url=base_url or default_url,
                    api_key_env=api_key_env or default_key,
                    **_initial_provider_token_limits(provider),
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
                created.append(relative_to_root(root, path).as_posix())
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


def set_model(
    root: Path,
    model_name: str,
    provider_kind: str = 'ollama',
    base_url: str | None = None,
) -> Path:
    base = safe_path(root, root / '.devpulse')
    base.mkdir(parents=True, exist_ok=True)
    config_path = base / 'config.json'
    preset = CLOUD_PRESETS.get(provider_kind)
    default_name = preset[0] if preset else provider_kind
    default_url = (
        'http://127.0.0.1:11434'
        if provider_kind == 'ollama'
        else preset.base_url if preset else 'https://api.openai.com/v1'
    )
    default_key = preset.api_key_env if preset else ''
    token_limits = _initial_provider_token_limits(provider_kind)

    data = {'providers': [], 'context_bytes': 24000, 'cache_ttl': 86400}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text('utf-8'))
        except Exception:
            pass

    providers = data.get('providers', [])
    updated = False
    selected = None
    for p in providers:
        if p.get('kind') == provider_kind:
            p.update(
                name=default_name,
                kind=provider_kind,
                model=model_name,
                base_url=base_url or default_url,
                api_key_env=default_key,
                **token_limits,
            )
            updated = True
            selected = p
            break
    if not updated and providers:
        p = providers[0]
        p.update(
            name=default_name,
            kind=provider_kind,
            model=model_name,
            base_url=base_url or default_url,
            api_key_env=default_key,
            **token_limits,
        )
        updated = True
        selected = p
    if not updated:
        selected = {
            'name': default_name,
            'kind': provider_kind,
            'model': model_name,
            'base_url': base_url or default_url,
            'api_key_env': default_key,
            **token_limits,
        }
        providers.insert(0, selected)
    providers = [selected] + [item for item in providers if item is not selected]
    unique_providers = []
    seen_names = set()
    for item in providers:
        if item.get('name') not in seen_names:
            unique_providers.append(item)
            seen_names.add(item.get('name'))
    providers = unique_providers[:4]
    data['providers'] = providers
    atomic_write(config_path, json.dumps(data, indent=2) + '\n')
    return config_path


def set_offline(root: Path) -> Path:
    base = safe_path(root, root / '.devpulse')
    base.mkdir(parents=True, exist_ok=True)
    config_path = base / 'config.json'
    data = {'providers': [], 'context_bytes': 24000, 'cache_ttl': 86400}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text('utf-8'))
        except (OSError, ValueError):
            raise ValueError('Cannot update invalid .devpulse/config.json.') from None
    data['providers'] = []
    atomic_write(config_path, json.dumps(data, indent=2) + '\n')
    return config_path
