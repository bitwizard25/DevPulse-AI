"""Project onboarding and explicit memory commands."""

import json
from dataclasses import asdict
from pathlib import Path

from ...bootstrap import make_engine
from ...infrastructure.config import load_config, protected_vault, state_home
from ...infrastructure.memory import SQLiteMemoryIndex
from ...infrastructure.project import add_memory, initialize, read_memory
from ...infrastructure.state import State
from ..output import emit


def init(args, root: Path) -> int:
    if args.provider == 'openai-compatible' and args.model == 'qwen2.5-coder:7b':
        raise ValueError('Provide --model with an exact model name for the cloud endpoint.')
    created = initialize(
        root,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
    )
    emit(
        'Created ' + ', '.join(created)
        if created
        else 'Already initialized; existing files preserved.'
    )
    emit(
        'Edit .devpulse/RULES.md and MEMORY.md, then run devpulse review --offline or configure a model.'
    )
    return 0


def memory(args, root: Path) -> int:
    vault = protected_vault(load_config(root))
    if args.action in ('search', 'reindex'):
        state = State(state_home())
        index = SQLiteMemoryIndex(state)
        report = (
            index.rebuild(root, vault) if args.action == 'reindex' else index.refresh(root, vault)
        )
        if args.action == 'reindex':
            emit(asdict(report), True)
        else:
            if not args.text:
                raise ValueError('Supply a memory search query.')
            results = [
                asdict(chunk)
                for chunk in index.search(
                    state.identity(str(root)), args.text, kind='memory', limit=args.limit
                )
            ]
            if args.json:
                emit(results, True)
            else:
                for chunk in results:
                    emit(f'{chunk["path"]}:{chunk["start"]}-{chunk["end"]}\n{chunk["text"]}')
    elif args.action == 'add':
        if args.text is None:
            raise ValueError('Supply a decision: devpulse memory add "Use parameterized SQL."')
        add_memory(root, args.text, vault)
        emit('Added a redacted decision to .devpulse/MEMORY.md.')
    else:
        emit(read_memory(root, vault))
    return 0


def context(args, root: Path) -> int:
    state = State(state_home())
    engine = make_engine(state)
    config = load_config(root)
    if args.file or args.worktree:
        snapshot = engine.prepare(root, config, file=args.file, worktree=args.worktree)
        value = {'context': snapshot.context, 'input': json.loads(snapshot.prompt)}
    else:
        guidance = engine.context_reader(
            root, protected_vault(config), budget=config.context_bytes, query=args.query
        )
        value = engine.planner.plan(
            guidance, '', 'preview', config.providers, byte_budget=config.context_bytes
        )
    emit(value, args.json)
    return 0
