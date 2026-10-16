"""Validate untrusted model findings and bound review output."""

import json

from .checks import finding
from .errors import ProviderError


def validate_result(value: dict) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != {'summary', 'findings'}
        or not isinstance(value['summary'], str)
        or len(value['summary']) > 8000
    ):
        raise ProviderError('Review response must contain summary and findings only.')
    if not isinstance(value['findings'], list) or len(value['findings']) > 100:
        raise ProviderError('Review findings must be an array of at most 100 items.')
    for item in value['findings']:
        if not isinstance(item, dict) or set(item) != {
            'rule',
            'severity',
            'path',
            'line',
            'message',
        }:
            raise ProviderError('Invalid finding fields.')
        if (
            item['severity'] not in ('error', 'warning', 'info')
            or type(item['line']) is not int
            or item['line'] < 1
        ):
            raise ProviderError('Invalid finding severity or line.')
        if not all(
            isinstance(item[k], str) and len(item[k]) <= 4000 for k in ('rule', 'path', 'message')
        ):
            raise ProviderError('Invalid finding text.')
        path = item['path'].replace('\\', '/')
        if path.startswith('/') or ':' in path or '..' in path.split('/'):
            raise ProviderError('Finding paths must be project-relative.')
    return value


def bound_result(result: dict) -> dict:
    total = len(result['findings'])
    priority = {'error': 0, 'warning': 1, 'info': 2}
    result['findings'] = sorted(result['findings'], key=lambda item: priority[item['severity']])[
        :200
    ]
    while len(json.dumps(result).encode('utf-8')) > 480000 and result['findings']:
        result['findings'].pop()
    omitted = total - len(result['findings'])
    if omitted:
        result['findings'].append(
            finding(
                'findings-truncated',
                'warning',
                '',
                1,
                f'{omitted} additional finding(s) omitted from bounded output. Split the review.',
            )
        )
    return result
