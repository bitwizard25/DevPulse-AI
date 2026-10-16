"""Command arguments only; no business logic or I/O."""

import argparse

from .. import __version__


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(
        prog='devpulse', description='Local-first code review, project memory and gateway.'
    )
    app.add_argument('--version', action='version', version=__version__)
    app.add_argument(
        '--project', default='.', help='Project directory (default: current directory).'
    )
    commands = app.add_subparsers(dest='command', required=False)
    init = commands.add_parser(
        'init', help='Create config, rules, memory and a review skill; preserve existing files.'
    )
    init.add_argument(
        '--provider', choices=['ollama', 'openai-compatible', 'offline'], default='ollama'
    )
    init.add_argument(
        '--model', default='qwen2.5-coder:7b', help='Exact installed/provider model name.'
    )
    init.add_argument('--base-url')
    init.add_argument('--api-key-env', default='OPENAI_API_KEY')
    review = commands.add_parser(
        'review', help='Review staged diff by default; never edit target files.'
    )
    source = review.add_mutually_exclusive_group()
    source.add_argument('--file', help='Review a whole file within the project.')
    source.add_argument('--worktree', action='store_true', help='Review tracked unstaged changes.')
    source.add_argument('--staged', action='store_true', help='Review staged changes (default).')
    review.add_argument(
        'file_pos',
        nargs='?',
        metavar='FILE',
        help='Target file to review directly (e.g. devpulse review cli.py).',
    )
    review.add_argument(
        '--offline', action='store_true', help='Run deterministic checks without an LLM or network.'
    )
    review.add_argument(
        '--direct', action='store_true', help='Run in this process without the shared gateway.'
    )
    review.add_argument(
        '--detach', action='store_true', help='Submit a durable gateway job and return its ID.'
    )
    review.add_argument('--no-cache', action='store_true')
    review.add_argument(
        '--chaos', action='store_true', help='Simulate first-provider outage to exercise failover.'
    )
    review.add_argument('--json', action='store_true')
    review.add_argument('--fail-on', choices=['error', 'warning', 'none'], default='error')
    gateway = commands.add_parser('gateway', help='Manage the shared loopback gateway.')
    gateway.add_argument(
        'action', choices=['start', 'run', 'status', 'stop'], default='status', nargs='?'
    )
    memory = commands.add_parser(
        'memory', help='Read or explicitly add a redacted project decision.'
    )
    memory.add_argument(
        'action', choices=['show', 'add', 'search', 'reindex'], default='show', nargs='?'
    )
    memory.add_argument('text', nargs='?')
    memory.add_argument('--json', action='store_true')
    memory.add_argument('--limit', type=int, default=8)
    context = commands.add_parser(
        'context', help='Preview redacted project context used in reviews.'
    )
    context.add_argument('--json', action='store_true')
    preview = context.add_mutually_exclusive_group()
    preview.add_argument('--file')
    preview.add_argument('--worktree', action='store_true')
    preview.add_argument('--query', default='')
    sessions = commands.add_parser(
        'sessions', help='Show persisted session metadata for this project.'
    )
    sessions.add_argument('--json', action='store_true')
    sessions.add_argument('--limit', type=int, default=20)
    jobs = commands.add_parser('jobs', help='Inspect and control durable gateway review jobs.')
    jobs.add_argument('action', choices=['list', 'show', 'wait', 'cancel', 'retry'])
    jobs.add_argument('id', nargs='?')
    jobs.add_argument('--json', action='store_true')
    jobs.add_argument('--limit', type=int, default=20)
    jobs.add_argument('--timeout', type=float)
    jobs.add_argument('--fail-on', choices=['error', 'warning', 'none'], default='error')
    cache = commands.add_parser('cache', help='Manage local review cache.')
    cache.add_argument('action', choices=['clear'])
    prune = commands.add_parser(
        'prune', help='Remove completed session metadata older than the retention window.'
    )
    prune.add_argument('--days', type=int, default=30)
    commands.add_parser(
        'doctor', help='Inspect installation and provider configuration without inference.'
    )
    models = commands.add_parser(
        'models',
        aliases=['model'],
        help='Profile system hardware, rate Ollama models by fit, and select the active model.',
    )
    models.add_argument('model', nargs='?', help='Specific model name or pattern to inspect.')
    models.add_argument(
        '--select', action='store_true', help='Set this model as active in .devpulse/config.json.'
    )
    models.add_argument('--base-url', help='Ollama API base URL.')
    models.add_argument('--json', action='store_true')
    verify = commands.add_parser(
        'verify',
        help='Deterministic AST syntax and secret verification gate (exit code 2 on failure).',
    )
    verify.add_argument('--file', help='Target file to verify.')
    verify.add_argument(
        'file_pos',
        nargs='?',
        metavar='FILE',
        help='Target file to verify (e.g. devpulse verify bootstrap.py).',
    )
    verify.add_argument('--code', help='Code snippet string to verify.')
    verify.add_argument('--json', action='store_true')
    commands.add_parser(
        'mcp',
        help='Run Model Context Protocol (MCP) stdio server for Claude Code, Antigravity, and Codex.',
    )
    integrate = commands.add_parser(
        'integrate',
        help='Configure DevPulse MCP server and lifecycle hooks for Claude Code, Antigravity, and Codex.',
    )
    group = integrate.add_mutually_exclusive_group()
    group.add_argument(
        '--all',
        action='store_true',
        help='Configure all supported coding agents (default).',
    )
    group.add_argument(
        '--claude',
        action='store_true',
        help='Configure Claude Code MCP and PreToolUse hook.',
    )
    group.add_argument(
        '--antigravity',
        action='store_true',
        help='Configure Google Antigravity .agents/mcp_config.json.',
    )
    group.add_argument(
        '--codex',
        action='store_true',
        help='Configure OpenAI Codex CLI .codex/config.toml.',
    )
    group.add_argument(
        '--sync-only',
        action='store_true',
        help='Sync .devpulse/RULES.md to CLAUDE.md and AGENTS.md only.',
    )
    integrate.add_argument('--json', action='store_true')
    rules = commands.add_parser(
        'rules', help='Synchronize project rules to CLAUDE.md and AGENTS.md.'
    )
    rules.add_argument('action', choices=['sync'], default='sync', nargs='?')
    rules.add_argument('--json', action='store_true')
    commands.add_parser('setup', help='Run interactive guided setup wizard.')
    commands.add_parser('tui', help='Open a small interactive terminal dashboard.')
    for sub in set(commands.choices.values()):
        sub.add_argument('--project', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return app
