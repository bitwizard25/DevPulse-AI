"""Durable job inspection, waiting and control."""

import sys
import time
from pathlib import Path

from ...domain.jobs import TERMINAL_STATES
from ...infrastructure.config import state_home
from ...infrastructure.jobs import SQLiteJobStore
from ...infrastructure.state import State
from ..gateway import ensure_gateway
from ..output import emit, render_review, review_exit


def wait_for_result(job_id: str, *, timeout: float | None = None) -> dict:
    store = SQLiteJobStore(State(state_home()))
    ensure_gateway(state_home())
    started = time.monotonic()
    try:
        while True:
            job = store.get(job_id)
            if job.status == 'succeeded':
                return dict(job.result, job_id=job.id)
            if job.status in TERMINAL_STATES:
                raise ValueError(f'Job {job.id} {job.status}: {job.error or "no result available"}')
            if timeout is not None and time.monotonic() - started >= timeout:
                raise ValueError(
                    f'Wait timed out. Job {job.id} remains durable; use jobs wait to reconnect.'
                )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print(
            f'Stopped waiting; job {job_id} remains durable. Use jobs wait {job_id}.',
            file=sys.stderr,
        )
        raise


def handle(args, root: Path) -> int:
    state = State(state_home())
    store = SQLiteJobStore(state)
    if args.action == 'list':
        jobs = store.list(state.identity(str(root)), args.limit)
        if args.json:
            emit([job.public(include_result=False) for job in jobs], True)
        else:
            for job in jobs:
                emit(f'{job.id}  {job.status}  attempts={job.attempts}')
            if not jobs:
                emit('No durable jobs for this project.')
        return 0
    if not args.id:
        raise ValueError('Supply a job ID.')
    if args.action == 'wait':
        if args.timeout is not None and args.timeout <= 0:
            raise ValueError('Wait timeout must be positive.')
        result = wait_for_result(args.id, timeout=args.timeout)
        render_review(result, args.json)
        return review_exit(result, args.fail_on)
    if args.action == 'cancel':
        job = store.cancel(args.id)
    elif args.action == 'retry':
        job = store.retry(args.id)
        ensure_gateway(state_home())
    else:
        job = store.get(args.id)
    emit(job.public(), True)
    return 0
