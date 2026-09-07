"""
Windows-only RQ worker entrypoint.

RQ workers rely on os.fork() by default, which doesn't exist on Windows --
that's what SimpleWorker (rq.worker.SimpleWorker) fixes, by running jobs
in-process instead of forking a subprocess per job.

But SimpleWorker still enforces per-job timeouts with
rq.timeouts.UnixSignalDeathPenalty, which arms the timeout via
signal.SIGALRM. SIGALRM doesn't exist on Windows either, so the plain
`rq worker -w rq.worker.SimpleWorker ...` command crashes on the very first
job with:

    AttributeError: module 'signal' has no attribute 'SIGALRM'

This entrypoint swaps in a no-op death penalty class so jobs run without
per-job timeout enforcement. That's an acceptable trade-off here: jobs run
one at a time, in-process, and are short-lived (dividend payouts, treasury
accrual) -- there's no forking and nothing that risks hanging the worker
indefinitely. On macOS/Linux, keep using the normal `rq worker` command,
which enforces timeouts properly.

Run with (from forecast-backend/):
    python -m app.jobs.windows_worker
"""
from rq.timeouts import BaseDeathPenalty
from rq.worker import SimpleWorker

from app.jobs.queue import redis_conn, default_queue


class NoOpDeathPenalty(BaseDeathPenalty):
    """Disables RQ's signal-based job timeout enforcement (unavailable on Windows)."""

    def setup_death_penalty(self):
        pass

    def cancel_death_penalty(self):
        pass


class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = NoOpDeathPenalty


if __name__ == "__main__":
    worker = WindowsSimpleWorker([default_queue], connection=redis_conn)
    worker.work()
