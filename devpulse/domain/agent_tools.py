"""Provider-independent tool schemas and argument validation."""


def spec(name, description, properties, required=()):
    return {
        'name': name,
        'description': description,
        'inputSchema': {
            'type': 'object',
            'properties': properties,
            'required': list(required),
            'additionalProperties': False,
        },
    }


TEXT = {'type': 'string'}
PATH = {'type': 'string', 'description': 'Project-relative path'}
FINGERPRINT = {'type': 'string', 'description': 'Fingerprint from the latest read_file'}
TOOL_SPECS = [
    spec('list_files', 'Discover project files, respecting Git ignores.', {'query': TEXT}),
    spec(
        'read_file',
        'Read source lines. Check truncated and use further ranges as needed.',
        {
            'path': PATH,
            'start_line': {'type': 'integer', 'minimum': 1},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
        },
        ['path'],
    ),
    spec('search_text', 'Find literal text with file/line provenance.', {'query': TEXT}, ['query']),
    spec(
        'edit_file',
        'Replace one exact text match, preserving the rest of the file. Read first.',
        {
            'path': PATH,
            'old_text': TEXT,
            'new_text': TEXT,
            'expected_fingerprint': FINGERPRINT,
        },
        ['path', 'old_text', 'new_text', 'expected_fingerprint'],
    ),
    spec(
        'write_file',
        'Create a file. Replacing an existing file requires a full, unredacted read.',
        {
            'path': PATH,
            'content': TEXT,
            'expected_fingerprint': FINGERPRINT,
        },
        ['path', 'content'],
    ),
    spec(
        'run_command',
        'Run an argv command in the project. No implicit shell. Output/time are bounded.',
        {
            'argv': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 24},
            'timeout': {'type': 'integer', 'minimum': 1, 'maximum': 300},
        },
        ['argv'],
    ),
    spec(
        'verify_file',
        'Check Python syntax and potential secrets without running source.',
        {'path': PATH},
        ['path'],
    ),
]


def validate_arguments(name: str, arguments: dict):
    definition = next((item['inputSchema'] for item in TOOL_SPECS if item['name'] == name), None)
    if definition is None:
        raise ValueError('Unknown tool.')
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object.')
    properties = definition['properties']
    if set(arguments) - set(properties) or set(definition['required']) - set(arguments):
        raise ValueError('Tool arguments have missing or unknown fields; follow inputSchema.')
    for key, value in arguments.items():
        rule = properties[key]
        valid = (
            rule['type'] == 'string'
            and isinstance(value, str)
            or rule['type'] == 'integer'
            and type(value) is int
            or rule['type'] == 'array'
            and isinstance(value, list)
            and rule['minItems'] <= len(value) <= rule['maxItems']
            and all(isinstance(part, str) for part in value)
        )
        if not valid or (
            type(value) is int
            and not rule.get('minimum', value) <= value <= rule.get('maximum', value)
        ):
            raise ValueError(f'Invalid argument: {key}.')
