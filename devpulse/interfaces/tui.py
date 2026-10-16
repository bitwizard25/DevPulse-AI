"""Minimal line-oriented terminal dashboard using the same review engine."""

import sys
from pathlib import Path

from ..bootstrap import make_engine
from ..domain.errors import ProviderError
from ..domain.privacy import Vault
from ..infrastructure.config import load_config, protected_vault, state_home
from ..infrastructure.project import read_memory
from ..infrastructure.state import State
from .commands.jobs import wait_for_result
from .gateway import ensure_gateway, gateway_request
from .output import emit, render_review


def dashboard(root: Path):
    if not sys.stdin.isatty():
        raise ValueError(
            'The dashboard requires an interactive terminal. Use review --json for automation.'
        )
    state = State(state_home())
    engine = make_engine(state)
    while True:
        emit(
            f'\nDevPulse | {root.name}\n[r] AI staged review  [o] Offline staged checks  [m] Memory  [s] Sessions  [q] Quit'
        )
        action = input('> ').strip().lower()
        if action == 'q':
            return
        try:
            if action in ('r', 'o'):
                if action == 'o':
                    result = engine.review(root, load_config(root), mode='offline')
                else:
                    ensure_gateway(state.home)
                    job = gateway_request(state.home, '/jobs', {'project': str(root)})
                    result = wait_for_result(job['id'])
                render_review(result)
            elif action == 'm':
                emit(read_memory(root, protected_vault(load_config(root))))
            elif action == 's':
                for row in state.sessions(project=state.identity(str(root))):
                    emit(f'{row["id"]}  {row["status"]}')
            else:
                emit('Choose r, o, m, s or q.')
        except (ValueError, OSError, ProviderError) as exc:
            emit('Review unavailable: ' + Vault().scrub(str(exc)))
