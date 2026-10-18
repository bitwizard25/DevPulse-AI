"""Short first-run onboarding with automatic local/cloud defaults."""

import getpass
import warnings
from pathlib import Path

from ..domain.hardware import rate_models
from ..infrastructure.config import load_config
from ..infrastructure.credentials import read_api_key, save_api_key
from ..infrastructure.hardware import fetch_models, installed_model_names, probe_hardware
from ..infrastructure.project import CLOUD_PRESETS, initialize, set_model, set_offline
from .output import emit


def ensure_api_key(key_env: str, provider_name: str) -> bool:
    if read_api_key(key_env):
        emit(f'Using your saved {provider_name} API key.')
        return True
    try:
        while True:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                key = getpass.getpass(f'{provider_name} API key (hidden): ').strip()
            if key:
                break
            emit('API key cannot be empty. Enter a key or press Ctrl+C to cancel.')
    except (EOFError, KeyboardInterrupt):
        emit('\nSetup cancelled.')
        return False
    except getpass.GetPassWarning:
        raise ValueError(
            'Hidden API key input needs an interactive terminal. Run devpulse setup there.'
        ) from None
    try:
        persisted = save_api_key(key_env, key)
    except OSError:
        emit('API key is ready for this session; Windows could not save it for future sessions.')
    else:
        emit(
            'API key saved in your Windows user environment and ready to use.'
            if persisted
            else 'API key is ready for this session.'
        )
    return True


def run_setup_wizard(root: Path) -> int:
    config_path = root / '.devpulse/config.json'
    current = load_config(root) if config_path.exists() else None

    local_models = installed_model_names('http://127.0.0.1:11434')
    has_cloud_key = any(read_api_key(preset.api_key_env) for preset in CLOUD_PRESETS.values())
    if current and current.providers:
        default = '1' if current.providers[0].kind == 'ollama' else '2'
    elif current:
        default = '3'
    else:
        default = '2' if has_cloud_key and not local_models else '1'
    emit(f'DevPulse found {len(local_models)} installed local Ollama model(s).')
    emit('Choose a model source: [1] Ollama [2] Online API [3] Offline checks')
    try:
        choice = input(f'Provider [{default}]: ').strip() or default
    except (EOFError, KeyboardInterrupt):
        emit('\nSetup cancelled.')
        return 130

    if choice == '1':
        model = 'qwen2.5-coder:7b'
        if local_models:
            installed = set(local_models)
            rated = rate_models(probe_hardware(), fetch_models())
            model = next(
                (item.spec.name for item in rated if item.spec.name in installed), local_models[0]
            )
        if config_path.exists():
            set_model(root, model, 'ollama')
        else:
            initialize(root, provider='ollama', model=model)
        if not local_models:
            emit(
                f'Ollama is not exposing installed models; configure or pull {model} before prompting.'
            )
        else:
            emit(f'Using installed local model {model}.')
    elif choice == '2':
        emit('Choose an API provider: [1] OpenAI [2] Anthropic [3] Google Gemini')
        try:
            current_choice = next(
                (
                    key
                    for key, kind in {
                        '1': 'openai-compatible',
                        '2': 'anthropic',
                        '3': 'google',
                    }.items()
                    if current and current.providers and current.providers[0].kind == kind
                ),
                '1',
            )
            provider_choice = input(f'API provider [{current_choice}]: ').strip() or current_choice
        except (EOFError, KeyboardInterrupt):
            emit('\nSetup cancelled.')
            return 130
        providers = {
            '1': 'openai-compatible',
            '2': 'anthropic',
            '3': 'google',
        }
        provider = providers.get(provider_choice)
        if not provider:
            raise ValueError('Choose 1 (OpenAI), 2 (Anthropic) or 3 (Google Gemini).')
        preset = CLOUD_PRESETS[provider]
        name, model, base_url, key_env = preset
        if not ensure_api_key(key_env, name):
            return 130
        if config_path.exists():
            set_model(root, model, provider, base_url)
        else:
            initialize(
                root,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key_env=key_env,
            )
        emit(f'Using {name} with model {model}.')
    elif choice == '3':
        if config_path.exists():
            set_offline(root)
        else:
            initialize(root, provider='offline')
        emit('Offline checks are ready. Add Ollama or an online provider to use task sessions.')
    else:
        raise ValueError('Choose 1, 2 or 3.')

    emit(
        'Project rules and memory are ready. Coding-agent bridges remain available with devpulse integrate --all.'
    )
    return 0
