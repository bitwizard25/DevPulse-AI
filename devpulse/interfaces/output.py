"""Human output cannot interpret model-supplied terminal escape sequences."""

import json
import re


def terminal_safe(value) -> str:
    text = str(value)
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


def emit(value, as_json: bool = False):
    safe_text = json.dumps(value, indent=2, ensure_ascii=True) if as_json else terminal_safe(value)
    try:
        print(safe_text)
    except UnicodeEncodeError:
        import sys

        try:
            sys.stdout.buffer.write(
                (safe_text + '\n').encode(sys.stdout.encoding or 'utf-8', errors='replace')
            )
            sys.stdout.buffer.flush()
        except Exception:
            print(safe_text.encode('ascii', errors='replace').decode('ascii'))


def render_review(result: dict, as_json: bool = False):
    if as_json:
        emit(result, True)
        return
    emit(
        f'DevPulse | {result["mode"]} | {result["provider"]} | cache {result["cache"]} | {result["elapsed_ms"]} ms'
    )
    emit(result['summary'])
    for item in result['findings']:
        location = f'{item["path"]}:{item["line"]}' if item['path'] else 'project'
        emit(f'  {item["severity"].upper():7} {location} [{item["rule"]}] {item["message"]}')
    emit(
        f'{len(result["findings"])} finding(s) | {result["redacted_values"]} redacted value(s) | session {result["session"]}'
    )
    if result['context']['truncated']:
        emit('Context budget reached; some project guidance was omitted.')


def review_exit(result: dict, fail_on: str) -> int:
    levels = {'none': set(), 'error': {'error'}, 'warning': {'error', 'warning'}}
    return int(any(item['severity'] in levels[fail_on] for item in result['findings']))
