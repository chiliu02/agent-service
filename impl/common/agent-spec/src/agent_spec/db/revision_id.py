"""The Alembic head, as a bare string and nothing else.

**This module imports NOTHING, and that is its whole purpose.**

`revision.py` beside it holds the boot gate that compares a live database
against this value, and importing that module pulls SQLAlchemy. Two callers
cannot afford it:

* **the pre-boot specification** -- `spec.py` reads this value as
  `schema_revision` and it is published in each build's own OpenAPI document,
  so an operator can answer *will this image accept my database* before
  creating a container. It was a command in an image whose service cannot
  start until 0.19.0, which is why the constraint exists at all; it is kept
  because a heavy import on this path buys nothing;
* **a build with no database configured** -- plan-03's global constraint says
  `agent_service` must not import SQLAlchemy when nothing is persisted, and it
  is pinned by a fresh-interpreter test rather than by an in-process check,
  because `sys.modules` is already poisoned once any other test has run.

So the constant lives here, the gate lives there, and there is still exactly one
of it. Splitting the file is what keeps that true: the alternative is a second
copy in each build, test-pinned to this one, which is a copy either way.

**BUMP THIS IN THE SAME COMMIT AS A NEW REVISION.**
`tests/test_schema_gate.py::test_the_expected_revision_is_the_alembic_head`
fails otherwise, which is what makes a hand-written constant safe.

**The tree it is pinned against is `impl/common/db/`**, shared by every
implementation that persists -- so this is no build's private opinion of the
schema. They migrate one database between them, and three images disagreeing
about it is what the gate exists to catch.
"""

from __future__ import annotations

EXPECTED_REVISION = "d3f9a0c15e27"
