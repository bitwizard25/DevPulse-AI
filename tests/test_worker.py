import json
import tempfile
import unittest
from pathlib import Path

from devpulse.application.worker import Worker
from devpulse.bootstrap import make_engine
from devpulse.domain.errors import ProviderError
from devpulse.domain.models import Config, ProviderConfig
from devpulse.infrastructure.circuits import SQLiteCircuits
from devpulse.infrastructure.jobs import SQLiteJobStore
from devpulse.infrastructure.state import State
from tests.test_jobs import FakeClock


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.state = State(self.root / 'state')
        self.clock = FakeClock()
        self.store = SQLiteJobStore(self.state, self.clock)

    def prepare(self, transport, *, mode='ai'):
        (self.project / 'a.py').write_text('password="private-input"\nprint(1)')
        engine = make_engine(self.state, transport)
        config = Config(providers=[ProviderConfig()])
        prepared = engine.prepare(self.project, config, file='a.py', mode=mode)
        return engine, prepared

    def test_snapshot_replays_without_source_files_or_secret_map(self):
        calls = []

        def transport(config, prompt):
            calls.append(prompt)
            return {'summary': 'Reviewed', 'findings': []}

        engine, prepared = self.prepare(transport)
        self.assertNotIn('private-input', json.dumps(prepared.to_dict()))
        job = self.store.submit(prepared)
        (self.project / 'a.py').unlink()
        Worker(self.store, engine, clock=self.clock).run_once()
        self.assertEqual(self.store.get(job.id).status, 'succeeded')
        self.assertEqual(len(calls), 1)
        self.assertNotIn(b'private-input', self.state.path.read_bytes())

    def test_transient_failure_retries_at_most_three_attempts(self):
        def transport(config, prompt):
            raise ProviderError('temporary outage', retryable=True)

        engine, prepared = self.prepare(transport)
        job = self.store.submit(prepared)
        worker = Worker(self.store, engine, clock=self.clock)
        for _ in range(3):
            self.assertTrue(worker.run_once())
            self.clock.value += 100
        self.assertEqual(self.store.get(job.id).attempts, 3)
        self.assertEqual(self.store.get(job.id).status, 'failed')
        self.assertFalse(worker.run_once())

    def test_bad_response_is_not_retried(self):
        engine, prepared = self.prepare(lambda config, prompt: {'unexpected': 'bad'})
        job = self.store.submit(prepared)
        Worker(self.store, engine, clock=self.clock).run_once()
        self.assertEqual(self.store.get(job.id).status, 'failed')
        self.assertEqual(self.store.get(job.id).attempts, 1)

    def test_cancellation_discards_completed_provider_result(self):
        job_id = []

        def transport(config, prompt):
            self.store.cancel(job_id[0])
            return {'summary': 'discard me', 'findings': []}

        engine, prepared = self.prepare(transport)
        job = self.store.submit(prepared)
        job_id.append(job.id)
        Worker(self.store, engine, clock=self.clock).run_once()
        self.assertEqual(self.store.get(job.id).status, 'cancelled')
        self.assertIsNone(self.store.get(job.id).result)

    def test_circuit_cooldown_survives_new_adapter(self):
        circuits = SQLiteCircuits(self.state)
        circuits.write('provider', 3, self.clock.now() + 30)
        reopened = SQLiteCircuits(State(self.state.home))
        self.assertEqual(reopened.read('provider'), (3, 1030.0))


if __name__ == '__main__':
    unittest.main()
