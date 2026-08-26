"""A row-restriction value object.

Deliberately knows nothing about users, roles or authentication — it is a SQL
fragment and its parameters, nothing more. That keeps the dependency direction
right: :mod:`services.scoping` turns a signed-in principal into a :class:`Scope`,
and the storage layer consumes one without importing anything above it.

The important property is the default. :data:`DENY_ALL` rather than an empty
fragment means a query that is handed no scope returns **nothing**, not everything.
A forgotten filter shows up as an empty table, which someone reports; the opposite
default shows up as one student reading another's grades, which nobody reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Scope:
    """A ``WHERE``-clause fragment restricting which rows a caller may see.

    Attributes:
        sql: A boolean SQL expression, already parenthesised where needed.
        params: Parameters bound to the ``?`` placeholders in ``sql``, in order.
    """

    sql: str
    params: tuple[Any, ...] = ()

    def __and__(self, other: Scope) -> Scope:
        """Combine two scopes so both must hold.

        Args:
            other: The scope to intersect with.

        Returns:
            A scope matching only rows satisfying both.
        """
        if self.sql == "1=1":
            return other
        if other.sql == "1=1":
            return self
        return Scope(f"({self.sql}) AND ({other.sql})", self.params + other.params)


ALLOW_ALL = Scope("1=1")
"""Permits every row. For administrators only."""

DENY_ALL = Scope("1=0")
"""Permits no rows. The default, so a missing filter fails closed."""
