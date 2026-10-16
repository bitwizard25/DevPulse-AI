"""Process entry point: argument parsing, handler dispatch and safe error rendering."""

import sqlite3
import subprocess
import sys
from pathlib import Path

from ..domain.errors import ProviderError
from ..domain.privacy import Vault
from .commands import gateway, integrate, jobs, mcp, models, project, review, state, verify
from .output import terminal_safe
from .parser import parser

HANDLERS = {
    'init': project.init,
    'review': review.handle,
    'gateway': gateway.handle,
    'memory': project.memory,
    'context': project.context,
    'sessions': state.sessions,
    'cache': state.cache,
    'prune': state.prune,
    'doctor': state.doctor,
    'jobs': jobs.handle,
    'models': models.handle,
    'verify': verify.handle,
    'mcp': mcp.handle,
    'integrate': integrate.handle,
    'rules': lambda args, root: integrate.handle(setattr(args, 'sync_only', True) or args, root),
}


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        root = Path(args.project).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Project must be a directory.')
        if args.command == 'tui':
            from .tui import dashboard

            dashboard(root)
            return 0
        return HANDLERS[args.command](args, root)
    except (KeyboardInterrupt, EOFError):
        print('Stopped.', file=sys.stderr)
        return 130
    except (
        OSError,
        ValueError,
        TypeError,
        sqlite3.Error,
        ProviderError,
        subprocess.SubprocessError,
    ) as exc:
        print('devpulse: ' + terminal_safe(Vault().scrub(str(exc))), file=sys.stderr)
        return 2
