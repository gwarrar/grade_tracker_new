"""Scoped, paginated read queries.

Separate from :class:`~notenverwaltung.storage.sqlite_store.GradeStore` because the
store's job is entity CRUD, while list endpoints need filtering, sorting, paging and a
total count. Keeping them apart is what stops every store method growing a second
signature that takes a page number.

Still inside the storage layer, so SQL stays in one place. The :class:`Scope` these
functions take is built by :mod:`services.scoping`; a caller that forgets to pass one
gets :data:`~notenverwaltung.storage.scope.DENY_ALL` and therefore no rows.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.storage.scope import DENY_ALL, Scope

MAX_PAGE_SIZE = 200
"""Ceiling on ``size``.

Without it, ``?size=1000000`` is a one-request denial of service against a
single-writer database.
"""

DEFAULT_PAGE_SIZE = 25
"""Rows per page when the caller does not say.

Declared once here rather than as a literal in each route signature: four routers
spelled `le=200 ... = 25` by hand while both numbers already had a home.
"""


@dataclass
class Page[T]:
    """One page of results.

    Attributes:
        items: The rows on this page.
        total: How many rows match the query overall, ignoring paging.
        page: The 1-based page number.
        size: How many rows were requested per page.
    """

    items: list[T]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        """How many pages exist in total."""
        return max(1, -(-self.total // self.size))  # ceiling division


@dataclass(frozen=True)
class SortSpec:
    """A validated sort order.

    Sort columns cannot be parameterised in SQL, so they are interpolated — which
    means they must come from an allow-list rather than straight from the query
    string. :meth:`parse` is the only way to build one.

    Attributes:
        column: The validated column name.
        descending: Sort direction.
    """

    column: str
    descending: bool = False

    @property
    def sql(self) -> str:
        """The ``ORDER BY`` fragment."""
        return f"{self.column} {'DESC' if self.descending else 'ASC'}"

    @classmethod
    def parse(cls, raw: str | None, allowed: dict[str, str], default: str) -> SortSpec:
        """Parse a client-supplied sort into a validated spec.

        Args:
            raw: The requested sort, e.g. ``"-score"``. A leading ``-`` means
                descending. ``None`` selects the default.
            allowed: Public field name to real column name. Values are trusted;
                keys are what the client may ask for.
            default: The key to use when ``raw`` is absent.

        Returns:
            The validated spec.

        Raises:
            ValidationError: If the requested field is not in ``allowed``. Naming the
                permitted fields in the error turns a guessing game into one request.
        """
        key = (raw or default).strip()
        descending = key.startswith("-")
        field = key.lstrip("-") or default

        if field not in allowed:
            raise ValidationError(
                f"Cannot sort by {field!r}.", field="sort", allowed=sorted(allowed)
            )
        return cls(column=allowed[field], descending=descending)


def escape_like(value: str) -> str:
    r"""Escape the wildcards in a ``LIKE`` pattern.

    Without this, a search for ``100%`` matches every row -- a working-looking search
    returning wrong answers, which is worse than an error. ``\`` is escaped first, or
    escaping the other two would double-escape their new backslashes.

    Callers must pair this with ``ESCAPE '\'`` in the SQL; the escape character is
    not implied.

    Args:
        value: Raw user input.

    Returns:
        The value with ``\``, ``%`` and ``_`` escaped.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_clause(query: str | None, columns: list[str]) -> Scope:
    """Build a case-insensitive substring match across several columns.

    Uses ``LIKE`` rather than the regex search offered elsewhere: a list endpoint's
    ``?q=`` is a text box, and a user typing ``C++`` into it expects results, not a
    pattern error.

    Args:
        query: The search text. Blank or ``None`` matches everything.
        columns: Columns to search.

    Returns:
        A scope matching rows where any column contains the text.
    """
    if not query or not query.strip():
        return Scope("1=1")

    pattern = f"%{escape_like(query.strip())}%"
    clause = " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns)
    return Scope(f"({clause})", tuple(pattern for _ in columns))


_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


def paginate(
    conn: sqlite3.Connection,
    *,
    select: str,
    from_clause: str,
    scope: Scope | None,
    sort: SortSpec,
    page: int,
    size: int,
    search: str | None = None,
    search_columns: list[str] | None = None,
    extra: Scope | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """Run a scoped, filtered, sorted and paged query.

    Args:
        conn: The connection to query.
        select: The projection, without ``SELECT``.
        from_clause: The source, without ``FROM``, including any joins.
        scope: The caller's row restriction. ``None`` denies everything.
        sort: A validated sort order.
        page: 1-based page number.
        size: Rows per page, capped at :data:`MAX_PAGE_SIZE`.
        search: Optional free-text filter.
        search_columns: Columns the free-text filter applies to.
        extra: Additional filtering, such as ``course_id = ?``.

    Returns:
        ``(rows, total)`` where ``total`` ignores paging.

    Raises:
        ValidationError: If ``page`` is below 1 or a search column is malformed.
    """
    if page < 1:
        raise ValidationError("Page must be 1 or greater.", field="page", value=page)
    size = max(1, min(size, MAX_PAGE_SIZE))

    for column in search_columns or []:
        if not _SAFE_IDENT.match(column):
            raise ValueError(f"Unsafe search column: {column!r}")

    where = scope if scope is not None else DENY_ALL
    if extra is not None:
        where = where & extra
    if search_columns:
        where = where & _search_clause(search, search_columns)

    total_row = conn.execute(
        f"SELECT COUNT(*) FROM {from_clause} WHERE {where.sql}",  # noqa: S608
        where.params,
    ).fetchone()
    total = total_row[0] if total_row else 0

    rows = conn.execute(
        f"SELECT {select} FROM {from_clause} WHERE {where.sql}"  # noqa: S608
        f" ORDER BY {sort.sql} LIMIT ? OFFSET ?",
        (*where.params, size, (page - 1) * size),
    ).fetchall()

    return list(rows), total


def exists(conn: sqlite3.Connection, table: str, column: str, value: Any, scope: Scope) -> bool:
    """Check whether a row is visible to the caller.

    Used to distinguish "does not exist" from "exists but is not yours" — and then
    to deliberately report both as not-found, so a 403 does not confirm that a record
    with that id exists.

    Args:
        conn: The connection to query.
        table: The table to search.
        column: The column to match on.
        value: The value to match.
        scope: The caller's row restriction.

    Returns:
        ``True`` if a matching row is within scope.

    Raises:
        ValueError: If the table or column name is not a plain identifier.
    """
    if not _SAFE_IDENT.match(table) or not _SAFE_IDENT.match(column):
        raise ValueError(f"Unsafe identifier: {table}.{column}")

    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ? AND ({scope.sql}) LIMIT 1",  # noqa: S608
        (value, *scope.params),
    ).fetchone()
    return row is not None
