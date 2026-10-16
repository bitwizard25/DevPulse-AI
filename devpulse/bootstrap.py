"""Composition root: concrete dependencies are wired only at the process boundary."""

from dataclasses import dataclass

from .application.context import ContextPlanner, ContextService
from .application.jobs import JobService
from .application.ports import ModelTransport
from .application.review import Engine
from .application.router import Router
from .application.worker import Worker
from .infrastructure.circuits import SQLiteCircuits
from .infrastructure.clock import SystemClock
from .infrastructure.config import credential_values
from .infrastructure.context import read_rules
from .infrastructure.jobs import SQLiteJobStore
from .infrastructure.memory import SQLiteMemoryIndex
from .infrastructure.providers import complete
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


def make_runtime(state: State, transport: ModelTransport = complete) -> Runtime:
    clock = SystemClock()
    engine = make_engine(state, transport, circuits=SQLiteCircuits(state), clock=clock)
    jobs = SQLiteJobStore(state, clock)
    return Runtime(engine, jobs, JobService(jobs, engine, clock), Worker(jobs, engine, clock))
