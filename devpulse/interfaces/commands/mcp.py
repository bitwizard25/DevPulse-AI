"""Model Context Protocol (MCP) stdio server interface."""

import json
import sys
from pathlib import Path

from ...application.mcp import McpServer
from ...bootstrap import make_engine
from ...domain.mcp import McpRequest
from ...infrastructure.config import load_config, state_home
from ...infrastructure.hardware import probe_hardware
from ...infrastructure.memory import SQLiteMemoryIndex
from ...infrastructure.state import State


def handle(args, root: Path) -> int:
    state = State(state_home())
    engine = make_engine(state)
    memory_index = SQLiteMemoryIndex(state)

    server = McpServer(
        root=root,
        engine_factory=lambda: engine,
        memory_index_factory=lambda: memory_index,
        hardware_prober=probe_hardware,
        config_reader=lambda: load_config(root),
    )

    # If run interactively in a terminal, print friendly instructions to stderr
    if sys.stdin.isatty():
        sys.stderr.write(
            'DevPulse Model Context Protocol (MCP) Server\n'
            'Listening on stdio for JSON-RPC messages from coding agents (Claude Code, Google Antigravity, Codex).\n'
            'To connect your coding agents automatically, run:\n'
            '  devpulse integrate --all\n'
            'Press Ctrl+C to exit.\n'
        )
        sys.stderr.flush()

    # Stdio loop for MCP JSON-RPC
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            req = McpRequest.from_dict(payload)
            res = server.handle_request(req)
            # Notifications (like notifications/initialized) return None result
            if res.result is not None or res.error is not None:
                sys.stdout.write(json.dumps(res.to_dict()) + '\n')
                sys.stdout.flush()
        except Exception as exc:
            err_res = {
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700, 'message': f'Parse error: {str(exc)}'},
            }
            sys.stdout.write(json.dumps(err_res) + '\n')
            sys.stdout.flush()

    return 0
