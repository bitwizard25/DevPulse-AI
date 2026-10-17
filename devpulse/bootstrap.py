"""Composition root: concrete dependencies are wired only at the process boundary."""

from dataclasses import dataclass

from .application.agent import AgentModelRouter, AgentSession
from .application.context import ContextPlanner, ContextService
from .application.jobs import JobService
from .application.ports import ModelTransport
from .application.review import Engine
from .application.router import Router
from .application.worker import Worker
from .infrastructure.agent_guidance import read_agent_guidance
from .infrastructure.agent_sessions import SQLiteAgentSessions
from .infrastructure.agent_tools import ProjectTools
from .infrastructure.circuits import SQLiteCircuits
from .infrastructure.clock import SystemClock
from .infrastructure.config import credential_values
from .infrastructure.context import read_rules
from .infrastructure.jobs import SQLiteJobStore
from .infrastructure.memory import SQLiteMemoryIndex
from .infrastructure.providers import complete, complete_agent
from .infrastructure.source import collect
from .infrastructure.state import State
from .infrastructure.tokens import ConservativeTokenCounter


def make_engine(
    state: State, transport: ModelTransport = complete, *, circuits=None, clock=None
) -> Engine:
    return Engine(
        state=state,
        source_reader=collect,
        context_reader=ContextService(SQLiteMemoryIndex(state), read_rules, state.identity),
        router=Router(transport, circuits=circuits, clock=clock),
        credentials=credential_values,
        planner=ContextPlanner(ConservativeTokenCounter()),
    )


@dataclass
class Runtime:
    engine: Engine
    jobs: SQLiteJobStore
    service: JobService
    worker: Worker


@dataclass
class AgentRuntime:
    model: AgentModelRouter
    sessions: SQLiteAgentSessions
    context: ContextService


def make_agent_runtime(state: State, config) -> AgentRuntime:
    return AgentRuntime(
        model=AgentModelRouter(
            config.providers, complete_agent, circuits=SQLiteCircuits(state), clock=SystemClock()
        ),
        sessions=SQLiteAgentSessions(state),
        context=ContextService(SQLiteMemoryIndex(state), read_agent_guidance, state.identity),
    )


def make_agent_session(runtime, config, root, session_id, approve, on_event, vault):
    available_tokens = min(
        provider.context_window_tokens - provider.output_tokens - provider.safety_tokens
        for provider in config.providers
    )
    return AgentSession(
        runtime.model,
        ProjectTools(root, approve, vault),
        vault.scrub,
        on_event=on_event,
        store=runtime.sessions,
        session_id=session_id,
        # The agent packs JSON and source text, so reserve a conservative two
        # UTF-8 bytes per configured input token rather than wasting the token
        # allowance by treating every token as one byte.
        context_budget_bytes=available_tokens * 2,
    )


def make_runtime(state: State, transport: ModelTransport = complete) -> Runtime:
    clock = SystemClock()
    engine = make_engine(state, transport, circuits=SQLiteCircuits(state), clock=clock)
    jobs = SQLiteJobStore(state, clock)
    return Runtime(engine, jobs, JobService(jobs, engine, clock), Worker(jobs, engine, clock))
