"""Read state metadata, maintain retention, and inspect installation health."""

import subprocess
import sys
from pathlib import Path

from ... import __version__
from ...domain.privacy import Vault
from ...infrastructure.agent_sessions import SQLiteAgentSessions
from ...infrastructure.config import load_config, state_home
from ...infrastructure.context import assemble
from ...infrastructure.credentials import read_api_key
from ...infrastructure.provider_health import probe_provider
from ...infrastructure.state import State
from ..output import emit


def sessions(args, root: Path) -> int:
    if not 1 <= args.limit <= 200:
        raise ValueError('Session limit must be between 1 and 200.')
    state = State(state_home())
    project = state.identity(str(root))
    rows = [{'kind': 'review', **row} for row in state.sessions(args.limit, project)]
    for row in SQLiteAgentSessions(state).list(project, args.limit):
        rows.append(
            {
                'kind': 'agent',
                'id': row['id'],
                'project': row['project'],
                'status': row['status'],
                'started': row['created'],
                'finished': row['updated'],
                'error': None,
                'title': row['title'],
            }
        )
    rows.sort(key=lambda item: item['started'] or 0, reverse=True)
    rows = rows[: args.limit]
    if args.json:
        emit(rows, True)
    else:
        for row in rows:
            emit(f'{row["id"]}  {row["kind"]}  {row["status"]}')
        if not rows:
            emit('No review sessions for this project yet.')
    return 0


def cache(args, root: Path) -> int:
    State(state_home()).clear_cache()
    emit('Local response cache cleared.')
    return 0


def prune(args, root: Path) -> int:
    if args.days < 1:
        raise ValueError('Retention must be at least one day.')
    emit(f'Removed {State(state_home()).prune(args.days)} old session(s).')
    return 0


def doctor(args, root: Path) -> int:
    config = load_config(root)
    state = State(state_home())
    try:
        version = subprocess.run(
            ['git', '--version'], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = 'Git unavailable'
    emit(
        {
            'version': __version__,
            'python': sys.version.split()[0],
            'git': version,
            'state': str(state.home),
            'project': str(root),
            'providers': [
                {
                    'name': p.name,
                    'kind': p.kind,
                    'model': p.model,
                    'health': probe_provider(p),
                    'credential_set': bool(read_api_key(p.api_key_env))
                    if p.kind != 'ollama'
                    else None,
                }
                for p in config.providers
            ],
            'context': assemble(root, Vault(), config.context_bytes)['sources'],
        },
        True,
    )
    return 0
