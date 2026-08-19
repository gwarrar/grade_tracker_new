"""Persistence: the SQLite store, its connection helpers and the query builders.

This is the only layer that contains SQL. :class:`GradeStore` owns the per-entity
statements; :mod:`notenverwaltung.storage.queries` owns listing and pagination,
composed from a :class:`~notenverwaltung.storage.scope.Scope` so that a caller's
visibility is part of the query rather than a filter applied afterwards.
"""

from notenverwaltung.storage.db import apply_migrations, connect, transaction
from notenverwaltung.storage.sqlite_store import GradeStore

__all__ = [
    "GradeStore",
    "apply_migrations",
    "connect",
    "transaction",
]
