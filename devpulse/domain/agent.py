"""Validated decisions made by the task-oriented coding agent."""

import json
from dataclasses import dataclass

MAX_AGENT_OUTPUT = 65536
MAX_TOOL_CALLS = 4


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class AgentDecision:
    message: str
    tool_calls: tuple[ToolCall, ...]
    final: bool

    @classmethod
    def parse(cls, raw: str) -> 'AgentDecision':
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_AGENT_OUTPUT:
            raise ValueError('Agent response is empty or exceeds 64 KB.')
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            raise ValueError('Agent returned malformed decision JSON.') from None
        if not isinstance(value, dict) or set(value) != {'message', 'tool_calls', 'final'}:
            raise ValueError('Agent decision must contain message, tool_calls and final only.')
        message, calls, final = value['message'], value['tool_calls'], value['final']
        if not isinstance(message, str) or len(message) > 12000:
            raise ValueError('Agent message must be a string of at most 12 KB.')
        if type(final) is not bool or not isinstance(calls, list) or len(calls) > MAX_TOOL_CALLS:
            raise ValueError('Agent decision has invalid final flag or too many tool calls.')
        parsed = []
        for call in calls:
            if (
                not isinstance(call, dict)
                or set(call) != {'id', 'name', 'arguments'}
                or not isinstance(call['id'], str)
                or not call['id']
                or len(call['id']) > 64
                or not isinstance(call['name'], str)
                or not isinstance(call['arguments'], dict)
            ):
                raise ValueError('Agent tool call has an invalid shape.')
            parsed.append(ToolCall(call['id'], call['name'], call['arguments']))
        if len({call.id for call in parsed}) != len(parsed):
            raise ValueError('Tool call IDs must be unique within a decision.')
        if final and parsed:
            raise ValueError('A final agent response cannot also request tools.')
        if not final and not parsed:
            raise ValueError('A non-final agent response must request at least one tool.')
        return cls(message, tuple(parsed), final)
