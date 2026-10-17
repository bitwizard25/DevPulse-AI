"""Pin the active task and instructions; fit optional observations as valid JSON."""

import json

from ..domain.agent_prompts import AGENT_SYSTEM, TASK_BOOTSTRAP


def encoded(value):
    return json.dumps(value, ensure_ascii=True)


def scrub_structure(value, scrub):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [scrub_structure(item, scrub) for item in value]
    if isinstance(value, dict):
        return {key: scrub_structure(item, scrub) for key, item in value.items()}
    return value


def scrub_history(history, scrub):
    """Preserve JSON boundaries and never mistake old tool output for a user goal."""
    safe = []
    for item in history:
        if item['role'] == 'user':
            safe.append({'role': 'user', 'content': scrub(item['content'])})
        elif item['role'] == 'assistant':
            try:
                content = encoded(scrub_structure(json.loads(item['content']), scrub))
            except (ValueError, RecursionError):
                continue
            safe.append({'role': 'assistant', 'content': content})
    return safe


def bounded_result(value, budget):
    """Excerpt string leaves without cutting JSON syntax, fingerprints or short metadata."""

    def excerpt(item, limit):
        if isinstance(item, str) and len(item) > max(80, limit):
            return item[:limit] + ' [excerpted]'
        if isinstance(item, list):
            return [excerpt(child, limit) for child in item[:20]]
        if isinstance(item, dict):
            return {key: excerpt(child, limit) for key, child in list(item.items())[:40]}
        return item

    if len(encoded(value)) <= budget:
        return value, False
    low, high, best = 0, budget, {'status': 'omitted', 'reason': 'context budget'}
    while low <= high:
        middle = (low + high) // 2
        shortened = excerpt(value, middle)
        candidate = (
            {**shortened, '_truncated': True}
            if isinstance(shortened, dict)
            else {'_truncated': True, 'result': shortened}
        )
        if len(encoded(candidate)) <= budget:
            best, low = candidate, middle + 1
        else:
            high = middle - 1
    return best, True


class AgentContext:
    def __init__(self, budget_bytes):
        self.budget = budget_bytes

    def build(self, task, project, guidance, tools, history, observations, references=()):
        messages = [
            {'role': 'system', 'content': AGENT_SYSTEM},
            {'role': 'user', 'content': 'Tool catalog: ' + encoded(tools)},
            {
                'role': 'user',
                'content': TASK_BOOTSTRAP.format(
                    project_name=project, task=task, guidance=guidance
                ),
            },
        ]
        if len(encoded(messages)) > self.budget:
            raise ValueError(
                'Task, repository guidance and tool catalog exceed the model context budget; configure a larger window or curate instructions.'
            )
        omitted = 0

        def fit_optional(content, budget, *, required_key=None):
            # Tool evidence is JSON embedded in a message string. Fit the fully
            # serialized request, including that second layer of quote escaping.
            low, high, best = 0, max(0, budget), None
            while low <= high:
                middle = (low + high) // 2
                value, truncated = bounded_result(content, middle)
                if required_key and (
                    not isinstance(value, dict)
                    or not isinstance(value.get(required_key), list)
                    or not value[required_key]
                    or value[required_key][-1].get('tool_call_id')
                    != content[required_key][-1].get('tool_call_id')
                ):
                    high = middle - 1
                    continue
                candidate = {'role': 'user', 'content': encoded(value)}
                if len(encoded([*messages, candidate])) <= self.budget:
                    best = candidate, truncated
                    low = middle + 1
                else:
                    high = middle - 1
            return best

        def append_optional(content, budget):
            nonlocal omitted
            best = fit_optional(content, budget)
            if best:
                messages.append(best[0])
                omitted += int(best[1])
            else:
                omitted += 1

        # Compact earlier sessions to goals and final answers, not raw source/tool transcripts.
        if history:
            summaries = []
            for item in history[-20:]:
                if item['role'] == 'user':
                    text = item['content']
                    if '\nTask:\n' in text:
                        text = text.split('\nTask:\n', 1)[1].split('\nRepository context', 1)[0]
                    summaries.append({'goal': text[:300]})
                elif item['role'] == 'assistant':
                    try:
                        value = json.loads(item['content'])
                        if value.get('final'):
                            summaries.append({'answer': value['message'][:300]})
                    except (ValueError, TypeError, KeyError):
                        continue
            remaining = self.budget - len(encoded(messages))
            if remaining > 700:
                append_optional(
                    {'prior_session_excerpts': summaries[-4:]}, min(1000, remaining // 4)
                )
            omitted += len(history)

        if observations:
            remaining = self.budget - len(encoded(messages))
            # Keep the newest result even when a batch of older outputs exhausts
            # a small model's context. Add older results only when they also fit.
            retained = False
            window = observations[-12:]
            for start in range(len(window)):
                selected = window[start:]
                results = [
                    {'tool_call_id': item['id'], 'tool': item['name'], 'result': item['result']}
                    for item in selected
                ]
                ledger = [
                    {
                        'id': item['id'],
                        'tool': item['name'],
                        **{
                            key: item['result'][key]
                            for key in ('path', 'status', 'exit_code', 'error')
                            if key in item['result']
                        },
                    }
                    for item in selected
                ]
                best = fit_optional(
                    {'completed_tool_activity': ledger, 'tool_results': results},
                    remaining - 80,
                    required_key='tool_results',
                )
                if best:
                    messages.append(best[0])
                    omitted += int(best[1]) + start
                    retained = True
                    break
            if not retained:
                raise ValueError(
                    'Latest tool result cannot fit the configured context budget; use a larger model context or reduce repository guidance.'
                )
            omitted += max(0, len(observations) - len(window))
        elif references:
            remaining = self.budget - len(encoded(messages))
            if remaining > 300:
                append_optional({'retrieved_references': list(references)[:8]}, remaining - 80)

        return messages, {
            'type': 'context',
            'estimated_input_tokens': (len(encoded(messages)) + 1) // 2,
            'input_token_limit': (self.budget + 1) // 2,
            'serialized_bytes': len(encoded(messages)),
            'token_count_exact': False,
            'omitted_messages': omitted,
        }
