"""Durable submission and waiting use cases, shared by gateway entry points."""

from ..domain.jobs import TERMINAL_STATES, Job
from .ports import Clock, JobStore
from .review import Engine


class JobService:
    def __init__(self, store: JobStore, engine: Engine, clock: Clock):
        self.store, self.engine, self.clock = store, engine, clock

    def submit(self, root, config, **options) -> Job:
        return self.store.submit(self.engine.prepare(root, config, **options))

    def wait(self, job_id: str, stop_waiting=lambda: False) -> dict:
        while True:
            job = self.store.get(job_id)
            if job.status == 'succeeded':
                return dict(job.result, job_id=job.id)
            if job.status in TERMINAL_STATES:
                raise ValueError(
                    f'Job {job.id} {job.status}: {job.error or "no result is available"}'
                )
            if stop_waiting():
                raise ValueError(
                    f'Gateway is stopping. Job {job.id} remains recorded; use jobs wait after restart.'
                )
            self.clock.sleep(0.1)
