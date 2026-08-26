"""Layering rules, enforced.

The README claims dependencies flow one way:

    api/routers  ->  services  ->  storage  ->  models

A claim in a README is not a constraint. This file makes it one — the violation it
now prevents was committed once already, because `services/auth.py` needed a type
that happened to live in `api/`, and importing upward was the path of least
resistance. It compiled, the tests passed, and nothing complained.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"

FORBIDDEN: dict[str, set[str]] = {
    # The coursework core must stay independently usable. Anything it imports from
    # the layers above would make it un-runnable outside this application.
    "notenverwaltung": {"api", "services"},
    # Use cases must not depend on HTTP. A service that imports FastAPI cannot be
    # driven from a CLI, a test, or a background job without dragging a web
    # framework along.
    "services": {"api"},
}


def imports_of(path: pathlib.Path) -> set[str]:
    """Return the absolute module paths a module imports.

    Args:
        path: The Python file to inspect.

    Returns:
        Imported paths, e.g. ``{"sqlite3", "notenverwaltung.storage.db.transaction"}``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.update(f"{node.module}.{alias.name}" for alias in node.names)

    return found


def modules_in(package: str) -> list[pathlib.Path]:
    """Return every Python file in a package."""
    return sorted((SRC / package).rglob("*.py"))


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_the_package_exists(package: str) -> None:
    """Guards the rules below: a renamed package would make them silently vacuous."""
    assert modules_in(package), f"No modules found in {package!r} — has it moved?"


@pytest.mark.parametrize(
    ("package", "path"),
    [(pkg, path) for pkg in sorted(FORBIDDEN) for path in modules_in(pkg)],
    ids=lambda value: value.name if isinstance(value, pathlib.Path) else str(value),
)
def test_no_upward_imports(package: str, path: pathlib.Path) -> None:
    """No module may import from a layer above its own."""
    violations = {name.split(".")[0] for name in imports_of(path)} & FORBIDDEN[package]
    assert not violations, (
        f"{path.relative_to(SRC)} imports {sorted(violations)}, which sits above "
        f"{package!r}. Move the shared symbol down instead of importing upward."
    )


def test_routers_do_not_import_infrastructure() -> None:
    """No router reaches past its service into the database.

    This used to police five hand-listed handlers in `directory.py`, guarding a
    migration to an `AcademicRecords` protocol that was never finished — its own
    docstring conceded that "not-yet-migrated routers and services intentionally
    remain outside this rule", which is a rule that exempts whatever breaks it.

    Every router now passes it, so the exemption is gone. A router that imports
    `sqlite3` or the storage layer has taken on the transaction boundary, which
    belongs to the service that owns the use case -- together with the audit row that
    has to commit with the change it describes.

    Importing a *service* is not a violation: `routers/audit.py` reads the trail
    through `services.audit`, which is the layer doing its job.
    """
    forbidden = ("sqlite3", "notenverwaltung.storage")
    offenders: dict[str, list[str]] = {}
    for path in sorted((SRC / "api" / "routers").glob("*.py")):
        violations = sorted(
            name
            for name in imports_of(path)
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
        )
        if violations:
            offenders[path.name] = violations
    assert not offenders, (
        f"Routers importing infrastructure directly: {offenders}. "
        "Move the transaction and its audit row into the service that owns the use case."
    )


def test_sql_lives_only_in_the_storage_layer() -> None:
    """SQL belongs in ``notenverwaltung/storage`` and the services that own a use case.

    Not in routers. A router that writes SQL has bypassed the scope filter that
    `services.scoping` exists to apply, which is how row-level access control gets
    quietly lost.

    Scoped to ``api/routers`` rather than all of ``api``: `migrate` and `seed` are
    command-line entry points whose entire job is to populate a database, and there is
    no request whose scope they could be bypassing.
    """
    keywords = ("SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM")
    offenders: list[str] = []

    for path in sorted((SRC / "api" / "routers").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        # Ignore prose: docstrings and comments legitimately discuss queries.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith(("#", '"', "'"))
        )
        if any(keyword in code for keyword in keywords):
            offenders.append(str(path.relative_to(SRC)))

    assert not offenders, (
        f"SQL found in the HTTP layer: {offenders}. Move it into a service so the "
        "caller's scope is applied."
    )
