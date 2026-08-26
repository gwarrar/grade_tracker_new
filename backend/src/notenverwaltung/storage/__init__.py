"""Persistence: the SQLite store, its connection helpers and the query builders.

:class:`GradeStore` owns the per-entity statements; :mod:`notenverwaltung.storage.queries`
owns listing and pagination, composed from a
:class:`~notenverwaltung.storage.scope.Scope` so that a caller's visibility is part of
the query rather than a filter applied afterwards.

**Where SQL is allowed.** Here, and in the services that own a use case. *Not* in
routers, which is the half that is enforced rather than asked for:
``tests/unit/test_architecture.py`` fails the build on a router that writes SQL or
imports this package, because a router holding a connection has taken on the
transaction boundary and the audit row that must commit with it.
"""

from notenverwaltung.storage.db import apply_migrations, connect, transaction
from notenverwaltung.storage.sqlite_store import GradeStore

__all__ = [
    "GradeStore",
    "apply_migrations",
    "connect",
    "transaction",
]
