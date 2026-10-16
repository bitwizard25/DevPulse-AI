"""Review command: select execution mode and render the application result."""

from pathlib import Path

from ...bootstrap import make_engine
from ...infrastructure.config import load_config, state_home
from ...infrastructure.state import State
from ..gateway import ensure_gateway, gateway_request
from ..output import emit, render_review, review_exit
from .jobs import wait_for_result


def handle(args, root: Path) -> int:
    if args.detach and (args.direct or args.offline):
        raise ValueError(
            '--detach requires a gateway-managed AI review; remove --offline and --direct.'
        )
    options = {
        'mode': 'offline' if args.offline else 'ai',
        'file': args.file or getattr(args, 'file_pos', None),
        'worktree': args.worktree,
        'no_cache': args.no_cache,
        'chaos': args.chaos,
    }
    if args.direct or args.offline:
        result = make_engine(State(state_home())).review(root, load_config(root), **options)
    else:
        ensure_gateway(state_home())
        job = gateway_request(state_home(), '/jobs', {'project': str(root), **options})
        if args.detach:
            emit(
                job
                if args.json
                else f'Queued job {job["id"]}; inspect it with devpulse jobs show {job["id"]}.',
                args.json,
            )
            return 0
        result = wait_for_result(job['id'])
    render_review(result, args.json)
    return review_exit(result, args.fail_on)
