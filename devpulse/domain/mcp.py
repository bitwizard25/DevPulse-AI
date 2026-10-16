"""Domain representations for Model Context Protocol (MCP) JSON-RPC 2.0 messages."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpRequest:
    method: str
    id: Any = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'McpRequest':
        return cls(
            method=data.get('method', ''),
            id=data.get('id'),
            params=data.get('params') or {},
        )


@dataclass
class McpResponse:
    id: Any
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {'jsonrpc': '2.0', 'id': self.id}
        if self.error is not None:
            out['error'] = self.error
        else:
            out['result'] = self.result if self.result is not None else {}
        return out


MCP_PROTOCOL_VERSION = '2024-11-05'

MCP_SERVER_INFO = {
    'name': 'devpulse',
    'version': '0.2.0',
}

MCP_TOOLS = [
    {
        'name': 'devpulse_review',
        'description': 'Run a vendor-agnostic security audit and code review on files or git diffs with zero-retention secret scrubbing and project rule enforcement.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'file': {'type': 'string', 'description': 'Specific relative file path to review.'},
                'staged': {
                    'type': 'boolean',
                    'description': 'Review staged git changes (default true if no file specified).',
                },
                'worktree': {
                    'type': 'boolean',
                    'description': 'Review unstaged tracked git changes.',
                },
                'mode': {
                    'type': 'string',
                    'enum': ['ai', 'offline'],
                    'description': "Review mode: 'ai' (LLM review) or 'offline' (deterministic syntax/security checks only).",
                },
            },
        },
    },
    {
        'name': 'devpulse_verify',
        'description': 'Deterministic AST syntax verification and secret scrubber gate (Compiler-as-a-Judge). Returns errors or passes.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string', 'description': 'Source code string to verify.'},
                'file': {'type': 'string', 'description': 'Relative file path to verify.'},
            },
        },
    },
    {
        'name': 'devpulse_search_memory',
        'description': 'Search indexed project memory, decisions, rules, and codebase context with provenance.',
        'inputSchema': {
            'type': 'object',
            'required': ['query'],
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Search term or natural language query.',
                },
                'limit': {
                    'type': 'integer',
                    'default': 8,
                    'description': 'Maximum number of relevant chunks to return.',
                },
            },
        },
    },
    {
        'name': 'devpulse_hardware_profile',
        'description': 'Inspect host system hardware (RAM, VRAM, GPU) and rate compatible local Ollama coding models.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'base_url': {
                    'type': 'string',
                    'description': 'Ollama base URL (default http://127.0.0.1:11434).',
                }
            },
        },
    },
]

MCP_RESOURCES = [
    {
        'uri': 'devpulse://rules',
        'name': 'Project Rules',
        'description': 'Project architectural and coding rules from .devpulse/RULES.md',
        'mimeType': 'text/markdown',
    },
    {
        'uri': 'devpulse://memory',
        'name': 'Project Memory',
        'description': 'Project architectural decisions and conventions from .devpulse/MEMORY.md',
        'mimeType': 'text/markdown',
    },
]
