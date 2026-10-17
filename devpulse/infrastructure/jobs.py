"""Atomic SQLite queue with fenced ownership and expiring replay snapshots."""

import builtins
import json
import uuid

from ..domain.jobs import Job, ReviewSnapshot
from .clock import SystemClock
from .state import State

METADATA_FIELDS = 'id,project,status,attempts,created,updated,expires,available,owner,heartbeat,cancel_requested,error'


class SQLiteJobStore:
    def __init__(self, state: State, clock=None):
        self.state = state
        self.clock = clock or SystemClock()

    @staticmethod
    def _job(row, include_snapshot=False) -> Job:
        fields = dict(row)
        fields.pop('digest', None)
        raw = fields.pop('snapshot', None)
        fields['snapshot'] = (
            ReviewSnapshot.from_dict(json.loads(raw)) if include_snapshot and raw else None
        )
        fields['result'] = json.loads(fields['result']) if fields['result'] else None
        fields['cancel_requested'] = bool(fields['cancel_requested'])
        return Job(**fields)

    def submit(self, snapshot: ReviewSnapshot, *, ttl: float = 86400) -> Job:
        raw = json.dumps(snapshot.to_dict(), ensure_ascii=True)
        if len(raw.encode()) > 2 * 1024 * 1024:
            raise ValueError('Redacted snapshot exceeds the 2 MB storage limit. Split the review.')
        self.expire()
        now = self.clock.now()
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not snapshot.no_cache and not snapshot.chaos:
                existing = db.execute(
                    "SELECT * FROM jobs WHERE project=? AND digest=? AND status IN ('queued','running') AND cancel_requested=0 ORDER BY created,id LIMIT 1",
                    (snapshot.project, snapshot.digest),
                ).fetchone()
                if existing:
                    return self._job(existing)
            count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if count >= 100:
                raise ValueError(
                    'The queue already contains 100 outstanding jobs. Wait or cancel a job.'
                )
            job_id = uuid.uuid4().hex
            db.execute(
                'INSERT INTO jobs(id,project,digest,status,created,updated,expires,available,snapshot) VALUES(?,?,?,?,?,?,?,?,?)',
                (
                    job_id,
                    snapshot.project,
                    snapshot.digest,
                    'queued',
                    now,
                    now,
                    now + ttl,
                    now,
                    raw,
                ),
            )
            return self._job(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def get(self, job_id: str) -> Job:
        self.expire()
        with self.state.connect() as db:
            row = db.execute(
                'SELECT ' + METADATA_FIELDS + ',result,NULL AS snapshot FROM jobs WHERE id=?',
                (job_id,),
            ).fetchone()
        if row is None:
            raise ValueError('Unknown job ID.')
        return self._job(row)

    def list(self, project: str | None = None, limit: int = 20) -> builtins.list[Job]:
        if not 1 <= limit <= 200:
            raise ValueError('Job limit must be between 1 and 200.')
        self.expire()
        with self.state.connect() as db:
            if project:
                rows = db.execute(
                    'SELECT '
                    + METADATA_FIELDS
                    + ',NULL AS result,NULL AS snapshot FROM jobs WHERE project=? ORDER BY created DESC,rowid DESC LIMIT ?',
                    (project, limit),
                )
            else:
                rows = db.execute(
                    'SELECT '
                    + METADATA_FIELDS
                    + ',NULL AS result,NULL AS snapshot FROM jobs ORDER BY created DESC,rowid DESC LIMIT ?',
                    (limit,),
                )
            return [self._job(row) for row in rows]

    def claim(self, owner: str) -> Job | None:
        self.expire()
        now = self.clock.now()
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                return None
            row = db.execute(
                "SELECT id FROM jobs WHERE status='queued' AND available<=? AND attempts<3 ORDER BY created,rowid LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,owner=?,heartbeat=?,updated=? WHERE id=?",
                (owner, now, now, row['id']),
            )
            return self._job(
                db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone(), True
            )

    def heartbeat(self, job_id: str, owner: str) -> bool:
        with self.state.connect() as db:
            return bool(
                db.execute(
                    "UPDATE jobs SET heartbeat=?,updated=? WHERE id=? AND owner=? AND status='running'",
                    (self.clock.now(), self.clock.now(), job_id, owner),
                ).rowcount
            )

    def cancel(self, job_id: str) -> Job:
        self.get(job_id)
        with self.state.connect() as db:
            db.execute(
                "UPDATE jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated=? WHERE id=? AND status IN ('queued','running')",
                (self.clock.now(), job_id),
            )
        return self.get(job_id)

    def cancelled(self, job_id: str, owner: str) -> bool:
        job = self.get(job_id)
        return job.owner != owner or job.cancel_requested or job.status != 'running'

    def complete(self, job_id: str, owner: str, result: dict) -> bool:
        with self.state.connect() as db:
            return bool(
                db.execute(
                    "UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'succeeded' END,result=CASE WHEN cancel_requested=1 THEN NULL ELSE ? END,updated=?,owner=NULL,heartbeat=NULL WHERE id=? AND owner=? AND status='running'",
                    (json.dumps(result), self.clock.now(), job_id, owner),
                ).rowcount
            )

    def fail(self, job_id: str, owner: str, error: str, *, retry_delay: float | None = None):
        now = self.clock.now()
        with self.state.connect() as db:
            db.execute(
                """UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled'
                       WHEN ? IS NOT NULL AND attempts<3 AND expires>? THEN 'queued' ELSE 'failed' END,
                       error=?,available=?,updated=?,owner=NULL,heartbeat=NULL
                       WHERE id=? AND owner=? AND status='running'""",
                (retry_delay, now, error, now + (retry_delay or 0), now, job_id, owner),
            )

    def recover(self, owner: str):
        """Called only by the exclusive gateway owner before starting its worker."""
        self.expire()
        with self.state.connect() as db:
            db.execute(
                """UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled'
                       WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
                       owner=NULL,heartbeat=NULL,updated=?,available=?,error='Previous worker interrupted.'
                       WHERE status='running' AND (owner IS NULL OR owner!=?)""",
                (self.clock.now(), self.clock.now(), owner),
            )

    def expire(self):
        now = self.clock.now()
        with self.state.connect() as db:
            db.execute(
                """UPDATE jobs SET snapshot=NULL,status=CASE WHEN status IN ('queued','running')
                       THEN 'expired' ELSE status END,updated=? WHERE snapshot IS NOT NULL AND expires<=?""",
                (now, now),
            )

    def retry(self, job_id: str) -> Job:
        self.expire()
        with self.state.connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND status IN ('failed','cancelled') AND snapshot IS NOT NULL",
                (job_id,),
            ).fetchone()
        if not row:
            raise ValueError(
                'Only failed or cancelled jobs with unexpired snapshots can be retried.'
            )
        snapshot = ReviewSnapshot.from_dict(json.loads(row['snapshot']))
        return self.submit(snapshot, ttl=row['expires'] - self.clock.now())
