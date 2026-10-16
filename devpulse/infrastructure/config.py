"""Read local configuration and environment without exposing credential values."""

import json
import os
from pathlib import Path

from ..domain.models import Config, ProviderConfig
from ..domain.privacy import Vault
from .context import safe_path


def load_config(root: Path) -> Config:
    path = safe_path(root, root / '.devpulse/config.json')
    if not path.exists():
        return Config()
    if path.stat().st_size > 65536:
        raise ValueError('Project configuration is too large.')
    try:
        value = json.loads(path.read_text('utf-8'))
    except (ValueError, RecursionError):
        raise ValueError('Project config.json must contain valid JSON.') from None
    if not isinstance(value, dict) or set(value) - {'providers', 'context_bytes', 'cache_ttl'}:
        raise ValueError('Unknown project configuration fields.')
    items = value.get('providers', [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError('providers must be an array of provider configuration objects.')
    try:
        providers = [ProviderConfig(**item).validate() for item in items]
    except TypeError:
        raise ValueError('Unknown provider configuration fields.') from None
    if len(providers) > 4 or len({p.name for p in providers}) != len(providers):
        raise ValueError('Configure at most four providers with unique names.')
    budget, ttl = value.get('context_bytes', 24000), value.get('cache_ttl', 86400)
    if (
        type(budget) is not int
        or not 1000 <= budget <= 64000
        or type(ttl) is not int
        or not 0 <= ttl <= 604800
    ):
        raise ValueError('Invalid context_bytes or cache_ttl limits.')
    return Config(providers, budget, ttl)


def state_home() -> Path:
    return (
        Path(os.environ.get('DEVPULSE_HOME', str(Path.home() / '.devpulse'))).expanduser().resolve()
    )


def credential_values(config: Config) -> list[str]:
    return [os.environ.get(provider.api_key_env, '') for provider in config.providers]


def protected_vault(config: Config) -> Vault:
    vault = Vault()
    for value in credential_values(config):
        vault.protect(value)
    return vault
