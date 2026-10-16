"""Gateway lifecycle commands."""

from pathlib import Path

from ...infrastructure.config import state_home
from ...infrastructure.state import State
from ..gateway import Gateway, ensure_gateway, gateway_request
from ..output import emit


def handle(args, root: Path) -> int:
    home = state_home()
    if args.action == 'run':
        with Gateway(State(home)) as gateway:
            emit(f'Gateway listening on 127.0.0.1:{gateway.port}; Ctrl+C stops it.')
            gateway.serve()
    elif args.action == 'start':
        emit(ensure_gateway(home), True)
    elif args.action == 'stop':
        emit(gateway_request(home, '/shutdown', {}), True)
    else:
        emit(gateway_request(home, '/health'), True)
    return 0
