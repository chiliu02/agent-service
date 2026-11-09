"""Write the OpenAPI document and the PostgreSQL DDL to files.

    uv run python scripts/dump-schema.py     # -> the version's directory under
                                             #    ../../spec/, and
                                             #    ../../schema/
    uv run python scripts/dump-schema.py --out-dir dist     # both, into one place
    uv run python scripts/dump-schema.py --openapi-only

**Both destinations are under `spec/`, and neither is arbitrary.** The OpenAPI
document went there in Plan 8 step 4 and the DDL in Plan 9 step 2, for the same
reason each time: it is what a consumer is handed, and what another
implementation has to satisfy rather than reinvent.

The DDL took longer to get there because it *looked* like this build's private
business. It is not -- persistence is a feature of `agent-service`, not of any
agent SDK; the tables store what `/v1` returns; and Studio has been told to run
`alembic upgrade head` against a schema this side had never shipped them.

**This script lives in the implementation and writes two platform artifacts, and
that asymmetry is deliberate.** Generating either one needs an implementation:
`create_app().openapi()` for the document, an installed `alembic` for the DDL.
Being the generator is not the same as being the owner.

Both are produced **offline**: no running service, no database, no
credentials. `create_app()` only builds the app -- the credential check lives
in the lifespan, which `.openapi()` never runs -- and Alembic's `--sql` mode
renders migrations without connecting.

## Why this is a script rather than two shell redirects

Both one-liners work, but three details are easy to get wrong and silent when
you do:

* **Encoding.** PowerShell's `>` and `Out-File` write UTF-8 *with a BOM* here,
  which breaks strict JSON parsers and can upset `psql`. Writing from Python
  sidesteps the shell entirely.
* **`-x url=`.** `migrations/env.py` requires the value to be present but never
  connects to it in offline mode. Omitting it fails; supplying a real one
  implies a connection that does not happen.
* **Which SQL.** The Alembic output is what a deployment actually applies,
  including the `alembic_version` bookkeeping table. The models' own DDL is a
  different artifact -- see `--from-models`.

`tests/test_migrations.py::test_the_migrations_and_the_models_agree` is what
keeps those last two in step; if they ever diverge, that test is the one to
believe.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The platform root is two levels above this implementation. **Both artifacts
#: belong to the specification rather than to this build** -- the OpenAPI
#: document since Plan 8 step 4, the DDL since Plan 9 step 2.
#: **No version directories any more** (user, 2026-08-19). `spec/` carries
#: exactly one version -- the current one -- and every version before it lives in
#: its `release-<version>` git tag. **The tag is the freeze**, and the spec jar,
#: the schema jar and the three images are all built from it.
SPEC = ROOT.parents[1] / "spec"
SPEC_SCHEMA = SPEC / "database"


def _version_dir(version: str) -> Path:  # noqa: ARG001
    """Where this version's documents belong: **`spec/openapi/`.**

    Takes a version and ignores it, and stays a function for two reasons: the
    call sites read better for naming the version they are writing, and this
    layout has changed twice already.

    **The schema is not versioned this way** and stays at `schema/`, named
    by Alembic revision: most versions change no schema, so filing the DDL under
    versions would make the platform's schema reachable only by knowing which
    release shipped it.
    """
    return SPEC / "openapi"

#: The Alembic tree, which belongs to no implementation either: it is the
#: GENERATOR of the DDL above, and operator tooling like `psql`. Nothing under
#: `src/` imports it and the image ships neither it nor `alembic.ini`.
ALEMBIC = ROOT.parent / "common" / "db"

# Never connected to. `migrations/env.py` only requires the key to exist; in
# offline mode Alembic renders SQL without opening a connection.
_UNUSED_URL = "postgresql://unused/unused"


def _openapi() -> tuple[str, str]:
    """Return (version, pretty JSON)."""
    from agent_service.api import create_app

    spec = create_app().openapi()
    return spec["info"]["version"], json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def _pretty(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _write_core(directory: Path, version: str) -> None:
    """Recompute `openapi-<version>-core.json` from every implementation document present.

    **Derived from what is COMMITTED, not from every app in one process** (Plan 8
    step 6). Cutting a version would otherwise require every implementation to be
    installable at once -- and a Gemini or TypeScript build never will be.
    Whichever implementation regenerates last produces the complete core; a
    directory holding one document yields that document's own structure, which is
    the honest core while one build exists.

    **A SHRINKING core fails here rather than being written.** Intersection is
    monotonic, so a build that lacks a route silently removes it for everyone --
    see `agent_spec.openapi.core`. Losing a leaf is a breaking change under
    AS-23 and needs a decision, so this refuses and names what would go.
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
    # **The baseline is a PUBLISHED core, never this directory's own file.**
    #
    # A snapshot is never frozen -- that is the whole point of the suffix -- so
    # the file sitting here is scratch from the last regeneration, and comparing
    # against it makes the guard fire on its own intermediate states. It did,
    # immediately, the first time a second implementation's document joined:
    # eight leaves "disappeared", all of them status codes the Claude build
    # declares and the Codex build has measurably no path to.
    #
    # **That narrowing is the measurement, not a regression.** A new
    # implementation joining SHOULD narrow the intersection; what AS-23 protects
    # against is a core that shrinks while the set of implementations is
    # unchanged, which is a build having got weaker. The two are
    # indistinguishable from a scratch file and trivially distinguishable from a
    # published one.
    #
    # So the check belongs to the CUT, where a real baseline exists: the previous
    # version's published core. Cutting is the user's decision and carries this
    # comparison with it.
    baseline = target if (target.is_file() and "-snapshot" not in version) else None
    if baseline is not None:
        lost = shrinkage(json.loads(baseline.read_text(encoding="utf-8")), core)
        if lost:
            raise SystemExit(
                f"REFUSING to shrink the core: {len(lost)} leaf/leaves would be "
                f"removed, which is a breaking change under AS-23 and needs a "
                f"version and a notice. First few:\n  "
                + "\n  ".join(lost[:10])
            )
    target.write_text(_pretty(core), encoding="utf-8")
    print(f"  {target}  (core of {len(documents)} implementation document(s))")




def _migration_sql(target: str = "head") -> tuple[str, str]:
    """Delegated to `agent_spec.db.testing.render_ddl`.

    **It used to live here, and a second copy appeared the day the persistence
    tests moved into the shared package** -- that package needs to render the
    DDL to check the published file against the migrations, and reaching into
    one implementation's `scripts/` to do it would be exactly backwards. Two
    renderers of one published artifact is a drift waiting to happen, so there
    is one, and it is in the package that owns the schema.
    """
    from agent_spec.db.testing import render_ddl

    return render_ddl(target)


def _header(revision: str, source: str, extra: str = "") -> str:
    """Delegated too, for the same reason -- see `_migration_sql`."""
    from agent_spec.db.testing import ddl_header

    return ddl_header(revision, source, extra)


def _models_sql() -> str:
    """The schema as the ORM models define it -- NOT what gets deployed.

    Omits `alembic_version` and anything a revision does outside the metadata.
    Useful for diffing against the migration output; not for applying.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from agent_spec.db import Base

    dialect = postgresql.dialect()
    out: list[str] = []
    for table in Base.metadata.sorted_tables:
        out.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            out.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n\n".join(out) + "\n"



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # TWO defaults, and since Plan 9 step 2 they are siblings: both artifacts
    # are the SPECIFICATION's, one in the version's own directory and one under
    # `schema/`. There is no canonical `openapi/` directory -- see
    # SPEC_SNAPSHOTS above, which has said so since 2026-08-08 while these two
    # strings went on naming one. `--out-dir` overrides BOTH, which is what makes
    # `--out-dir dist` still mean "put everything somewhere I can look at it" --
    # and is the flag to reach for when you want to inspect a rendering without
    # touching a published, frozen file.
    ap.add_argument(
        "--out-dir",
        default=None,
        help="write both artifacts here instead of their separate defaults "
        "(the version's directory under spec/, and schema/)",
    )
    ap.add_argument("--openapi-only", action="store_true")
    ap.add_argument("--sql-only", action="store_true")
    ap.add_argument(
        "--from-models",
        action="store_true",
        help="render DDL from the ORM models instead of the migrations "
        "(no alembic_version; not what a deployment applies)",
    )
    ap.add_argument(
        "--revision",
        default="head",
        help="which Alembic revision to render up to, from base (default: head). "
        "Needed only to reproduce a DDL file for a revision that is no longer "
        "the head; the published set is one file per revision.",
    )
    args = ap.parse_args()

    if args.openapi_only and args.sql_only:
        print("--openapi-only and --sql-only are mutually exclusive", file=sys.stderr)
        return 2

    override = Path(args.out_dir) if args.out_dir else None
    sql_out = override or SPEC_SCHEMA
    sql_out.mkdir(parents=True, exist_ok=True)

    # THREE VERSION STREAMS NOW, and using the wrong one publishes a file
    # nobody will look for.
    #
    #   DOCUMENT version  (spec/VERSION, what the app serves as info.version)
    #       names openapi-<version>.json                        -- Plan 8 step 5
    #   ALEMBIC revision  (the migration tree's head)
    #       names agent-service-<revision>.sql                         -- Plan 9 step 1
    #   BUILD version     (pyproject.toml)
    #       names NEITHER artifact any more
    #
    # The DDL stopped being named by the build version because three
    # implementations at three build versions cannot each name one shared
    # schema: `agent-service-0.16.0.sql` means nothing once codex-python is at 0.3.0.
    # The revision is the stream that moves exactly when the schema does.
    version, spec_json = _openapi()

    if not args.sql_only:
        # The version's own directory, created if absent -- for a snapshot this
        # is the step that creates it. For a release the CUT creates it, by
        # renaming the snapshot, and `_version_dir` is what makes this follow.
        openapi_out = override or _version_dir(version)
        openapi_out.mkdir(parents=True, exist_ok=True)
        # **The filename carries the IMPLEMENTATION since Plan 8 step 6.** AS-24
        # keys the published document to the version *and* the build, because two
        # implementations cannot serve one byte-identical document while the
        # document also documents behaviour -- and relaxing AS-24 to containment
        # instead would break the transfer that lets nine clause predicates run
        # on a bare checkout with no service.
        from agent_service.versions import IMPLEMENTATION_NAME

        target = openapi_out / f"{IMPLEMENTATION_NAME}-{version}.json"
        target.write_text(spec_json, encoding="utf-8")
        print(f"  {target}  ({len(spec_json):,} bytes)")
        _write_core(openapi_out, version)

    if not args.openapi_only:
        if args.from_models:
            # Still rendered at the head revision's shape, and named for it --
            # the models are what the head migration was written from, so any
            # other pairing would be a file whose name lies about its content.
            revision, _ = _migration_sql(args.revision)
            body = _models_sql()
            source = "the ORM models (agent_service.db.Base.metadata)"
            extra = "Excludes alembic_version. Not the deployed schema."
            target = sql_out / f"schema-{revision}-models.sql"
        else:
            revision, body = _migration_sql(args.revision)
            source = "the Alembic revisions"
            extra = ""
            target = sql_out / f"agent-service-{revision}.sql"
        target.write_text(_header(revision, source, extra) + body, encoding="utf-8")
        print(f"  {target}  ({len(body):,} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
