"""Small HTTP adapters with bounded responses and no credential-bearing redirects."""

import json
import socket
from urllib import error, request
from urllib.parse import quote, urlsplit

from ..domain.agent_schema import decision_schema
from ..domain.errors import ProviderError
from ..domain.models import ProviderConfig
from ..domain.prompts import SYSTEM
from ..domain.review import validate_result
from .credentials import read_api_key

MAX_RESPONSE = 1024 * 1024


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(
    url: str,
    *,
    payload: dict | None = None,
    headers: dict | None = None,
    timeout: float = 90,
    local_error_details: bool = False,
    service: str = 'Provider',
) -> dict:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = request.Request(
        url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}
    )
    try:
        # Ignore ambient HTTP proxies for loopback traffic.
        handlers = [NoRedirect()]
        if urlsplit(url).hostname in ('127.0.0.1', 'localhost', '::1'):
            handlers.append(request.ProxyHandler({}))
        with request.build_opener(*handlers).open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProviderError('Provider response exceeds 1 MB.')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProviderError('Provider returned an invalid JSON object.')
        return value
    except error.HTTPError as exc:
        # Never expose or persist response bodies: providers can echo credentials.
        detail = ''
        try:
            if local_error_details:
                value = json.loads(exc.read(16384))
                if isinstance(value, dict) and isinstance(value.get('error'), str):
                    detail = ' ' + value['error'][:1000]
        except (ValueError, UnicodeError):
            pass
        finally:
            exc.close()
        raise ProviderError(
            f'Provider HTTP {exc.code}.' + detail,
            retryable=exc.code in (408, 429) or exc.code >= 500,
        ) from None
    except (error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = exc.reason if isinstance(exc, error.URLError) else exc
        if isinstance(reason, (TimeoutError, socket.timeout)):
            message = f'{service} request timed out after {timeout:g} seconds.'
            if service == 'Ollama':
                message += (
                    ' The model may still be loading or running slowly. Check Ollama'
                    ' and increase the provider timeout in .devpulse/config.json if needed.'
                )
        elif service == 'Ollama':
            parsed = urlsplit(url)
            # Include only the origin, never request paths or raw network errors.
            origin = f'{parsed.scheme}://{parsed.netloc}'
            message = (
                f'Cannot connect to Ollama at {origin}. Start Ollama (ollama serve),'
                ' check the configured base_url, then run devpulse doctor and retry.'
            )
        else:
            message = 'Provider connection failed. Check the endpoint and network connectivity.'
        raise ProviderError(message, retryable=True) from None
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderError('Provider returned malformed JSON.') from None


def complete(config: ProviderConfig, prompt: str) -> dict:
    config.validate()
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
    if config.kind == 'ollama':
        result = http_json(
            config.base_url.rstrip('/') + '/api/chat',
            payload={
                'model': config.model,
                'messages': messages,
                'stream': False,
                'format': 'json',
                'options': {
                    'temperature': 0,
                    'num_predict': config.output_tokens,
                    'num_ctx': config.context_window_tokens,
                },
            },
            timeout=config.timeout,
            service='Ollama',
        )
        content = (
            result.get('message', {}).get('content')
            if isinstance(result.get('message'), dict)
            else None
        )
    else:
        content = _complete_cloud(config, messages)
    if not isinstance(content, str):
        raise ProviderError('Provider response has no text content.')
    try:
        return validate_result(json.loads(content))
    except (ValueError, RecursionError):
        raise ProviderError('Model did not return valid review JSON.') from None


def complete_agent(config: ProviderConfig, messages: list[dict]) -> str:
    """Return one task-harness decision as JSON text using the configured provider."""
    config.validate()
    if config.kind == 'ollama':
        result = http_json(
            config.base_url.rstrip('/') + '/api/chat',
            payload={
                'model': config.model,
                'messages': messages,
                'stream': False,
                'format': decision_schema(),
                'options': {
                    'temperature': 0,
                    'num_predict': config.output_tokens,
                    'num_ctx': config.context_window_tokens,
                },
            },
            timeout=config.timeout,
            service='Ollama',
        )
        content = (
            result.get('message', {}).get('content')
            if isinstance(result.get('message'), dict)
            else None
        )
    else:
        content = _complete_cloud(config, messages)
    if not isinstance(content, str):
        raise ProviderError('Provider response has no text content.')
    return content


def _complete_cloud(config: ProviderConfig, messages: list[dict]) -> str | None:
    key = read_api_key(config.api_key_env)
    if not key:
        raise ProviderError(
            f'No API key found for {config.api_key_env}. Run devpulse setup to enter it.'
        )
    base = config.base_url.rstrip('/')
    if config.kind == 'anthropic':
        system = '\n\n'.join(m['content'] for m in messages if m.get('role') == 'system')
        conversation = [
            {
                'role': 'assistant' if m.get('role') == 'assistant' else 'user',
                'content': m.get('content', ''),
            }
            for m in messages
            if m.get('role') != 'system'
        ]
        result = http_json(
            base + '/messages',
            payload={
                'model': config.model,
                'max_tokens': config.output_tokens,
                'system': system,
                'messages': conversation,
            },
            headers={'x-api-key': key, 'anthropic-version': '2023-06-01'},
            timeout=config.timeout,
        )
        blocks = result.get('content')
        if not isinstance(blocks, list):
            return None
        return '\n'.join(
            block['text']
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get('text'), str)
        )

    if config.kind == 'google':
        system = '\n\n'.join(m['content'] for m in messages if m.get('role') == 'system')
        conversation = [
            {
                'role': 'model' if m.get('role') == 'assistant' else 'user',
                'parts': [{'text': m.get('content', '')}],
            }
            for m in messages
            if m.get('role') != 'system'
        ]
        result = http_json(
            f'{base}/models/{quote(config.model, safe="-_.")}:generateContent',
            payload={
                'systemInstruction': {'parts': [{'text': system}]},
                'contents': conversation,
                'generationConfig': {
                    'responseMimeType': 'application/json',
                    'maxOutputTokens': config.output_tokens,
                    'temperature': 0,
                },
            },
            headers={'x-goog-api-key': key},
            timeout=config.timeout,
        )
        try:
            parts = result['candidates'][0]['content']['parts']
            return ''.join(part['text'] for part in parts if isinstance(part.get('text'), str))
        except (KeyError, IndexError, TypeError):
            return None

    result = http_json(
        base + '/chat/completions',
        payload={
            'model': config.model,
            'messages': messages,
            'response_format': {'type': 'json_object'},
            'max_completion_tokens': config.output_tokens,
        },
        headers={'Authorization': 'Bearer ' + key},
        timeout=config.timeout,
    )
    try:
        return result['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return None
