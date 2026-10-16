import concurrent.futures
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from devpulse.domain.jobs import ReviewSnapshot
from devpulse.domain.models import Config
from devpulse.infrastructure.jobs import SQLiteJobStore
from devpulse.infrastructure.state import State


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def now(self):
        return self.value

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def snapshot(digest='digest', **changes):
    values = dict(
        project='project',
        digest=digest,
        config=Config(),
        prompt='redacted input',
        findings=[],
        context={},
        source={'kind': 'file', 'python_files_checked': 1},
        redacted_values=0,
        mode='offline',
        has_source=True,
        no_cache=False,
        chaos=False,
    )
    return ReviewSnapshot(**(values | changes))


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = State(self.home)
        self.clock = FakeClock()
        self.store = SQLiteJobStore(self.state, self.clock)

    def test_snapshot_survives_reopen_and_coalesces(self):
        job = self.store.submit(snapshot())
        reopened = SQLiteJobStore(State(self.home), self.clock)
        self.assertEqual(reopened.submit(snapshot()).id, job.id)
        claimed = reopened.claim('owner')
        self.assertEqual(claimed.snapshot.prompt, 'redacted input')
        self.assertEqual(claimed.attempts, 1)
        self.assertIsNone(self.store.claim('other-owner'))

    def test_concurrent_claim_is_atomic(self):
        self.store.submit(snapshot())
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            claimed = list(pool.map(lambda n: self.store.claim(str(n)), range(8)))
        self.assertEqual(sum(job is not None for job in claimed), 1)

    def test_equal_timestamps_keep_submission_order(self):
        expected = [self.store.submit(snapshot(str(number))).id for number in range(8)]
        actual = []
        for _ in expected:
            job = self.store.claim('owner')
            actual.append(job.id)
            self.store.complete(job.id, 'owner', {'summary': 'done'})
        self.assertEqual(actual, expected)

    def test_listing_does_not_load_results_or_snapshots(self):
        job = self.store.submit(snapshot())
        self.store.claim('owner')
        self.store.complete(job.id, 'owner', {'summary': 'large saved result'})
        listed = self.store.list()[0]
        self.assertIsNone(listed.result)
        self.assertIsNone(listed.snapshot)
        self.assertEqual(self.store.get(job.id).result['summary'], 'large saved result')

    def test_cancel_and_expire_remove_replay_payload(self):
        cancelled = self.store.submit(snapshot('cancel'))
        self.store.cancel(cancelled.id)
        self.assertEqual(self.store.get(cancelled.id).status, 'cancelled')
        expiring = self.store.submit(snapshot('expire'))
        self.clock.value += 86401
        self.store.expire()
        self.assertEqual(self.store.get(expiring.id).status, 'expired')
        with self.state.connect() as db:
            self.assertIsNone(
                db.execute('SELECT snapshot FROM jobs WHERE id=?', (expiring.id,)).fetchone()[0]
            )
        with self.assertRaises(ValueError):
            self.store.retry(expiring.id)

    def test_recovery_and_owner_fencing(self):
        job = self.store.submit(snapshot())
        self.store.claim('dead-owner')
        self.store.recover('new-owner')
        self.assertEqual(self.store.get(job.id).status, 'queued')
        claimed = self.store.claim('new-owner')
        self.assertFalse(self.store.complete(job.id, 'dead-owner', {'summary': 'stale'}))
        self.assertTrue(self.store.complete(job.id, 'new-owner', {'summary': 'current'}))
        self.assertEqual(self.store.get(job.id).result['summary'], 'current')
        self.assertEqual(claimed.attempts, 2)

    def test_running_cancel_is_requested_until_attempt_finishes(self):
        job = self.store.submit(snapshot())
        self.store.claim('owner')
        self.store.cancel(job.id)
        self.assertEqual(self.store.get(job.id).status, 'running')
        self.assertTrue(self.store.get(job.id).cancel_requested)
        self.store.complete(job.id, 'owner', {'summary': 'must be discarded'})
        self.assertEqual(self.store.get(job.id).status, 'cancelled')
        self.assertIsNone(self.store.get(job.id).result)

    def test_manual_retry_preserves_original_snapshot_expiry(self):
        job = self.store.submit(snapshot(), ttl=10)
        self.store.claim('owner')
        self.store.fail(job.id, 'owner', 'invalid response')
        self.clock.value += 4
        retried = self.store.retry(job.id)
        self.assertNotEqual(retried.id, job.id)
        self.assertEqual(retried.expires, 1010.0)

    def test_outstanding_limit_and_no_cache(self):
        first = self.store.submit(snapshot(no_cache=True))
        second = self.store.submit(snapshot(no_cache=True))
        self.assertNotEqual(first.id, second.id)
        for number in range(98):
            self.store.submit(snapshot(str(number)))
        with self.assertRaisesRegex(ValueError, '100'):
            self.store.submit(snapshot('overflow'))

    def test_version_two_backup_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with closing(sqlite3.connect(home / 'state.db')) as db:
                db.executescript("""
                    CREATE TABLE sessions(id TEXT PRIMARY KEY,project TEXT,digest TEXT,status TEXT,
                        started REAL,finished REAL,result TEXT,error TEXT,owner_pid INTEGER DEFAULT 0);
                    CREATE TABLE cache(key TEXT PRIMARY KEY,result TEXT,expires REAL);
                    INSERT INTO cache VALUES('old','{"summary":"retained"}',99999999999);
                    PRAGMA user_version=2;
                """)
                db.commit()
            upgraded = State(home)
            self.assertEqual(upgraded.cache_get('old'), {'summary': 'retained'})
            backups = list((home / 'backups').glob('state-v2-*.db'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_version_one_backup_precedes_all_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with closing(sqlite3.connect(home / 'state.db')) as db:
                db.executescript("""CREATE TABLE sessions(id TEXT PRIMARY KEY,project TEXT,digest TEXT,status TEXT,
                    started REAL,finished REAL,result TEXT,error TEXT); PRAGMA user_version=1;""")
                db.commit()
            upgraded = State(home)
            backup = next((home / 'backups').glob('state-v1-*.db'))
            with closing(sqlite3.connect(backup)) as db:
                self.assertNotIn(
                    'owner_pid', {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
                )
            with upgraded.connect() as db:
                self.assertIn(
                    'owner_pid', {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
                )

    def test_missing_fts5_fails_before_migration(self):
        from devpulse.infrastructure.migrations import migrate

        class WithoutFTS:
            def execute(self, sql):
                raise sqlite3.OperationalError('no such module: fts5')

        with self.assertRaisesRegex(ValueError, 'FTS5'):
            migrate(WithoutFTS(), self.home, 0)


if __name__ == '__main__':
    unittest.main()
