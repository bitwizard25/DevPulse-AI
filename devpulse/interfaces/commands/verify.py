"""Deterministic AST syntax and secret verification gate (Compiler-as-a-Judge)."""

import sys
from pathlib import Path

from ...domain.checks import check_python
from ...domain.privacy import Vault
from ...infrastructure.context import safe_path
from ..output import emit


def handle(args, root: Path) -> int:
    source_text = ''
    target_path = getattr(args, 'file', None)
    is_python = True

    if target_path:
        file_path = safe_path(root, root / target_path)
        if not file_path.is_file():
            raise ValueError(f'File not found: {target_path}')
        source_text = file_path.read_text(encoding='utf-8', errors='replace')
        is_python = file_path.suffix.lower() == '.py'
    elif getattr(args, 'code', None):
        source_text = args.code
    elif not sys.stdin.isatty():
        source_text = sys.stdin.read()
    else:
        raise ValueError('Provide --file, --code, or pipe source code via stdin.')

    vault = Vault()
    vault.scrub(source_text)

    errors = []

    # 1. Secret detection gate
    if vault.count > 0:
        errors.append(
            {
                'rule': 'secret-leak',
                'severity': 'error',
                'message': f'Secret detected ({vault.count} pattern(s) identified).',
                'path': target_path or 'stdin',
                'line': 1,
            }
        )

    # 2. Syntax verification gate
    if is_python and source_text.strip():
        fake_path = target_path or 'stdin.py'
        findings = check_python([{'path': fake_path, 'content': source_text}])
        for f in findings:
            if f['severity'] == 'error':
                errors.append(
                    {
                        'rule': f['rule'],
                        'severity': f['severity'],
                        'message': f['message'],
                        'path': f['path'],
                        'line': f['line'],
                    }
                )

    as_json = getattr(args, 'json', False)

    if errors:
        if as_json:
            emit({'status': 'failed', 'errors': errors}, as_json=True)
        else:
            emit(f'DevPulse Verify Gate | FAILED ({len(errors)} error(s))')
            for err in errors:
                emit(f'  ERROR {err["path"]}:{err["line"]} [{err["rule"]}] {err["message"]}')
        # Exit code 2 is the standard blocker for Claude Code & agent pre-tool hooks
        return 2

    if as_json:
        emit({'status': 'clean'}, as_json=True)
    else:
        emit('DevPulse Verify Gate | Clean (no syntax errors or secrets detected)')
    return 0
