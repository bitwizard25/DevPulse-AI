"""Relevance selection and prompt budgeting without filesystem or database dependencies."""

import json
from dataclasses import asdict

from ..domain.models import ProviderConfig
from ..domain.prompts import SYSTEM
from .ports import MemoryIndex, TokenCounter

BUDGET_VERSION = 'context-v1'


class ContextService:
    def __init__(self, index: MemoryIndex, guidance_reader, identity):
        self.index, self.guidance_reader, self.identity = index, guidance_reader, identity

    def __call__(self, root, vault, budget=24000, query='') -> dict:
        guidance = self.guidance_reader(root, vault)
        report = self.index.refresh(root, vault)
        project = self.identity(str(root))
        memory = self.index.search(project, query, kind='memory', limit=8)
        if not memory:
            memory = self.index.first_memory(project, limit=8)
        code = self.index.search(project, query, kind='code', limit=8)
        return {
            'mandatory': guidance['text'],
            'candidates': [asdict(chunk) for chunk in memory + code],
            'sources': guidance['sources'],
            'fingerprint': guidance['fingerprint'] + report.fingerprint,
            'index': {
                'documents': report.documents,
                'chunks': report.chunks,
                'skipped': report.skipped,
            },
        }


class ContextPlanner:
    def __init__(self, counter: TokenCounter):
        self.counter = counter

    def plan(
        self,
        context: dict,
        source: str,
        source_kind: str,
        providers: list[ProviderConfig],
        *,
        byte_budget: int = 24000,
        enforce: bool = True,
    ) -> dict:
        providers = providers or [ProviderConfig()]
        input_limit = min(
            p.context_window_tokens - p.output_tokens - p.safety_tokens for p in providers
        )
        mandatory = context.get('mandatory', context.get('text', ''))

        def prompt(text):
            return json.dumps(
                {'context': text, 'source_kind': source_kind, 'source': source}, ensure_ascii=False
            )

        def tokens(text):
            return self.counter.count(SYSTEM) + self.counter.count(prompt(text))

        if enforce and (tokens(mandatory) > input_limit or len(mandatory.encode()) > byte_budget):
            raise ValueError(
                'Source and project rules exceed the model context budget. Split the review or configure a larger context window.'
            )
        text, selected, omitted = mandatory, [], []
        for chunk in context.get('candidates', []):
            header = f'\n--- {chunk["path"]}:{chunk["start"]}-{chunk["end"]} ---\n'
            body = chunk['text']

            def fits(length, prefix=text + header, candidate_body=body):
                candidate = prefix + candidate_body[:length]
                return len(candidate.encode()) <= byte_budget and (
                    not enforce or tokens(candidate) <= input_limit
                )

            length = len(body)
            if not fits(length):
                low, high = 0, length
                while low < high:
                    middle = (low + high + 1) // 2
                    if fits(middle):
                        low = middle
                    else:
                        high = middle - 1
                length = low
                omitted.append(
                    {
                        'path': chunk['path'],
                        'start': chunk['start'],
                        'reason': 'excerpted to fit budget'
                        if length
                        else 'context budget exhausted',
                    }
                )
            if length:
                excerpt = body[:length]
                text += header + excerpt
                selected.append(
                    {
                        'path': chunk['path'],
                        'kind': chunk['kind'],
                        'start': chunk['start'],
                        'end': min(chunk['end'], chunk['start'] + excerpt.count('\n')),
                        'excerpted': length < len(body),
                    }
                )
        index = dict(context.get('index', {}))
        skipped = index.get('skipped', [])
        index['skipped_count'] = len(skipped)
        index['skipped'] = [item[:500] for item in skipped[:50]]
        metadata = {
            'sources': list(
                dict.fromkeys(context.get('sources', []) + [item['path'] for item in selected])
            ),
            'selected': selected,
            'omitted': omitted,
            'truncated': bool(omitted),
            'budget_bytes': byte_budget,
            'estimated_input_tokens': tokens(text),
            'input_token_limit': input_limit,
            'token_count_exact': self.counter.exact,
            'token_counter': self.counter.name,
            'budget_version': BUDGET_VERSION,
            'inference_budget_enforced': enforce,
            'index': index,
        }
        return {'prompt': prompt(text), 'context': metadata}
