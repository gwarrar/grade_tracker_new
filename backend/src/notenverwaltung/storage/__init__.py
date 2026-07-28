"""Persistence: the :class:`GradeStore` interface and its implementations.

This is the only layer that contains SQL. Everything above it works against the ABC,
which is what keeps a future database change to one new subclass.
"""

from notenverwaltung.storage.base import GradeStore
from notenverwaltung.storage.db import apply_migrations, connect, transaction
from notenverwaltung.storage.memory_store import InMemoryGradeStore
from notenverwaltung.storage.sqlite_store import SqliteGradeStore

__all__ = [
    "GradeStore",
    "InMemoryGradeStore",
    "SqliteGradeStore",
    "apply_migrations",
    "connect",
    "transaction",
]
