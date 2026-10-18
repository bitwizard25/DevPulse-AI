"""Provider-neutral decoding constraints; runtime validation remains authoritative."""

from copy import deepcopy

from .agent import MAX_TOOL_CALLS
from .agent_tools import REVIEW_PROJECT_TOOL, TOOL_SPECS


def decision_schema() -> dict:
    variants = []
    for tool in [*TOOL_SPECS, REVIEW_PROJECT_TOOL]:
        variants.append(
            {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                    'name': {'type': 'string', 'const': tool['name']},
                    'arguments': deepcopy(tool['inputSchema']),
                },
                'required': ['id', 'name', 'arguments'],
                'additionalProperties': False,
            }
        )
    return {
        'type': 'object',
        'properties': {
            'message': {'type': 'string', 'maxLength': 12000},
            'tool_calls': {
                'type': 'array',
                'maxItems': MAX_TOOL_CALLS,
                'items': {'anyOf': variants},
            },
            'final': {'type': 'boolean'},
        },
        'required': ['message', 'tool_calls', 'final'],
        'additionalProperties': False,
    }
