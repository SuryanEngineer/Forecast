"""
Pure business-logic engines for the Forecast trading platform.

Everything in this package is deliberately dependency-free (standard library
only: decimal, dataclasses, heapq, itertools). No SQLAlchemy, no FastAPI, no
Redis. That means:

  1. It can be unit-tested without a database, a running API, or any
     third-party package installed.
  2. The "real" formulas (quick buy/sell pricing, dividend payout curve,
     treasury accrual) live in exactly one place each, clearly documented,
     and are easy to swap out once the simulation phase of the roadmap
     produces the final versions.

The `app/services/` layer is the only thing that is allowed to import both
this package and the SQLAlchemy models -- it translates database rows into
the plain dataclasses these engines expect, calls the pure function, and
writes the result back to the database inside a transaction.
"""
