"""Write this implementation's OpenAPI document, and refresh the core.

    uv run python scripts/dump-openapi.py            # -> the version's directory
                                                     #    under ../../spec/
    uv run python scripts/dump-openapi.py --out-dir dist

**Offline.** No running service, no credential, no agent: `create_app()` only
builds the app, and the boot gates live in the lifespan, which `.openapi()`
never runs. That is what makes the published document producible in a container
that could not start.

**No SQL here, unlike the other two builds' generators.** The DDL belongs to the
specification and is generated from `agent-spec`; this build adds no tables of
its own, so there is nothing for it to render.

**The core is recomputed from what is on DISK**, not from every app in one
process. So the sequence that produces a complete `openapi-<version>-core.json` is: run
each implementation's generator, in any order, and the last one to run computes
the intersection over all the documents present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: The platform root's `spec/`. Two levels up from this build.
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
    """Return `(document version, pretty JSON)`.

    Built with settings that name no credential and no real workspace: nothing
    here reaches the filesystem or the agent, and a generator that needed either
    could not run where this one must.
    """
    from agent_service.api import create_app
    from agent_service.config import Settings

    settings = Settings(
        workspace_dir=ROOT / "workspace",
        agent_home_root=ROOT / "temp" / "agent-home",
        transcript_store=ROOT / "temp" / "transcripts",
        gemini_binary=Path("gemini"),
        require_credentials=False,
    )
    document = create_app(settings).openapi()
    return document["info"]["version"], _pretty(document)


def _write_core(directory: Path, version: str) -> None:
    """Recompute `openapi-<version>-core.json` from every implementation document present.

    **The logic lives in `agent_spec.openapi.core`**, which all three builds
    call; what is repeated per build is the file handling, not the definition of
    what a core is.

    **A shrinking core is refused rather than written.** Intersection is
    monotonic, so a build lacking a route removes it for every build, which is
    breaking under AS-23. A snapshot's core is scratch and is exempt: a NEW
    implementation joining legitimately narrows the intersection, and that is
    the measurement rather than a regression — only a published core can tell
    the two apart, so the check belongs to the cut.
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
    baseline = target if (target.is_file() and "-snapshot" not in version) else None
    if baseline is not None:
        lost = shrinkage(json.loads(baseline.read_text(encoding="utf-8")), core)
        if lost:
            raise SystemExit(
                f"REFUSING to shrink the core: {len(lost)} leaf/leaves would be "
                "removed, which is breaking under AS-23 and needs a version and "
                "a notice. First few:\n  " + "\n  ".join(lost[:10])
            )
    target.write_text(_pretty(core), encoding="utf-8")
    print(f"  {target}  (core of {len(documents)} implementation document(s))")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=None,
                    help="write here instead of the version's directory under spec/")
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
