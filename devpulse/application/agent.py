"""Bounded model/tool orchestration for task-first terminal sessions."""

import json
import time
from typing import Callable, Protocol

from ..domain.agent import AgentDecision, ToolCall
from ..domain.agent_intent import is_read_only_project_review, requests_project_review
from ..domain.agent_prompts import AGENT_SYSTEM
from ..domain.agent_tools import validate_arguments
from ..domain.errors import ProviderError
from .agent_completion import CompletionGate
from .agent_context import AgentContext, bounded_result, scrub_history, scrub_structure

MAX_TURNS = 12
MAX_TOOL_RESULT_BYTES = 32000


class AgentModel(Protocol):
    def __call__(self, messages: list[dict]) -> str: ...


class ToolRunner(Protocol):
    def describe(self) -> list[dict]: ...
    def execute(self, name: str, arguments: dict) -> dict: ...


class AgentSessionStore(Protocol):
    def messages(self, session_id: str) -> list[dict]: ...
    def append(self, session_id: str, role: str, content: str): ...
    def begin_turn(self, session_id: str, task: str) -> str: ...
    def finish_turn(self, turn_id: str, status: str, *, summary=None, error=None): ...
    def begin_action(self, turn_id: str, call_id: str, name: str): ...
    def finish_action(self, turn_id: str, call_id: str, result: dict): ...


class AgentModelRouter:
    """Use configured providers in order and persist transient-failure circuits."""

    def __init__(self, providers, transport, circuits=None, clock=None):
        self.providers, self.transport = providers, transport
        self.circuits, self.clock = circuits, clock
        self.failures: dict[str, tuple[int, float]] = {}

    def _now(self):
        return self.clock.now() if self.clock else time.time()

    def _read(self, key):
        return self.circuits.read(key) if self.circuits else self.failures.get(key, (0, 0))

    def _write(self, key, failures, opened_until):
        if self.circuits:
            self.circuits.write(key, failures, opened_until)
        else:
            self.failures[key] = (failures, opened_until)

    def __call__(self, messages: list[dict]) -> str:
        if not self.providers:
            raise ProviderError('No AI provider is configured. Run devpulse init first.')
        last_error = None
        available = False
        for provider in self.providers:
            key = json.dumps(provider.__dict__, sort_keys=True)
            failures, until = self._read(key)
            if self._now() < until:
                continue
            available = True
            try:
                response = self.transport(provider, messages)
                self._write(key, 0, 0)
                return response
            except ProviderError as exc:
                last_error = exc
                if exc.retryable:
                    failures += 1
                    self._write(key, failures, self._now() + 30 if failures >= 3 else 0)
        if not available:
            raise ProviderError(
                'All configured model circuits are open; retry after cooldown.', retryable=True
            )
        if last_error:
            raise last_error
        raise ProviderError('No configured model provider is available.')


class AgentSession:
    def __init__(
        self,
        model: AgentModel,
        tools: ToolRunner,
        scrub: Callable[[str], str],
        *,
        on_event: Callable[[dict], None] | None = None,
        store: AgentSessionStore | None = None,
        session_id: str | None = None,
        context_budget_bytes: int = 16000,
    ):
        self.model, self.tools, self.scrub = model, tools, scrub
        self.on_event = on_event or (lambda event: None)
        self.store, self.session_id = store, session_id
        self.turn_id = None
        self.context_budget_bytes = max(1, min(context_budget_bytes, 512000))
        self.messages: list[dict] = [{'role': 'system', 'content': AGENT_SYSTEM}]
        if store and session_id:
            for item in store.messages(session_id):
                self.messages.append({'role': item['role'], 'content': item['content']})

    def _persist(self, role: str, content: str):
        # Callers redact text leaves before serialization. Scrubbing serialized JSON
        # can register escape characters as secrets and corrupt later JSON strings.
        if self.store and self.session_id:
            self.store.append(self.session_id, role, content)

    @staticmethod
    def _reuse_read_result(call: ToolCall, observations: list[dict]) -> dict | None:
        if call.name != 'read_file':
            return None
        arguments = call.arguments
        path = str(arguments.get('path', '')).replace('\\', '/')
        start = arguments.get('start_line', 1)
        limit = arguments.get('limit', 200)
        for observation in reversed(observations):
            result = observation['result']
            if observation['name'] == 'run_command':
                return None
            if (
                observation['name'] in ('edit_file', 'write_file')
                and result.get('status') == 'written'
                and str(result.get('path', '')).replace('\\', '/') == path
            ):
                return None
            if observation['name'] != 'read_file':
                continue
            if str(result.get('path', '')).replace('\\', '/') != path:
                continue
            total = result.get('total_lines')
            result_start = result.get('start_line')
            result_end = result.get('end_line')
            if (
                type(total) is not int
                or type(result_start) is not int
                or type(result_end) is not int
                or type(start) is not int
                or type(limit) is not int
                or start > total
            ):
                continue
            requested_end = min(total, start + limit - 1)
            covered = result_start <= start and result_end >= requested_end
            if covered and isinstance(result.get('content'), str):
                return {**result, 'provenance': 'reused prior read'}
        return None

    def run(self, task: str, project_name: str, guidance: str = '', references=()) -> str:
        if not task.strip() or len(task.encode('utf-8')) > 12000:
            raise ValueError('Task must contain 1 to 12 KB of text.')
        self.turn_id = (
            self.store.begin_turn(self.session_id, self.scrub(task))
            if self.store and self.session_id
            else None
        )
        try:
            answer = self._run(task, project_name, guidance, references)
        except BaseException as exc:
            if self.turn_id:
                status = (
                    'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
                )
                self.store.finish_turn(self.turn_id, status, error=self.scrub(str(exc))[:2000])
            raise
        else:
            if self.turn_id:
                self.store.finish_turn(self.turn_id, 'succeeded', summary=answer)
            return answer

    def _run(self, task, project_name, guidance, references):
        completion = CompletionGate(task)
        history = self.messages[1:]
        task, guidance = self.scrub(task), self.scrub(guidance)
        self.messages.append({'role': 'user', 'content': task})
        self._persist('user', task)
        tool_specs = self.tools.describe()
        project_review_intent = requests_project_review(task) and any(
            item.get('name') == 'review_project' for item in tool_specs
        )
        project_review = project_review_intent and is_read_only_project_review(task)
        if not project_review_intent:
            tool_specs = [item for item in tool_specs if item.get('name') != 'review_project']
        context = AgentContext(self.context_budget_bytes)
        observations = []
        scoped = {}
        seen_ids = set()
        for turn in range(MAX_TURNS):
            set_guidance = getattr(self.tools, 'set_guidance', None)
            if set_guidance:
                set_guidance([{'path': path, 'text': text} for path, text in scoped.items()])
            active_guidance = guidance + ''.join(
                f'\n--- {path} ---\n{text}' for path, text in scoped.items()
            )
            active_guidance += completion.guidance
            if project_review_intent and not project_review:
                active_guidance += (
                    '\nUse review_project before manual reads for the requested repository audit.'
                )
            if project_review and turn == 0:
                request_messages = None
                metadata = {'type': 'context', 'omitted_messages': 0}
            else:
                request_messages, metadata = context.build(
                    task,
                    project_name,
                    active_guidance,
                    tool_specs,
                    scrub_history(history, self.scrub),
                    observations,
                    scrub_structure(references, self.scrub),
                )
            self.on_event(metadata)
            if project_review and turn == 0:
                decision = AgentDecision(
                    'Running a read-only review of the whole project.',
                    (ToolCall('project-review', 'review_project', {}),),
                    False,
                )
                raw = json.dumps(
                    {
                        'message': decision.message,
                        'tool_calls': [
                            {'id': call.id, 'name': call.name, 'arguments': call.arguments}
                            for call in decision.tool_calls
                        ],
                        'final': False,
                    }
                )
            else:
                raw = self.model(request_messages)
                decision = AgentDecision.parse(raw)
            allowed_tools = {item.get('name') for item in tool_specs if isinstance(item, dict)}
            local_ids = set()
            guidance_required = False
            validated_calls = []
            for call in decision.tool_calls:
                if call.name not in allowed_tools:
                    raise ValueError('Agent requested a tool outside the available catalog.')
                if call.id in local_ids:
                    raise ValueError('Tool call IDs must be unique within a decision.')
                local_ids.add(call.id)
                validate_arguments(call.name, call.arguments)
                call_id = call.id
                if call_id in seen_ids:
                    suffix = 1
                    while f'{call.id}_{suffix}' in seen_ids:
                        suffix += 1
                    call_id = f'{call.id}_{suffix}'
                seen_ids.add(call_id)
                validated_calls.append(ToolCall(call_id, call.name, call.arguments))
            safe_message = self.scrub(decision.message)
            decision_value = scrub_structure(json.loads(raw), self.scrub)
            if decision.discarded_tool_calls:
                safe_message += '\n\nDevPulse ignored a tool request paired with this final answer.'
                decision_value['message'] = safe_message
                decision_value['tool_calls'] = []
            safe_decision = json.dumps(decision_value, ensure_ascii=True)
            if decision.final:
                feedback = completion.check()
                if feedback:
                    observations.append(
                        {'id': f'completion-{turn}', 'name': 'completion_check', 'result': feedback}
                    )
                    self._persist('tool', 'Completion check: ' + json.dumps(feedback))
                    self.on_event({'type': 'completion_blocked', 'reason': feedback['reason']})
                    continue
                safe_message = completion.render(safe_message)
                decision_value['message'] = safe_message
                safe_decision = json.dumps(decision_value, ensure_ascii=True)
            self.messages.append({'role': 'assistant', 'content': safe_decision})
            self._persist('assistant', safe_decision)
            if decision.final:
                self.on_event({'type': 'message', 'text': safe_message})
                return safe_message
            else:
                self.on_event({'type': 'plan', 'text': safe_message})
            for call in validated_calls:
                safe_call_id = self.scrub(call.id)
                safe_arguments = scrub_structure(call.arguments, self.scrub)
                self.on_event(
                    {
                        'type': 'tool_start',
                        'name': call.name,
                        'arguments': safe_arguments,
                    }
                )
                if self.turn_id:
                    self.store.begin_action(self.turn_id, safe_call_id, call.name)
                try:
                    result = self._reuse_read_result(call, observations)
                    if result is None:
                        result = self.tools.execute(call.name, call.arguments)
                except Exception as exc:
                    result = {'error': self.scrub(str(exc))[:2000]}
                safe_result = scrub_structure(result, self.scrub)
                completion.observe(call.name, call.arguments, safe_result)
                for item in safe_result.get('instructions', []):
                    scoped[item['path']] = item['text']
                guidance_required = (
                    guidance_required or safe_result.get('status') == 'instructions_required'
                )
                if self.turn_id:
                    self.store.finish_action(self.turn_id, safe_call_id, safe_result)
                safe_result, _ = bounded_result(safe_result, MAX_TOOL_RESULT_BYTES)
                observations.append({'id': safe_call_id, 'name': call.name, 'result': safe_result})
                rendered = json.dumps(safe_result, ensure_ascii=True)
                self.messages.append(
                    {'role': 'tool', 'content': f'Tool result {safe_call_id}: {rendered}'}
                )
                self._persist('tool', f'Tool result {safe_call_id}: {rendered}')
                self.on_event({'type': 'tool_end', 'name': call.name, 'result': rendered})
                if project_review and call.name == 'review_project':
                    if 'error' in safe_result:
                        raise ValueError('Project review failed: ' + safe_result['error'])
                    answer = self._format_project_review(safe_result)
                    final = json.dumps(
                        {'message': answer, 'tool_calls': [], 'final': True}, ensure_ascii=True
                    )
                    self.messages.append({'role': 'assistant', 'content': final})
                    self._persist('assistant', final)
                    self.on_event({'type': 'message', 'text': answer})
                    return answer
                if guidance_required:
                    break
        raise ValueError(f'Agent reached its {MAX_TURNS}-turn limit; ask it to continue.')

    @staticmethod
    def _format_project_review(result):
        lines = [result.get('summary') or 'Project review completed.']
        findings = result.get('findings', [])
        if not findings:
            lines.append('No actionable findings.')
        else:
            for item in findings:
                location = item.get('path') or 'project'
                if item.get('line'):
                    location += f':{item["line"]}'
                severity = str(item.get('severity', 'info')).upper()
                lines.append(f'- [{severity}] {location}: {item.get("message", "Review finding.")}')
        omitted = result.get('omitted_findings', 0)
        if omitted:
            lines.append(f'{omitted} additional findings omitted from the task response.')
        coverage = result.get('source', {})
        omitted_files = coverage.get('files_omitted_from_prompt', 0)
        if omitted_files:
            lines.append(
                f'Coverage warning: {omitted_files} project file(s) were excluded from the AI prompt by size limits.'
            )
        return '\n'.join(lines)
