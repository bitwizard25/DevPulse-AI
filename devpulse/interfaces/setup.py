"""Interactive setup wizard and main interactive launcher for DevPulse AI."""

from pathlib import Path

from ..domain.hardware import FitTier, rate_models
from ..infrastructure.config import load_config, state_home
from ..infrastructure.hardware import fetch_models, probe_hardware
from ..infrastructure.integrate import integrate_all
from ..infrastructure.project import initialize, set_model
from .output import emit


def run_setup_wizard(root: Path) -> int:
    profile = probe_hardware()

    emit('==============================================================================')
    emit('  DevPulse AI — Interactive Project Setup')
    emit('==============================================================================')
    emit(f'  Project:   {root}')
    emit(
        f'  Hardware:  {profile.gpu_name} ({profile.vram_gb:.1f} GB VRAM) | {profile.total_ram_gb:.1f} GB RAM ({profile.os_name})'
    )
    emit('------------------------------------------------------------------------------')
    emit('Step 1: Choose your review engine:')
    emit('  [1] [Offline] Local Mode (Syntax, Security & Secret Scrubber - No LLM required)')
    emit('  [2] [Ollama]  Local AI (100% private offline models running on your hardware)')
    emit('  [3] [Cloud]   OpenAI-compatible endpoint (BYOK)')

    try:
        choice = input('\nChoice [1-3, default 1]: ').strip()
    except (EOFError, KeyboardInterrupt):
        emit('\nSetup cancelled.')
        return 130

    chosen_provider = 'offline'
    chosen_model = 'offline'
    base_url = None
    api_key_env = 'OPENAI_API_KEY'

    if choice == '2':
        chosen_provider = 'ollama'
        base_url = 'http://127.0.0.1:11434'
        all_models = fetch_models(base_url)
        ratings = rate_models(profile, all_models)
        top_ratings = ratings[:4]

        emit('\nStep 1b: Recommended models for your hardware:')
        for idx, r in enumerate(top_ratings, 1):
            tier_str = '100% GPU VRAM' if r.tier == FitTier.FIT_VRAM else 'System RAM / CPU'
            emit(
                f'  [{idx}] {r.spec.name:<22} ({tier_str:<15} ~{r.predicted_tps:>4.1f} t/s, IQ {r.spec.coding_iq})'
            )

        try:
            m_choice = input(
                f'\nSelect model [1-{len(top_ratings)} or enter model name, default 1]: '
            ).strip()
        except (EOFError, KeyboardInterrupt):
            emit('\nSetup cancelled.')
            return 130

        if m_choice in ('1', '2', '3', '4') and int(m_choice) <= len(top_ratings):
            chosen_model = top_ratings[int(m_choice) - 1].spec.name
        elif m_choice:
            chosen_model = m_choice
        else:
            chosen_model = top_ratings[0].spec.name if top_ratings else 'qwen2.5-coder:7b'

    elif choice == '3':
        chosen_provider = 'openai-compatible'
        try:
            chosen_model = (
                input('\nEnter model name (e.g. gpt-4o-mini, deepseek-chat): ').strip()
                or 'gpt-4o-mini'
            )
            base_url = (
                input('Enter API base URL [default https://api.openai.com/v1]: ').strip()
                or 'https://api.openai.com/v1'
            )
            api_key_env = (
                input('Enter environment variable for API key [default OPENAI_API_KEY]: ').strip()
                or 'OPENAI_API_KEY'
            )
        except (EOFError, KeyboardInterrupt):
            emit('\nSetup cancelled.')
            return 130

    # Initialize the project files
    initialize(
        root,
        provider=chosen_provider,
        model=chosen_model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    emit(f'\n[+] Project initialized with {chosen_provider} ({chosen_model}).')

    # Step 2: Agent Ecosystem Integration
    emit('\nStep 2: Coding Agent Bridges')
    emit('Connect DevPulse MCP Server & Compiler Gate to Claude Code, Antigravity & Codex?')
    try:
        agent_choice = input('Configure agent bridges? [Y/n, default Y]: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        emit('\nSetup cancelled.')
        return 130

    if agent_choice in ('', 'y', 'yes'):
        files = integrate_all(root)
        emit('[+] Configured agent bridges:')
        for f in files:
            rel = Path(f).relative_to(root) if Path(f).is_relative_to(root) else f
            emit(f'    {rel}')

    emit('\n==============================================================================')
    emit('  [+] DevPulse AI setup complete! What next:')
    emit('    - Run code review:    devpulse review')
    emit('    - Check model fit:    devpulse models')
    emit('    - Verify file syntax: devpulse verify --file <filename>')
    emit('==============================================================================\n')
    return 0


def run_interactive_menu(root: Path) -> int:
    from .. import __version__
    from ..bootstrap import make_engine
    from ..infrastructure.state import State
    from .commands import models, verify
    from .output import render_review

    while True:
        config = load_config(root)
        # If not yet configured with providers or missing RULES.md, offer setup wizard directly
        if (
            not (root / '.devpulse/RULES.md').exists()
            or not (root / '.devpulse/config.json').exists()
        ):
            return run_setup_wizard(root)

        profile = probe_hardware()
        active_model = 'None (offline mode)'
        if config.providers:
            p0 = config.providers[0]
            active_model = f'{p0.model} ({p0.kind})'

        emit('==============================================================================')
        emit(f'  DevPulse AI v{__version__} | Local Code Review, Gate & Agent Co-Processor')
        emit('==============================================================================')
        emit(f'  Project:       {root}')
        emit(f'  Active Model:  {active_model}')
        emit(
            f'  Hardware:      {profile.gpu_name} ({profile.vram_gb:.1f} GB VRAM) | {profile.total_ram_gb:.1f} GB RAM ({profile.os_name})'
        )
        emit('------------------------------------------------------------------------------')
        emit('  What would you like to do?')
        emit('    [1] Run code review (file or staged changes)')
        emit('    [2] Run offline deterministic checks (syntax & secrets)')
        emit('    [3] Select / inspect AI models')
        emit('    [4] Verify a file (Compiler-as-a-Judge gate)')
        emit('    [5] Connect coding agents (Claude / Antigravity / Codex)')
        emit('    [6] Run setup wizard again')
        emit('    [q] Exit')
        emit('------------------------------------------------------------------------------')

        try:
            choice = input('Choice [1-6, q]: ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            emit('\nGoodbye.')
            return 0

        if choice in ('q', 'quit', 'exit'):
            emit('Goodbye.')
            return 0
        elif choice == '1':
            try:
                target = input(
                    '\nEnter file to review, or press Enter for entire codebase (type "staged" for git diff): '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                target = ''
            if not target or target.lower() in ('all', '.', '*', 'entire', 'project'):
                target = 'all'
            elif target.lower() == 'staged':
                target = None

            emit('\nRunning code review...')
            try:
                engine = make_engine(State(state_home()))
                res = engine.review(root, load_config(root), mode='ai', file=target)
                render_review(res)
            except Exception as exc:
                emit(f'Review error: {str(exc)}')
            input('\nPress Enter to return to menu...')
        elif choice == '2':
            try:
                target = input(
                    '\nEnter file for offline checks, or press Enter for entire codebase (type "staged" for git diff): '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                target = ''
            if not target or target.lower() in ('all', '.', '*', 'entire', 'project'):
                target = 'all'
            elif target.lower() == 'staged':
                target = None

            emit('\nRunning offline deterministic checks (syntax & secrets)...')
            try:
                engine = make_engine(State(state_home()))
                res = engine.review(root, load_config(root), mode='offline', file=target)
                render_review(res)
            except Exception as exc:
                emit(f'Offline review error: {str(exc)}')
            input('\nPress Enter to return to menu...')
        elif choice == '3':
            emit('\nModel Profiler & Selection:')
            models.handle(
                type(
                    'Args', (), {'model': None, 'select': False, 'base_url': None, 'json': False}
                )(),
                root,
            )
            try:
                m_pick = input(
                    '\nEnter model name to activate (or press Enter to return): '
                ).strip()
                if m_pick:
                    set_model(root, m_pick)
                    emit(f"[+] Active model set to '{m_pick}'")
                    config = load_config(root)
                    if config.providers:
                        active_model = f'{config.providers[0].model} ({config.providers[0].kind})'
            except (EOFError, KeyboardInterrupt):
                pass
            input('\nPress Enter to return to menu...')
        elif choice == '4':
            try:
                target = input(
                    '\nEnter file to verify, or press Enter for entire codebase: '
                ).strip()
                if not target:
                    target = 'all'
                verify.handle(
                    type(
                        'Args',
                        (),
                        {
                            'file': target,
                            'file_pos': None,
                            'all': False,
                            'code': None,
                            'json': False,
                        },
                    )(),
                    root,
                )
            except (EOFError, KeyboardInterrupt):
                pass
            input('\nPress Enter to return to menu...')
        elif choice == '5':
            emit('\nConfiguring bridges for Claude Code, Antigravity, and Codex...')
            files = integrate_all(root)
            for f in files:
                rel = Path(f).relative_to(root) if Path(f).is_relative_to(root) else f
                emit(f'  configured: {rel}')
            emit('[+] Agent bridges configured.')
            input('\nPress Enter to return to menu...')
        elif choice == '6':
            run_setup_wizard(root)
            config = load_config(root)
            if config.providers:
                active_model = f'{config.providers[0].model} ({config.providers[0].kind})'
        else:
            emit('Invalid choice. Enter 1-6 or q.')
