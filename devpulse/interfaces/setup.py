"""Short first-run onboarding with automatic local/cloud defaults."""

import os
from pathlib import Path

from ..domain.hardware import rate_models
from ..infrastructure.config import load_config
from ..infrastructure.hardware import fetch_models, installed_model_names, probe_hardware
from ..infrastructure.project import initialize, set_model
from .output import emit


def run_setup_wizard(root: Path) -> int:
    config_path = root / '.devpulse/config.json'
    if config_path.exists():
        current = load_config(root)
        if current.providers:
            return 0

    local_models = installed_model_names('http://127.0.0.1:11434')
    has_openai_key = bool(os.environ.get('OPENAI_API_KEY'))
    default = '2' if has_openai_key and not local_models else '1'
    emit(f'DevPulse found {len(local_models)} installed local Ollama model(s).')
    emit('Choose a model source: [1] Ollama [2] OpenAI-compatible [3] Offline checks')
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
        if config_path.exists():
            set_model(root, 'gpt-4o-mini', 'openai-compatible')
        else:
            initialize(
                root,
                provider='openai-compatible',
                model='gpt-4o-mini',
                base_url='https://api.openai.com/v1',
                api_key_env='OPENAI_API_KEY',
            )
        if not has_openai_key:
            emit('Set OPENAI_API_KEY in your environment before asking for a task.')
    elif choice == '3':
        initialize(root, provider='offline')
        emit('Offline checks are ready. The task agent needs an Ollama or OpenAI-compatible model.')
    else:
        raise ValueError('Choose 1, 2 or 3.')

    emit(
        'Project rules and memory are ready. Coding-agent bridges remain available with devpulse integrate --all.'
    )
    return 0
