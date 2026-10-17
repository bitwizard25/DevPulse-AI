"""Process entry point: argument parsing, handler dispatch and safe error rendering."""

import sqlite3
import subprocess
import sys
from pathlib import Path

from ..domain.errors import ProviderError
from ..domain.privacy import Vault
from . import agent as agent_command
from .commands import gateway, integrate, jobs, mcp, models, project, review, state, verify
from .output import terminal_safe
from .parser import parser

HANDLERS = {
    'init': project.init,
    'run': agent_command.run,
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
    'model': models.handle,
    'verify': verify.handle,
    'mcp': mcp.handle,
    'integrate': integrate.handle,
    'rules': lambda args, root: integrate.handle(setattr(args, 'sync_only', True) or args, root),
    'setup': lambda args, root: __import__(
        'devpulse.interfaces.setup', fromlist=['run_setup_wizard']
    ).run_setup_wizard(root),
}


def print_welcome(root: Path):
    from .. import __version__
    from ..infrastructure.config import load_config
    from ..infrastructure.hardware import probe_hardware
    from .output import emit

    hw = probe_hardware()
    config = load_config(root)
    active_model = 'None (offline mode)'
    if config.providers:
        p0 = config.providers[0]
        active_model = f'{p0.model} ({p0.name})'

    emit('==============================================================================')
    emit(f'  DevPulse AI v{__version__} | Task-First Coding Harness & Review Gateway')
    emit('==============================================================================')
    emit(f'  Project:       {root}')
    emit(f'  Active Model:  {active_model}')
    emit(
        f'  Hardware:      {hw.gpu_name} ({hw.vram_gb:.1f} GB VRAM) | {hw.total_ram_gb:.1f} GB RAM ({hw.os_name})'
    )
    emit('------------------------------------------------------------------------------')
    emit('  Quick Commands:')
    emit('    devpulse                     Start or resume a task-first coding session')
    emit('    devpulse run "<task>"         Run one task in the current repository')
    emit('    devpulse review              Run code review & security audit on staged changes')
    emit('    devpulse review --file <f>   Review a specific file in the repository')
    emit('    devpulse verify --file <f>   AST syntax & secret blocker gate (exit code 2)')
    emit('    devpulse models              Profile host hardware & rate Ollama models')
    emit('    devpulse models <name> --select  Select and activate a local Ollama model')
    emit('    devpulse integrate --all     Bridge Claude Code, Google Antigravity & Codex')
    emit('    devpulse mcp                 Launch Model Context Protocol stdio server')
    emit('    devpulse tui                 Open the interactive task session')
    emit('    devpulse --help              Show detailed command arguments')
    emit('==============================================================================')


def main(argv=None) -> int:
    app_parser = parser()
    args = app_parser.parse_args(argv)
    try:
        root = Path(args.project).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Project must be a directory.')
        if not args.command:
            if sys.stdin.isatty():
                return agent_command.run(args, root)
            print_welcome(root)
            return 0
        if args.command == 'tui':
            return agent_command.run(args, root)
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
