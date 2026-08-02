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


def test_migrated_enrollment_controllers_do_not_import_infrastructure() -> None:
    """The migrated enrollment seam depends on its capability, not infrastructure.

    Imports are module-scoped, so this protects the complete directory router that
    owns the five migrated handlers. Migration, seed and admin entry points, plus
    not-yet-migrated routers and services, intentionally remain outside this rule.
    """
    path = SRC / "api" / "routers" / "directory.py"
    assert path.is_file(), "The migrated directory router has moved"

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    expected = {
        "student_courses",
        "list_enrollments",
        "enroll",
        "set_enrollment_status",
        "unenroll",
    }
    assert expected <= functions, f"Enrollment controllers missing: {sorted(expected - functions)}"

    forbidden = ("sqlite3", "notenverwaltung.storage", "services.audit")
    violations = sorted(
        name
        for name in imports_of(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    )
    assert not violations, (
        f"{path.relative_to(SRC)} imports infrastructure directly: {violations}. "
        "Use the AcademicRecords capability instead."
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
