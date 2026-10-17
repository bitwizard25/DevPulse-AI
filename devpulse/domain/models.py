"""Project configuration contains endpoint names, never credential values."""

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit


@dataclass
class ProviderConfig:
    name: str = 'ollama'
    kind: str = 'ollama'
    model: str = 'qwen2.5-coder:7b'
    base_url: str = 'http://127.0.0.1:11434'
    api_key_env: str = ''
    timeout: float = 90
    context_window_tokens: int = 8192
    output_tokens: int = 2048
    safety_tokens: int = 1024

    def validate(self):
        if not all(
            type(value) is int
            for value in (self.context_window_tokens, self.output_tokens, self.safety_tokens)
        ):
            raise ValueError('Provider token limits must be integers.')
        if (
            not 2048 <= self.context_window_tokens <= 1048576
            or not 128 <= self.output_tokens
            or not 256 <= self.safety_tokens
        ):
            raise ValueError('Invalid provider context, output or safety token budget.')
        if self.output_tokens + self.safety_tokens >= self.context_window_tokens:
            raise ValueError('Provider context must exceed output plus safety token reserves.')
        if not all(
            isinstance(v, str)
            for v in (self.name, self.kind, self.model, self.base_url, self.api_key_env)
        ):
            raise ValueError('Provider fields must be strings.')
        parsed = urlsplit(self.base_url)
        if self.kind not in ('ollama', 'openai-compatible', 'anthropic', 'google'):
            raise ValueError('Provider kind must be ollama, openai-compatible, anthropic or google.')
        if (
            parsed.scheme not in ('http', 'https')
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError('Provider URL must have a host and no credentials, query or fragment.')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote provider endpoints require HTTPS.')
        if (
            not self.model
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', self.name)
            or type(self.timeout) not in (int, float)
            or not 1 <= self.timeout <= 300
        ):
            raise ValueError('Provider requires name, model and timeout between 1 and 300 seconds.')
        if self.api_key_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.api_key_env):
            raise ValueError(
                'api_key_env must be an environment variable name, never a credential value.'
            )
        if self.kind != 'ollama' and not self.api_key_env:
            raise ValueError('Cloud providers require an api_key_env variable name.')
        return self


@dataclass
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)
    context_bytes: int = 24000
    cache_ttl: int = 86400

    def as_dict(self):
        return asdict(self)
