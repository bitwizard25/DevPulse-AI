"""Small HTTP adapters with bounded responses and no credential-bearing redirects."""

import json
import os
import socket
from urllib import error, request

from ..domain.errors import ProviderError
from ..domain.models import ProviderConfig
from ..domain.prompts import SYSTEM
from ..domain.review import validate_result

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
) -> dict:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = request.Request(
        url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}
    )
    try:
        # Ignore ambient HTTP proxies for loopback traffic.
        from urllib.parse import urlsplit

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
    except (error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
        raise ProviderError('Provider connection failed or timed out.', retryable=True) from None
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
        )
        content = (
            result.get('message', {}).get('content')
            if isinstance(result.get('message'), dict)
            else None
        )
    else:
        key = os.environ.get(config.api_key_env)
        if not key:
            raise ProviderError(
                f'Set the environment variable {config.api_key_env} for this provider.'
            )
        result = http_json(
            config.base_url.rstrip('/') + '/chat/completions',
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
            content = result['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            content = None
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
                'format': 'json',
                'options': {
                    'temperature': 0,
                    'num_predict': config.output_tokens,
                    'num_ctx': config.context_window_tokens,
                },
            },
            timeout=config.timeout,
        )
        content = (
            result.get('message', {}).get('content')
            if isinstance(result.get('message'), dict)
            else None
        )
    else:
        key = os.environ.get(config.api_key_env)
        if not key:
            raise ProviderError(
                f'Set the environment variable {config.api_key_env} for this provider.'
            )
        result = http_json(
            config.base_url.rstrip('/') + '/chat/completions',
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
            content = result['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            content = None
    if not isinstance(content, str):
        raise ProviderError('Provider response has no text content.')
    return content
