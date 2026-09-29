"""Write this implementation's OpenAPI document, and refresh the core.

    uv run python scripts/dump-schema.py            # -> the version's directory
                                                    #    under spec/
    uv run python scripts/dump-schema.py --out-dir dist

**Why this build has its own generator, when the Claude build's writes two
platform artifacts.** Since Plan 8 step 6 the published document is named for the
implementation as well as the version — `openapi-<version>-<impl>.json` — and only
this build can produce this build's. Generating it needs `create_app()`, which
needs the Codex SDK installed. The Claude build's script cannot import it and
should not try.

**The DDL is NOT written here, and that is not an omission.** There is one schema,
it belongs to the platform (Plan 9), and it is rendered from the Alembic tree in
`impl/common/db/` by the Claude build's `dump-schema.py`. A second renderer of one
published artifact is a drift waiting to happen. This build *conforms* to that
schema; it does not author it.

**The core is refreshed from what is committed**, not from every app in one
process — see `_write_core`. So the sequence that produces a complete
`openapi-<version>-core.json` is: run each implementation's generator, in any order, and
the last one to run computes the core over all the documents on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: The platform root's `spec/`. Two levels up from this implementation.
SPEC = ROOT.parent.parent / "spec"


def _version_dir(version: str) -> Path:  # noqa: ARG001
    """Where this version's documents belong: **`spec/openapi/`.**

    **No version directories any more** (user, 2026-08-19). `spec/openapi/` carries
    exactly one version and every version before it lives in its
    `release-<version>` git tag, which is also what every release artifact is
    built from. Same three lines in all three builds -- what is duplicated is
    the lookup, not the definition of where a delivery lives.
    """
    return SPEC / "openapi"


def _pretty(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _openapi() -> tuple[str, str]:
    """Return (document version, pretty JSON)."""
    from agent_service.api import create_app

    document = create_app().openapi()
    return document["info"]["version"], _pretty(document)


def _write_core(directory: Path, version: str) -> None:
    """Recompute `openapi-<version>-core.json` from every implementation document present.

    Identical in intent to the Claude build's, and deliberately duplicated rather
    than shared: the *logic* lives in `agent_spec.openapi.core`, which both call.
    What is repeated here is six lines of file handling, not the definition of
    what a core is.

    **A shrinking core is refused, not written.** Intersection is monotonic, so a
    build lacking a route removes it for every build. That is breaking under
    AS-23.
    """
    from agent_spec.openapi.core import core_document, shrinkage

    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob(f"*-{version}.json"))
        # **The core is in the same namespace as its own inputs**, so the glob
        # that finds the implementations finds it too. Feeding it back in would
        # make the intersection idempotent-looking and hide a build that lost a
        # leaf.
        if not path.name.startswith("core-")
    ]
    if not documents:
        return
    core = core_document(documents)
    target = directory / f"core-{version}.json"
    # A snapshot's own core file is scratch, not a baseline -- see the long
    # comment on the Claude build's `_write_core`, which this mirrors. The
    # short version: a new implementation joining narrows the intersection and
    # that is the measurement; AS-23 protects against narrowing while the set of
    # implementations is unchanged, and only a published core can tell those
    # apart. The check therefore belongs to the cut.
    baseline = target if (target.is_file() and "-snapshot" not in version) else None
    if baseline is not None:
        lost = shrinkage(json.loads(baseline.read_text(encoding="utf-8")), core)
        if lost:
            raise SystemExit(
                f"REFUSING to shrink the core: {len(lost)} leaf/leaves would be "
                f"removed, which is breaking under AS-23 and needs a version and "
                f"a notice. First few:\n  " + "\n  ".join(lost[:10])
            )
    target.write_text(_pretty(core), encoding="utf-8")
    print(f"  {target}  (core of {len(documents)} implementation document(s))")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--out-dir",
        default=None,
        help="write here instead of the version's directory under spec/",
    )
    args = ap.parse_args()

    from agent_service.versions import IMPLEMENTATION_NAME

    version, document_json = _openapi()
    out = Path(args.out_dir) if args.out_dir else _version_dir(version)
    out.mkdir(parents=True, exist_ok=True)

    target = out / f"{IMPLEMENTATION_NAME}-{version}.json"
    target.write_text(document_json, encoding="utf-8")
    print(f"  {target}  ({len(document_json):,} bytes)")
    _write_core(out, version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
