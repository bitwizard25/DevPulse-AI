"""Agent ecosystem integration command for Claude Code, Antigravity, and Codex."""

from pathlib import Path

from ...infrastructure.integrate import (
    integrate_all,
    integrate_antigravity,
    integrate_claude,
    integrate_codex,
    sync_rules,
)
from ..output import emit


def handle(args, root: Path) -> int:
    files = []
    if getattr(args, 'sync_only', False):
        files = sync_rules(root)
        action_name = 'Rule sync'
    elif getattr(args, 'claude', False):
        files = integrate_claude(root)
        action_name = 'Claude Code bridge'
    elif getattr(args, 'antigravity', False):
        files = integrate_antigravity(root)
        action_name = 'Google Antigravity bridge'
    elif getattr(args, 'codex', False):
        files = integrate_codex(root)
        action_name = 'OpenAI Codex CLI bridge'
    else:
        files = integrate_all(root)
        action_name = 'All agent bridges'

    if getattr(args, 'json', False):
        emit({'status': 'success', 'action': action_name, 'files': files}, as_json=True)
        return 0

    emit(f'DevPulse Bridge | {action_name} complete')
    for f in files:
        rel = Path(f).relative_to(root) if Path(f).is_relative_to(root) else f
        emit(f'  configured: {rel}')

    emit(
        'Ready: DevPulse MCP server and Compiler-as-a-Judge hooks are configured for your coding agents.'
    )
    return 0
