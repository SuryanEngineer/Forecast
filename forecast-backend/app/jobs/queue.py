"""
RQ (Redis Queue) setup. Per the roadmap: "a queue (BullMQ if Node,
Celery/RQ if Python) to process dividend payouts after tournament results
are ingested, so it doesn't block the request path." RQ was chosen over
Celery for v1 because it needs nothing but Redis (no separate broker
config, no result backend setup) -- simplest thing that works, easy to
swap for Celery later if the job workload grows more complex.

Run the worker with:  rq worker forecast-default --url $REDIS_URL
(see README_SETUP.md for the exact command and a systemd/Procfile
example).
"""
from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)
default_queue = Queue("forecast-default", connection=redis_conn)
