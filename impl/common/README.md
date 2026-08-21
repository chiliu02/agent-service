# `impl/common/` — what the SPECIFICATION determines, never what the SDK does

Things every implementation needs that are **not part of any implementation**.

```
agent-spec/  the specification as pydantic models -- these GENERATE the document
web/         console.html + serve.py -- a dev console that speaks /v1 only
db/          init/01-roles.sql       -- the agent_service / agent_readonly split
             alembic.ini migrations/ -- the schema's GENERATOR (Plan 9 step 2)
```

## The one rule

**Share what the SPECIFICATION determines. Never share what the SDK
determines.**

The line falls almost exactly where the SDK imports do. In `claude-python`, five
modules import `claude_agent_sdk` — `sessions`, `runner`, `options`, `policy`,
`errors`, about 1,834 lines. **Those may never be shared.** The other ~6,000 do
not, and are candidates.

**This rule replaced "never importable code" on 2026-08-07**, and the reason it
had to is worth keeping. `schemas.py` has zero SDK imports and is the 1,023
lines that **generate the published OpenAPI document**. AS-24 requires every
implementation to serve that document exactly, and
`test_the_published_spec_file_matches_this_version_of_the_app` enforces it
byte-for-byte — so **two hand-maintained copies are a specification violation
that ships**, not a duplication that annoys. Refusing to share it would have
been the more dangerous discipline.

**The package name is the guard.** It is `agent_spec`, not `common` or `shared`:
you cannot justify putting a Codex notification mapper in a package called
`agent_spec`, and its `pyproject.toml` depends on **pydantic and nothing else**.
A dependency appearing there is the signal that something implementation-shaped
is being smuggled in.

**What is still forbidden**, and this half of the old rule stands: no shared
base classes for the SDK layer, no "just this one helper" that happens to be
useful twice, no common package a fourth implementation in another language
could not use. `plan-8-design.md` step 7 still applies — *sharing a language is
not a licence to share code* — it just is not the whole rule.

**What generalises lives in `spec/`**, and it is the specification, the
conformance suite and `/v1/capabilities` — not code. If two implementations need
the same logic, that is a sign the *specification* should say something, not that
a library should appear here.

## What is here, and why each qualifies

### `web/` — a client, not an implementation

`serve.py` is standard library only and imports nothing from any implementation;
`console.html` calls `/v1/*` and nothing else. **It drives any conforming
build**, including one written in another language, which is exactly what makes
it common rather than Claude's.

It deliberately names no implementation in its error messages, for the same
reason. It lived under `impl/claude-python/` until 2026-08-07 and told a failing
user to run `uvicorn agent_service.main:app` — advice that would send a Codex or
Gemini user to start the wrong thing.

Dev tool only: no auth, conversation lost on reload. See `docs/plans.md` Plan 6.

```bash
python impl/common/web/serve.py               # proxies to http://127.0.0.1:8000
```

### `db/migrations/` and `db/alembic.ini` — operator tooling, and Python

**The sharpest test this directory's rule has faced, and it survives it by being
sharpened rather than bent** (Plan 9 §3.3, 2026-08-08).

Alembic migrations *are* Python, and this README's rule was once "never
importable code".

**This section first replaced that with "nothing an implementation imports at
runtime", and that was wrong within a screen of itself** — `agent-spec` is
imported at runtime by every build, and it is the largest thing in this
directory. Corrected 2026-08-08, the same day, after the question *"so part of
the db layer moves to common?"* made the contradiction visible.

**There is no single rule, and pretending otherwise is what produced a false
one.** Three distinct justifications admit something here, and a candidate needs
exactly one of them:

| Admitted because… | What is here | Imported at runtime? |
|---|---|---|
| **the SPECIFICATION determines it** | `agent-spec` — AS-24 requires every build to serve a byte-identical document, so two hand-maintained copies are a violation that *ships* | **yes**, and that is fine |
| **it is TOOLING nobody imports** | `db/migrations/`, `db/alembic.ini`, `db/init/`, `web/` | **no**, and that is the whole claim |
| **MORE THAN ONE implementation needs it** (user, 2026-08-08) | persistence, once it is extracted | **yes** |

### The third one is new, and it reverses something this file argued

**"Shared by all implementations" was never the requirement, and reading it as
one was this file's mistake.** Until 2026-08-08 the argument against a shared
persistence layer ended with *"no common package a fourth implementation in
another language could not use"* — which sets the bar at **every** implementation
and therefore at the least capable one. Under it, two Python builds must
hand-maintain two copies of the same thing because a hypothetical TypeScript
build could not import either.

**The bar is "more than one", and a package usable by only the Python builds
qualifies.** A third implementation in another language reimplements it, exactly
as it would reimplement everything else — and it is no worse off than if the
duplication had been left in place, which is the point. What it loses is nothing;
what two Python builds gain is one copy instead of two.

**What is still forbidden has not moved: anything that encodes ONE SDK's
shapes.** That is the original rule — *never share what the SDK determines* —
and the relaxation is about how many implementations must benefit, not about
what may be shared. A module that reads a Claude turn outcome does not become
shareable by being useful twice; it becomes shareable by being rewritten to read
what the *specification* defines.

The migrations qualify under the second justification, because **no service ever
runs them** — that is not an aspiration, it is enforced
three ways: `grep alembic src/` returns nothing, the images ship neither
`alembic.ini` nor `migrations/`, and the 0.10.0 revision gate exists precisely to
refuse a container whose database was migrated to the wrong place. `ci.py`
applies them itself, before starting any service. **Alembic here is `psql` with
a version number.**

They are shared for the reason the DDL they render is published: **persistence is
a feature of `agent-service`, not of any agent SDK.** The tables store what `/v1`
returns, Studio's D-08 has one schema for the whole fleet, and the revision gate
compares a single `alembic_version` — three things that were already assuming a
common schema while the tree that produced it sat inside one implementation.

**One migration tree serving a shared database is not a shared library.** If that
distinction ever stops being obvious, the question to ask is the rule above: does
a running service import it? The answer must stay no.

**The artifact is NOT here.** The rendered DDL is published at
`spec/snapshots/schema/agent-service-<revision>.sql`, beside the OpenAPI documents,
because it is what a consumer is handed. This directory holds the generator. Same
split as `dump-schema.py` and `spec/snapshots/openapi/`.

### `db/init/` — SQL, and language-neutral by construction

`01-roles.sql` creates the two-role split every implementation needs for the
same reason: **the agent has `Bash` and is therefore inside the service's trust
boundary**, so the service role and any role the agent might ever hold must be
different. That argument is about the agent, not about the SDK, so it is as true
for Codex and Gemini as for Claude.

Mounted at `/docker-entrypoint-initdb.d` by an implementation's own
`compose.yaml`. It runs **once, on an empty data directory** — editing it does
nothing to an existing deployment.

Kept in one place because three copies of a role grant that must match what each
service connects as is a drift waiting to happen.

## What is NOT here, and why

**`impl/claude-python/scripts/dump-schema.py` stays where it is.** It does
`from agent_service.api import create_app` — it imports the implementation, so it
*is* the implementation's. Every build needs its own, and that is correct rather
than wasteful.

**Note what that means now that it writes two platform artifacts.** Being the
generator of a shared thing does not make the generator shared: producing either
file needs a working implementation — `create_app().openapi()` for the document,
an installed `alembic` for the DDL. Ownership follows who the artifact is *for*,
not who can produce it.

**`src/agent_service/db/` stays in the implementation too**, and Plan 9 §5 says so
in as many words. Those six modules — `wiring`, `writer`, `recorder`,
`repository`, `queries`, `session_store` — are an ORM layer that *conforms to* the
schema; they are not the schema. Moving them here would be the shared-package
refactor this README forbids, and it would look identical to Plan 9 at a glance.

## For `ci.py`'s implementation loops

**`impl/common/` is not an implementation and must be skipped.** `UNIT_IMPLS` and
`CONTAINER_IMPLS` are explicit lists rather than a glob of `impl/*` for exactly
that reason — a glob would try to build a container from this directory.

**But `ci.py` does address `impl/common/db/` directly**, and that is not a
contradiction: it is where the Alembic tree lives, so the `container` stage
points `alembic -c` at it and `freeze` reads the revision head out of it.
Addressed as tooling, never enumerated as an implementation.

Written down here rather than discovered then.
