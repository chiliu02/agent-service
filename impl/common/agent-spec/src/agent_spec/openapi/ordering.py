"""One canonical order for `paths`, so isomorphism is VISIBLE and not merely true.

**AS-31 makes the builds structurally identical; this makes them look it.** The
core is an intersection and `conformance_failures` compares leaves by dotted
path, so both are entirely order-insensitive — three documents can satisfy every
clause and still list their operations in three different orders, which is
exactly what happened.

## What went wrong without it

FastAPI writes `paths` in **route-registration order**, so the JSON key order was
whichever order the decorators happened to run in `api.py`:

    claude-python   meta  query  sessions  history
    gemini-python   meta  query  sessions  history
    codex-python    meta  sessions  query  history

Nothing chose that and nothing caught it: `freeze` hashes each document against
its own published copy, the core is a set intersection, and AS-24's check is a
**dict** comparison, which in Python ignores key order. Two builds agreeing was a
coincidence, not a convention.

**It is not cosmetic once you try to read them side by side.** A textual diff of
codex's document against either of the others shows a large block move that has
no meaning, and the reader has to establish that by inspection every time.

## Why an explicit list rather than a sort

Sorting alphabetically would put `/v1/runs/{run_id}` between `/v1/query` and
`/v1/sessions`, which is tidy and says nothing. The order below is the API's own
story — discover it, open a session and drive it, or skip all that with a
one-shot, then read back what happened — and **the tag grouping is real here in a
way it was not before**: the old orders interleaved `history` into the middle of
the session block, and only Swagger's own grouping hid that.

Adding a route means adding it here, deliberately, in the place a reader would
look for it.
"""

from __future__ import annotations

from typing import Any

#: Every path the specification defines, in the order every build publishes them.
#:
#: **Grouped by tag, and lifecycle-ordered within each group.** `sessions` comes
#: before `query` because it is the primary surface and `query` is the shortcut
#: past it; `history` comes last because it reads back what the others produced.
CANONICAL_PATHS: tuple[str, ...] = (
    # meta -- what this service is, before you use it
    "/healthz",
    "/v1/deployment",
    # ... and the same deployment's `accepts`, rendered for a validator. It
    # follows the payload it is derived from rather than sitting under a
    # `schemas` heading of its own: a reader meets the fact, then its other
    # shape.
    "/v1/schemas/run-options",
    # sessions -- open, inspect, change, drive, stop, close
    "/v1/sessions",
    "/v1/sessions/{sid}",
    "/v1/sessions/{sid}/messages",
    "/v1/sessions/{sid}/messages/stream",
    "/v1/sessions/{sid}/interrupt",
    # query -- the same turn with no session to manage
    "/v1/query",
    "/v1/query/stream",
    # history -- reading back what was recorded
    "/v1/sessions/{sid}/transcript",
    "/v1/runs/{run_id}",
)

_RANK = {path: index for index, path in enumerate(CANONICAL_PATHS)}


def canonical(document: dict[str, Any]) -> dict[str, Any]:
    """`document` with its `paths` in `CANONICAL_PATHS` order.

    **A shallow copy**: the operations themselves are shared with the original,
    because only the ordering of the `paths` mapping changes.

    **An unlisted path is appended, not rejected.** Raising would turn adding a
    route into a 500 on `/openapi.json` in a running service, which is a worse
    failure than an out-of-place entry — so the loud part lives in a test
    instead (`test_document_paths_are_in_canonical_order`, one per build), where
    a new route fails CI at the moment it is added and the fix is one line here.
    """
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return document
    ordered = dict(
        sorted(paths.items(), key=lambda item: (_RANK.get(item[0], len(_RANK)),))
    )
    return {**document, "paths": ordered}


def enforce_canonical_order(app: Any) -> None:
    """Make `app.openapi()` return the canonical order, and keep it cached.

    **Applied in the app rather than at publication time**, which is the whole
    point: `scripts/dump-openapi.py` writes what the service serves, so ordering
    only on the way out would leave the live document and the published file
    disagreeing — and AS-24's dict comparison would not notice.
    """
    build = app.openapi

    def openapi() -> dict[str, Any]:
        schema = canonical(build())
        # FastAPI caches here and `build()` returns the cache on later calls, so
        # writing the ordered document back makes this idempotent.
        app.openapi_schema = schema
        return schema

    app.openapi = openapi
