"""Best-effort local redaction. Vault contents never leave the request scope."""

import math
import re
from collections import Counter


class Vault:
    def __init__(self, namespace: str = ''):
        self._values: dict[str, str] = {}
        self._detected: set[str] = set()
        self._namespace = namespace

    def _mask(self, value: str) -> str:
        self._detected.add(value)
        return self._register(value)

    def _register(self, value: str) -> str:
        if value not in self._values:
            self._values[value] = f'__SECRET_{self._namespace}{len(self._values) + 1:03d}__'
        return self._values[value]

    def protect(self, value: str):
        if value:
            self._register(value)

    def fork(self):
        """Protect known values while keeping derived-index detections request-local."""
        child = Vault(namespace='INDEX_')
        child._values = dict(self._values)
        return child

    def _replace_known(self, text: str) -> str:
        for value in sorted(self._values, key=len, reverse=True):
            if value in text:
                self._detected.add(value)
                text = text.replace(value, self._values[value])
        return text

    def scrub(self, text: str) -> str:
        # Replace known values first, including values repeated without a key name.
        text = self._replace_known(text)
        text = re.sub(
            r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?-----END (?:[A-Z ]*PRIVATE KEY)-----',
            lambda m: self._mask(m[0]),
            text,
        )
        text = re.sub(
            r'(?i)(\b(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|password|passwd|token|client_secret|aws_secret_access_key)\b["\x27]?\s*[:=]\s*["\x27]?)([^\s"\x27,;}{]+)',
            lambda m: m[1] + (m[2] if m[2].startswith('__SECRET_') else self._mask(m[2])),
            text,
        )
        text = re.sub(
            r'(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]+)', lambda m: m[1] + self._mask(m[2]), text
        )
        text = re.sub(
            r'\b(?:sk-[A-Za-z0-9_-]{16,}|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,})\b',
            lambda m: self._mask(m[0]),
            text,
        )

        def entropy_mask(match):
            value = match[0]
            entropy = -sum(
                (n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values()
            )
            return self._mask(value) if entropy >= 4.0 else value

        text = re.sub(r'(?<![\w])[A-Za-z0-9_+/=-]{24,}(?![\w])', entropy_mask, text)
        return self._replace_known(text)

    @property
    def count(self) -> int:
        return len(self._detected)

    def scrub_value(self, value):
        """Scrub string leaves without corrupting JSON escape sequences or field names."""
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, list):
            return [self.scrub_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.scrub_value(item) for key, item in value.items()}
        return value
