"""Bounded provider diagnostics; never load a model or send source/credentials."""

from ..domain.errors import ProviderError
from .providers import http_json


def probe_provider(config):
    config.validate()
    if config.kind != 'ollama':
        return {
            'status': 'not_checked',
            'message': 'Cloud credentials are inspected locally; no inference request was sent.',
        }
    try:
        result = http_json(
            config.base_url.rstrip('/') + '/api/tags',
            timeout=min(config.timeout, 5),
            service='Ollama',
        )
    except ProviderError as exc:
        return {'status': 'unavailable', 'message': str(exc)}
    models = result.get('models')
    if not isinstance(models, list):
        return {'status': 'invalid_response', 'message': 'Ollama returned an invalid model list.'}
    names = {
        item[key]
        for item in models
        if isinstance(item, dict)
        for key in ('name', 'model')
        if isinstance(item.get(key), str)
    }
    selected = config.model
    if ':' not in selected.rsplit('/', 1)[-1]:
        selected += ':latest'
    if config.model not in names and selected not in names:
        return {
            'status': 'model_missing',
            'message': f'Ollama is running, but the selected model is missing. Run ollama pull {config.model}.',
        }
    return {
        'status': 'ready',
        'message': 'Ollama is reachable and the selected model is installed.',
    }
