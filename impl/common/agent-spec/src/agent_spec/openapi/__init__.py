"""The OpenAPI half of the specification: the models that GENERATE the document.

**These models ARE the published document.** `openapi-<version>.json` is
generated from them, AS-24 freezes it once published, and
`test_the_published_spec_file_matches_this_version_of_the_app` fails the build
if a running service serves anything else.

## Why a subpackage, since 2026-08-08

The specification publishes **two** artifacts, and both are now rendered here:

    agent_spec.openapi.schemas  ->  spec/openapi-<ver>-<impl>.json
    agent_spec.db               ->  schema/schema-<rev>.sql

AS-24 makes the first the specification's; **AS-30 makes the second the
specification's too** -- persistence is a feature of `agent-service` rather than
of any agent SDK, so the tables that store what `/v1` returns are specified
rather than left to each build to invent.

**Splitting them also ends a collision this repository had lived with.**
`agent_spec.schemas` (as it was called) meant *the API models* while
`schema/` meant
*the DDL* -- one word, two things, in a codebase that has already paid twice for
exactly that (`provider`, and `contract`). `openapi` and `db` cannot be
confused.

**Deliberately no re-exports here.** A `from .schemas import *` would carry
pydantic's own names (`BaseModel`, `Field`, `Any`) into this namespace, and a
hand-maintained `__all__` is one more list to keep in step with a 1,000-line
module. Callers name the module:

    from agent_spec.openapi.schemas import RunResponse
"""
