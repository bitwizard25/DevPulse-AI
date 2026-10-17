"""Task-first terminal interaction for the local coding harness."""

import json
import sys
from pathlib import Path

from ..bootstrap import make_agent_runtime, make_agent_session
from ..domain.errors import ProviderError
from ..infrastructure.config import load_config, protected_vault, state_home
from ..infrastructure.files import ProcessLock
from ..infrastructure.state import State
from .output import terminal_safe


def run(args, root: Path) -> int:
    interactive = not getattr(args, 'task', None)
    if interactive and not sys.stdin.isatty():
        raise ValueError('Task mode needs a TTY. Use devpulse run "your task" for automation.')
    state = State(state_home())
    project_id = state.identity(str(root))
    config = load_config(root)
    if not config.providers:
        if not interactive:
            raise ValueError(
                'No model configured. Run devpulse init to choose a local or cloud model.'
            )
        from .setup import run_setup_wizard

        if run_setup_wizard(root):
            return 130
        config = load_config(root)
        if not config.providers:
            print(
                'Offline setup complete. Run `devpulse init --provider ollama` or `--provider openai-compatible` to enable task sessions.'
            )
            return 0
    runtime = make_agent_runtime(state, config)
    vault = protected_vault(config)

    def approve(kind, target, diff):
        mode = runtime.sessions.get(session_id)['permission']
        if mode == 'auto' or (mode == 'edit' and kind == 'write'):
            return True
        if kind == 'write' and getattr(args, 'allow_edits', False):
            return True
        if kind == 'command' and getattr(args, 'allow_commands', False):
            return True
        if not interactive:
            return False
        if kind == 'write':
            print(
                f'\nProposed change: {terminal_safe(vault.scrub(target))}\n'
                f'{terminal_safe(vault.scrub(diff))}'
            )
            prompt = 'Apply this change? [y/N] '
        else:
            print(f'\nCommand requested: {terminal_safe(vault.scrub(target))}')
            prompt = 'Run this command? [y/N] '
        return input(prompt).strip().lower() in ('y', 'yes')

    def on_event(event):
        output = sys.stdout if interactive else sys.stderr
        if event['type'] == 'message' and event['text'] and interactive:
            print('\n' + terminal_safe(event['text']))
        elif event['type'] == 'tool_start':
            details = event['arguments']
            target = details.get('path', details.get('query', details.get('argv', '')))
            print(
                f'\n* {terminal_safe(event["name"])} {terminal_safe(str(target)[:2000])}',
                file=output,
            )
        elif event['type'] == 'tool_end':
            try:
                result = json.loads(event['result'])
                if result.get('status') == 'denied':
                    print('  denied by user', file=output)
                elif result.get('status') == 'written':
                    print(f'  wrote {result.get("path")}', file=output)
                elif result.get('status') == 'completed':
                    print(
                        f'  exit {result.get("exit_code")}\n{terminal_safe(result.get("output", ""))}',
                        file=output,
                    )
                elif result.get('status') in ('clean', 'findings'):
                    print(f'  verification: {result.get("status")}', file=output)
                else:
                    print('  completed', file=output)
            except (ValueError, TypeError):
                print('  completed', file=output)
        elif event['type'] == 'context' and event['omitted_messages']:
            print('  Context compacted; current task and instructions kept.', file=output)

    def create_session(title='Terminal session'):
        metadata = runtime.sessions.create(project_id, title)
        return metadata['id']

    session_id = getattr(args, 'session', None)
    if session_id:
        metadata = runtime.sessions.get(session_id)
        if metadata['project'] != project_id:
            raise ValueError('Agent session belongs to a different project.')
        if metadata['status'] != 'active':
            raise ValueError('Agent session is closed; start a new session.')
    elif getattr(args, 'new', False):
        session_id = create_session()
    else:
        existing = runtime.sessions.latest(project_id)
        session_id = existing['id'] if existing else create_session()

    if getattr(args, 'permissions', None):
        runtime.sessions.set_permission(session_id, args.permissions)

    def session_lock():
        return ProcessLock(state.home / 'agent-locks' / (state.identity(session_id) + '.lock'))

    def execute_task(task):
        with session_lock():
            runtime.sessions.recover(session_id)
            if runtime.sessions.get(session_id)['title'] == 'Terminal session':
                runtime.sessions.set_title(session_id, vault.scrub(task).strip()[:160])
            session = make_agent_session(
                runtime, config, root, session_id, approve, on_event, vault
            )
            context = runtime.context(
                root, vault, budget=config.context_bytes, query=vault.scrub(task)
            )
            return session.run(
                task, root.name, context['mandatory'], references=context['candidates']
            )

    if interactive:
        print(f'DevPulse | {root.name} | {config.providers[0].model} | session {session_id[:8]}')
        print('Describe the outcome you want. Type /help for session commands, /quit to exit.')
        while True:
            try:
                task = input('\n> ').strip()
            except (EOFError, KeyboardInterrupt):
                print('\nSession saved.')
                return 0
            if not task:
                continue
            if task == '/quit':
                print('Session saved.')
                return 0
            if task == '/help':
                print(
                    '/status  session, model and latest turn\n/permissions ask|edit|auto  session access\n/new  start another session\n/clear  delete this session\n/quit  exit'
                )
                continue
            if task == '/status':
                print(f'{session_id} | {config.providers[0].model} ({config.providers[0].name})')
                print(f'Permissions: {runtime.sessions.get(session_id)["permission"]}')
                turns = runtime.sessions.turns(session_id, 1)
                if turns:
                    print(f'Latest turn: {turns[0]["id"]} {turns[0]["status"]}')
                continue
            if task.startswith('/permissions'):
                parts = task.split()
                if len(parts) == 2 and parts[1] in ('ask', 'edit', 'auto'):
                    runtime.sessions.set_permission(session_id, parts[1])
                else:
                    print(
                        'Choose ask (approval per action), edit (automatic project edits), or auto (edits and commands). Commands use your OS access.'
                    )
                print('Permissions: ' + runtime.sessions.get(session_id)['permission'])
                continue
            if task in ('/new', '/clear'):
                with session_lock():
                    if task == '/clear':
                        runtime.sessions.clear(session_id)
                    else:
                        runtime.sessions.close(session_id)
                session_id = create_session()
                print(f'Started session {session_id[:8]}.')
                continue
            try:
                execute_task(task)
            except KeyboardInterrupt:
                print(
                    '\nTurn interrupted and saved. Inspect /status or continue with another prompt.'
                )
            except (ValueError, OSError, ProviderError) as exc:
                print('DevPulse: ' + terminal_safe(vault.scrub(str(exc))), file=sys.stderr)
    else:
        answer = execute_task(' '.join(args.task))
        if getattr(args, 'json', False):
            print(json.dumps({'session_id': session_id, 'message': answer}, ensure_ascii=False))
        else:
            print(terminal_safe(answer))
    return 0
