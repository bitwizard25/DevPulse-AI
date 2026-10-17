"""Bounded model/tool orchestration for task-first terminal sessions."""

import json
import time
from typing import Callable, Protocol

from ..domain.agent import AgentDecision
from ..domain.agent_prompts import AGENT_SYSTEM
from ..domain.agent_tools import validate_arguments
from ..domain.errors import ProviderError
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
        history = self.messages[1:]
        task, guidance = self.scrub(task), self.scrub(guidance)
        self.messages.append({'role': 'user', 'content': task})
        self._persist('user', task)
        tool_specs = self.tools.describe()
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
            raw = self.model(request_messages)
            decision = AgentDecision.parse(raw)
            allowed_tools = {item.get('name') for item in tool_specs if isinstance(item, dict)}
            local_ids = set()
            guidance_required = False
            for call in decision.tool_calls:
                if call.name not in allowed_tools:
                    raise ValueError('Agent requested a tool outside the available catalog.')
                if call.id in seen_ids or call.id in local_ids:
                    raise ValueError('Tool call IDs must be unique throughout a turn.')
                local_ids.add(call.id)
                validate_arguments(call.name, call.arguments)
            seen_ids.update(local_ids)
            safe_message = self.scrub(decision.message)
            safe_decision = json.dumps(
                scrub_structure(json.loads(raw), self.scrub), ensure_ascii=True
            )
            self.messages.append({'role': 'assistant', 'content': safe_decision})
            self._persist('assistant', safe_decision)
            self.on_event({'type': 'message', 'text': safe_message})
            if decision.final:
                return safe_message
            for call in decision.tool_calls:
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
                    result = self.tools.execute(call.name, call.arguments)
                except Exception as exc:
                    result = {'error': self.scrub(str(exc))[:2000]}
                safe_result = scrub_structure(result, self.scrub)
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
                if guidance_required:
                    break
        raise ValueError(f'Agent reached its {MAX_TURNS}-turn limit; ask it to continue.')
