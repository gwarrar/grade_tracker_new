"""Write the OpenAPI document to docs/openapi.json.

Committed and diffable, so a change to the API surface is visible in review rather
than only at runtime. CI regenerates it and fails if the committed copy is stale --
documentation that can drift from the code is documentation nobody trusts.

Usage:
    uv run python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def main(argv: list[str] | None = None) -> int:
    """Write or verify the OpenAPI document.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit code. With --check, 1 means the committed copy is stale.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if the committed copy is out of date."
    )
    args = parser.parse_args(argv)

    document = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current.strip() != document.strip():
            print(
                "docs/openapi.json is stale. Run:\n    uv run python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print("docs/openapi.json is up to date")
        return 0

    OUTPUT.write_text(document + "\n", encoding="utf-8")
    paths = len(json.loads(document)["paths"])
    print(f"wrote {OUTPUT} ({paths} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
