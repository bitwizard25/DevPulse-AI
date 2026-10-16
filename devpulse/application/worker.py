"""Single durable worker; SQLite owns scheduling, retries and cancellation state."""

import random
import threading
import uuid

from ..domain.errors import ProviderError, ReviewCancelled
from ..domain.privacy import Vault
from .ports import Clock, JobStore
from .review import Engine


class JobCancellation:
    def __init__(self, store: JobStore, job_id: str, owner: str):
        self.store, self.job_id, self.owner = store, job_id, owner

    def cancelled(self) -> bool:
        return self.store.cancelled(self.job_id, self.owner)


class Worker:
    def __init__(self, store: JobStore, engine: Engine, clock: Clock, *, owner: str | None = None):
        self.store, self.engine, self.clock = store, engine, clock
        self.owner = owner or uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.store.recover(self.owner)
        self._thread = threading.Thread(target=self._loop, name='devpulse-worker', daemon=False)
        self._thread.start()

    def stop(self):
        self.request_stop()
        if self._thread:
            self._thread.join()

    def request_stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(0.2)

    def run_once(self) -> bool:
        job = self.store.claim(self.owner)
        if job is None:
            return False
        finished = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(job.id, finished), daemon=True)
        heartbeat.start()
        try:
            result = self.engine.execute(
                job.snapshot, JobCancellation(self.store, job.id, self.owner)
            )
            self.store.complete(job.id, self.owner, result)
        except ReviewCancelled:
            self.store.fail(job.id, self.owner, 'Job cancelled or expired.')
        except ProviderError as exc:
            delay = (
                max(exc.retry_after, min(60, 2 ** (job.attempts - 1)) + random.uniform(0.2, 0.8))
                if exc.retryable
                else None
            )
            self.store.fail(job.id, self.owner, Vault().scrub(str(exc))[:1000], retry_delay=delay)
        except ValueError as exc:
            self.store.fail(job.id, self.owner, Vault().scrub(str(exc))[:1000])
        except Exception:
            self.store.fail(
                job.id, self.owner, 'Review failed; no raw input or provider response was logged.'
            )
        finally:
            finished.set()
            heartbeat.join()
        return True

    def _heartbeat(self, job_id: str, finished: threading.Event):
        while not finished.wait(5):
            if not self.store.heartbeat(job_id, self.owner):
                return
