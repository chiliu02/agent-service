"""Everything this repository can check for free, in one command.

    uv run python .ci/ci.py            # all five stages
    uv run python .ci/ci.py --fast     # freeze + links + tests, no Docker
    uv run python .ci/ci.py --stages freeze,container
    uv run python .ci/ci.py --serial-unit   # unit suites one at a time, streaming

**ONE runner for the whole platform.** It lives at the platform root and the
implementations live under `impl/`. Every `uv`/`docker` command below runs with
an implementation directory as its working directory, because that is where
`pyproject.toml`, `compose.yaml` and `alembic.ini` are; git and the
documentation stages run from the platform root.

**Three lists, not one, and they are different lengths on purpose.** `IMPL` is
the reference implementation and is what `freeze` reads a version and a
`schema/` from. `UNIT_IMPLS` is every directory with a test suite.
`CONTAINER_IMPLS` is every directory with a Dockerfile, which since 2026-08-08
is two -- that is Plan 8 step 7, arriving one stage at a time rather than all at
once. A directory can be in one list and not the next, and `gemini-python` (in
none of them) is what that looks like.

**Two roots, and one of them collides.** `tests/`, `schema/`, `src/` and
`spike/` exist only under the implementation, so a bare mention of one below is
implementation-relative and needs no prefix. `docs/` exists at BOTH levels, so
it is always written out: `docs/…` is the platform's,
`impl/claude-python/docs/…` is the implementation's.

There is no CI SERVICE. This repository has no git remote (`git remote -v` is
empty), and the decision on 2026-08-06 was to keep it that way and drive the
same stages locally instead. So this file is "the CI", and the only thing that
runs it is you.

## The five stages

| stage       | what it proves                                      | needs   |
|-------------|-----------------------------------------------------|---------|
| `freeze`    | no published document was edited after publication  | git     |
| `links`     | every relative link and `#anchor` in the docs resolves | nothing |
| `unit`      | the in-process suite + the conformance document tier | Docker* |
| `container` | the conformance suite against a REAL container, in  | Docker  |
|             | BOTH deployments -- with a database and without     |         |
| `gates`     | the boot gates: misconfigured images exit 3         | Docker  |

\\* `unit` uses Docker only because `tests/dbharness.py` starts a Postgres when
`AGENT_SERVICE_TEST_DATABASE_URL` is unset. `--fast` passes `-m "not postgres"`
and needs no daemon.

## Nothing here can spend money

`pyproject.toml` sets `addopts = "-m 'not live'"`, so every pytest invocation
below deselects the paid tier, and no stage passes `-m live` or unsets that.
The CI container is additionally booted with **no `ANTHROPIC_API_KEY` at all**
(see `_write_env_file`) and `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, which
`docs/dev-todo.md` §1 records as measured to pass the free conformance tier
21/21. Running the paid tier stays a command you type by hand.

## Why Python and not a shell script

The repository's other script is Python
(`impl/claude-python/scripts/dump-schema.py`), the primary host is Windows while
the Bash tool is also present, and a `.sh`/`.ps1` pair would drift.
`dump-schema.py`'s docstring already records that PowerShell's `>`
writes a BOM; the same class of surprise applies to writing an env file, which
this does.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import tokenize
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: The platform root -- the PARENT of the directory this file sits in. git, the
#: documentation stages and `spec/` are addressed from here.
#:
#: `.parent.parent`, and the second one is load-bearing: this file lived at the
#: repository root until 2026-08-07 and moved into `.ci/` so that the root shows
#: three directories and nothing else. Every path in this module is built from
#: `ROOT`, so getting this wrong does not fail loudly -- it silently addresses
#: `.ci/impl`, `.ci/spec` and a git repository that is not there, and the
#: stages report everything as missing rather than as broken.
ROOT = Path(__file__).resolve().parent.parent

#: THE REFERENCE implementation -- the one with a container, a database and the
#: published `schema/`. Everything container-shaped still points here:
#: `compose*.yaml`, `alembic.ini`, the `container` and `gates` stages.
IMPL = ROOT / "impl" / "claude-python"

#: Every implementation whose UNIT SUITE runs, in order. Plan 8 step 7 turns the
#: container stage into a loop too; this is the half that is cheap today,
#: because a unit suite needs no daemon.
#:
#: **`impl/common/` is deliberately absent and must stay absent**: it is assets
#: and clients, not an implementation, and a glob of `impl/*` would try to build
#: a container from it. Listed explicitly rather than globbed for exactly that
#: reason.
#:
#: A directory with no `pyproject.toml` is SKIPPED rather than failed -- an
#: implementation can be started as notes before it is a project, which is what
#: `gemini-python` is today. The count is printed so a suite that silently
#: stopped being collected is visible.
UNIT_IMPLS: tuple[str, ...] = (
    "claude-python",
    "codex-python",
    "gemini-python",
    # **NOT an implementation, and it is here anyway** (2026-08-08). It is the
    # specification rendered in Python -- `agent_spec.openapi` generates the
    # published document, `agent_spec.db` conforms to the published DDL -- and
    # since the persistence layer moved into it, it is ~1,200 lines with 25
    # tests of its own. A shared layer whose tests live in one implementation is
    # a layer only that implementation keeps honest.
    #
    # The comment above still holds for `container`/`gates`: `CONTAINER_IMPLS`
    # must never gain this entry, because there is no image to build from it.
    "common/agent-spec",
)

#: How many unit suites run AT ONCE. Five today -- four implementations and the
#: conformance document tier -- so this is "all of them" and the cap is only a
#: ceiling for whatever is added next.
#:
#: **They are safe to overlap, and that was checked rather than assumed.** Each
#: is a separate process with its own virtualenv; none binds a socket (every
#: suite drives its app through an in-process ASGI transport at
#: `http://test`); and every suite that needs a directory or a subprocess takes
#: it from a per-test `tmp_path`. The one resource genuinely shared is the
#: Postgres that `impl/claude-python/tests/dbharness.py` starts outside `--fast`,
#: and it is shared with nothing -- no other suite has a database.
#:
#: **The cap is not sized against CPUs on purpose.** What `unit` spends is
#: WAITING, not computing: timeout budgets, courtesy-interrupt windows, and the
#: app-server that `impl/codex-python`'s session fixture spawns and tears down
#: per test. Measured 2026-08-17, serial: claude 33.0s + codex 32.5s + gemini
#: 16.7s + the two small suites = 87.4s of an 92.9s `--fast` run. Sleeping
#: processes do not need a core each.
UNIT_MAX_WORKERS = 5

#: How many xdist workers `IMPL`'s suite gets, and **only under `--fast`** --
#: see the comment at the `-n` in `stage_unit`, which is where the safety
#: argument lives.
#:
#: **A fixed number rather than `-n auto`, because `auto` is wrong here twice
#: over.** It reads the whole machine (14 cores on this host) and would claim it
#: for one of five suites that are already running at once; and it is measured
#: against a suite whose cost is waiting, where workers stop paying long before
#: they run out of cores. Measured alone, 2026-08-17: 33.0s at `-n 1`, 14.3s at
#: 4, 14.3s at 6, 10.5s at 8.
#:
#: **The ceiling on this number is flakiness, not throughput.** The suite
#: asserts budgets by letting them elapse, and a dozen of those assertions are
#: UPPER bounds -- `elapsed < 0.05` is the tightest. Every worker added makes a
#: scheduling stall likelier, so this is set below what the clock alone would
#: justify and is verified by repeated runs under the concurrent stage rather
#: than alone.
#:
#: **4 rather than 8, and the reason is that no suite is the pole for long.**
#: For `claude-python`, 4 and 6 measured identically (14.3s) and 8 gave 10.5s;
#: for `codex-python`, 11.6s / 9.7s / 9.1s. In both cases the suite drops below
#: the next-slowest one well before the workers stop helping, and a stage cannot
#: go below its longest member -- so the extra workers buy the STAGE nothing and
#: are spent purely on contention and flake risk. Raise this only when the
#: longest suite is one of these two.
UNIT_XDIST_WORKERS = 4

#: Builds whose suite is distributed in EVERY mode, not only under `--fast`.
#:
#: **`claude-python` is deliberately absent, and the asymmetry is the point.**
#: Its Postgres tests share one server and one schema, so it gets workers only
#: on the branch that has just deselected them -- see the `-n` in `stage_unit`.
#: The builds listed here have no database and nothing else shared: no
#: `conftest.py`, no session- or module-scoped fixture in `tests/`, and every
#: session takes its agent state and workspace from a per-test `tmp_path`.
#: There is nothing for two workers to contend over, so there is no branch.
#:
#: **A new build does NOT belong here by default.** Earn the entry by checking
#: for shared state first; the cost of being wrong is a flake, which is the
#: expensive kind of wrong.
#:
#: **`gemini-python` is here for consistency and not for the clock** (user,
#: 2026-08-17), which is worth saying because the measurement says the opposite
#: of what the entry implies: its suite goes 16.4s -> 6.3s and the STAGE DOES
#: NOT MOVE -- 21.2s mean before (n=7), 21.3s after (n=12). The stage is
#: CPU-bound now, 4 workers per build on a 14-core host, so a third build's
#: workers come out of the other two's share and the other two slowed to pay for
#: it (claude 18.4 -> 20.2s, codex 13.0 -> 17.3s).
#:
#: **The spread is +/-3s, several times any effect worth looking for**, so a
#: handful of runs can show a gain, a loss or nothing -- an earlier 4-vs-6-run
#: sample read as a 1s gain and was noise. A dozen runs per arm is the minimum
#: for a number here to mean anything, which is itself a reason not to tune this
#: further. Recorded so the next person does not re-run the experiment expecting
#: the earlier builds' result.
UNIT_XDIST_ALWAYS: tuple[str, ...] = ("codex-python", "gemini-python")

#: `IMPL` as a posix repo-relative prefix, for the paths handed to git and for
#: anything printed. `Path.relative_to` on Windows yields backslashes and git
#: pathspecs want forward ones.
IMPL_REL = IMPL.relative_to(ROOT).as_posix()

#: Its own compose project, so every container, network and volume this creates
#: is namespaced away from a stack the operator is already running. It is also
#: what `down -v` scopes to -- see `_teardown`.
PROJECT = "agentsvc-ci"

#: Not 8000. `compose.yaml` publishes 127.0.0.1:8000 and this stack has to be
#: able to run beside it; `compose.ci.yaml` reads both of these.
#:
#: There is no `IMAGE` constant any more: compose builds `<project>-<service>`,
#: and since two projects exist that name is `Containerised.image` below. It is
#: needed by name because `spec/conformance/test_boot_gates.py` refuses to
#: default the image -- this machine carries other `agent-service` tags that
#: serve older versions and boot with no credential, and a default silently
#: measured the wrong one.
CI_HOST_PORT = 8100

#: The out-of-band migration route, and it is **below 49152 on purpose** since
#: 2026-08-19. It was 55440, chosen only to miss the 55433 the developer docs
#: suggest -- which put it inside Windows' dynamic range, where Hyper-V reserves
#: hundred-port blocks and hands nothing back. One of those blocks
#: (55365-55464) swallowed it: compose could not bind Postgres, the persistence
#: sub-stage died with `ports are not available` before a test ran, and the
#: whole `container` stage failed while every test in it was fine. The
#: reservations move across a reboot, so the old value was a stage that fails on
#: a schedule nobody controls rather than a stage that was broken.
CI_PG_PORT = 15432


@dataclass(frozen=True)
class Containerised:
    """One implementation that ships an image, for the `container` and `gates`
    stages. Added 2026-08-08, when `codex-python` gained a Dockerfile.

    **Every field here is a thing the two builds do not share**, which is the
    reason this is a record rather than four parallel constants: a per-field
    dict keyed by name is the shape that lets one of them drift out of step
    with the others silently.
    """

    #: The directory under `impl/`, and the working directory for its compose
    #: commands.
    name: str

    #: Its own compose project, so two implementations' stacks can be up at the
    #: same time without sharing a network or colliding on a container name.
    project: str

    #: The published host port, matching its `compose.ci.yaml` default.
    host_port: int

    #: Whether it has a `persistence` profile, and therefore whether the
    #: `container` stage runs a second pass with a database behind it.
    #:
    #: **All three, as of 2026-08-12** -- Claude since plan-03, Codex since
    #: 2026-08-08, Gemini since the entry below. The comment here used to say
    #: "only the Claude build does today" and was two builds out of date, which
    #: is worth noticing: a `false` in a record like this reads as a decision
    #: long after it has become a leftover.
    persistence: bool

    #: The variable that moves this build's model endpoint, and the credential
    #: the redirect check hands it. **The names are here rather than read from
    #: the image on purpose**: this check exists to catch a build whose published
    #: `endpoint_source` no longer works, and asking the build under test which
    #: variable to use would let it answer with the one it happens to honour.
    endpoint_env_var: str
    credential_env_var: str

    #: A syntactically plausible credential that authenticates nothing. It never
    #: leaves the container -- the endpoint is redirected at a sink on this
    #: machine before the turn is taken -- but the CLIs reject a value of the
    #: wrong shape before making a request, which would pass this check for the
    #: wrong reason.
    credential_dummy: str

    #: `None` when the LIVE conformance tier is expected to pass. Otherwise the
    #: reason it is not run, printed on every run.
    #:
    #: **This is not a mute button and it must not become one.** A string here
    #: says a build is measured to fail clauses that a decision has yet to be
    #: made about -- the failures are real, they are recorded in that build's
    #: `docs/spec-divergence.md`, and the image is still BUILT and still passes
    #: the boot-gate tier on every run. What it must never mean is "this
    #: implementation's failures are acceptable"; the moment the decision lands,
    #: the entry goes and the tier runs.
    live_tier_blocked_by: str | None

    @property
    def path(self) -> Path:
        return ROOT / "impl" / self.name

    @property
    def image(self) -> str:
        """Compose's `<project>-<service>`, which `gates` needs by name."""
        return f"{self.project}-agent-service"


#: Every implementation with a Dockerfile. `gemini-python` is absent because it
#: is notes rather than a project, and `common/` because it is assets rather
#: than an implementation -- the same reason `UNIT_IMPLS` is a list and not a
#: glob of `impl/*`.
CONTAINER_IMPLS: tuple[Containerised, ...] = (
    Containerised(
        name="claude-python",
        project=PROJECT,
        endpoint_env_var="ANTHROPIC_BASE_URL",
        credential_env_var="ANTHROPIC_API_KEY",
        credential_dummy="sk-ant-ci-not-a-real-key",
        host_port=CI_HOST_PORT,
        persistence=True,
        live_tier_blocked_by=None,
    ),
    Containerised(
        name="gemini-python",
        project=f"{PROJECT}-gemini",
        endpoint_env_var="GOOGLE_GEMINI_BASE_URL",
        credential_env_var="GEMINI_API_KEY",
        # The shape matters: this CLI refuses a value that does not look
        # like a Google key before it makes any request.
        credential_dummy="AIzaSyCiCiCiCiCiCiCiCiCiCiCiCiCiCiCiC",
        # 8120, because 8100 and 8110 are the other two stacks' CI ports and a
        # full run has all three up at once -- or up in sequence against a port
        # the previous teardown has not fully released.
        host_port=8120,
        # TRUE since 2026-08-12. It was false while this build had no database
        # at all, and the negative control in `stage_container`'s docstring is
        # exactly why flipping it matters: against a no-database stack only one
        # of the two 404 conditions is reachable, so an implementation that
        # hard-coded the disabled `type` onto every 404 would pass. This build
        # now returns both, and only the database pass can tell them apart.
        #
        # **What a database buys here is HISTORY, never continuity** -- this
        # agent resumes from a `--session-file` on disk, so the rows are a
        # record and never a source.
        persistence=True,
        live_tier_blocked_by=None,
    ),
    Containerised(
        name="codex-python",
        project=f"{PROJECT}-codex",
        endpoint_env_var="OPENAI_BASE_URL",
        credential_env_var="OPENAI_API_KEY",
        credential_dummy="sk-ci-not-a-real-key",
        host_port=8110,
        # TRUE since 2026-08-08: this build persists. The container stage now
        # runs BOTH deployments against it, which is what makes the
        # two-kinds-of-404 negative control reachable here as well.
        persistence=True,
        # **NOTHING BLOCKS IT ANY MORE, as of 2026-08-09.** Measured against a
        # container built from this tree: **53 passed, 0 failed, 13 skipped.**
        #
        # It took four separate fixes and the order is the interesting part,
        # because each one made the next measurable:
        #
        #   nine failures  AS-13/14/15/20 + AS-24
        #   -> one         0.18.0 made AS-13 conditional on
        #                  `allow_supplied_sdk_session_id` and restated AS-15
        #   -> one         codex-python persisting took 123 keys off AS-24
        #   -> one         declaring the statuses it can actually produce took
        #                  the delta to 55 keys, 42 of them prose
        #   -> zero        Plan 8 step 6: the document is published PER
        #                  IMPLEMENTATION, so AS-24 compares a build against its
        #                  own document instead of against the other build's
        #
        # **The last step is the one that mattered and it was not a relaxation.**
        # AS-24 still demands byte equality -- it just names the right pair. The
        # 55-key delta is still there and is now where it belongs: between two
        # implementations' documents, governed by AS-31 (structural identity to
        # `openapi-<version>-core.json`, which both satisfy with zero failures) and AS-32
        # (a behavioural difference is published on `/v1/capabilities`).
        #
        # Leave this `None`. A string here means a tier is not running, and a
        # tier that is silently not running is indistinguishable from one that
        # passes.
        live_tier_blocked_by=None,
    ),
)

#: Throwaway, on loopback, in a volume destroyed at the end of the run. It is
#: written to a gitignored file under `temp/`, never to `.env`.
CI_PG_PASSWORD = "ci-not-a-secret"

#: How long the redirect check waits for a turn to reach its sink. Generous
#: because a cold agent starts a subprocess and negotiates before it sends
#: anything, and the wait ENDS at the first request rather than running out --
#: a healthy build satisfies it in a few seconds and only a broken one pays it.
REDIRECT_TURN_TIMEOUT_S = 120

#: `temp/<name>/`, per CLAUDE.md: every temporary directory belongs under
#: `temp/`, and `.gitignore` covers it with the same `temp/*` + negation form
#: the workspace mount uses.
CI_TEMP = ROOT / "temp" / "ci"

#: The acceptance suite, which since Plan 8 step 3 is the SPECIFICATION's and its own
#: uv project -- pytest and httpx, no implementation. Every pytest invocation
#: against it therefore passes `cwd=CONFORMANCE`, not `cwd=IMPL`.
#:
#: `testpaths = ["."]` in its `pyproject.toml` means the whole suite runs with
#: no path argument; `BOOT_GATES` is named only so the two halves can be split,
#: the `container` stage ignoring it and the `gates` stage running just it.
CONFORMANCE = ROOT / "spec" / "conformance"
BOOT_GATES = "test_boot_gates.py"

#: The Alembic tree, which since Plan 9 step 2 belongs to no implementation.
#:
#: **It is the GENERATOR, not the artifact.** The DDL it renders is published at
#: `schema/` beside the OpenAPI documents, because persistence is
#: a feature of `agent-service` rather than of any agent SDK and a consumer is
#: told to apply it (`docs/to-agent-harness/image-0.10.0-available.md`: *"Apply
#: out of band, as D-11 requires: `alembic upgrade head`"*). The tree that
#: produces it is operator tooling, like `psql` -- **no implementation imports
#: it at runtime**, and the images ship neither it nor `alembic.ini`, which is
#: what the 0.10.0 revision gate exists to keep true.
ALEMBIC = ROOT / "impl" / "common" / "db"


# ---------------------------------------------------------------------------
# process plumbing
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None
) -> int:
    """Run a command with its output going straight to this terminal.

    Deliberately NOT captured. A stage that fails should show pytest's own
    report or compose's own error where you are already looking, rather than
    being re-rendered by this file.

    `cwd` defaults to `IMPL` and not to `ROOT`, which is the opposite of what it
    was before the implementation moved down a level. Every caller here is a
    `uv` or `docker compose` invocation, and all of those need the directory
    holding `pyproject.toml` / `compose.yaml`. A platform-level command would
    have to pass `cwd=ROOT` explicitly; none does yet.
    """
    # Quoted, because the arguments that matter most here are the ones that
    # contain spaces -- `-m "not postgres"` printed bare reads as two flags and
    # is not a command you could paste back.
    print(f"\n$ {' '.join(shlex.quote(part) for part in cmd)}", flush=True)
    full = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd or IMPL, env=full).returncode


def _run_captured(
    cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None
) -> tuple[int, str]:
    """`_run`, but holding the child's output instead of streaming it.

    **This does not weaken the rule above it.** `_run`'s reason for streaming is
    that a failing stage should show pytest's own report rather than one this
    file re-rendered -- which is a rule about the bytes being UNMODIFIED, not
    about when they arrive. Nothing here parses, filters or reformats: the
    caller prints exactly what came back.

    It exists because `unit` runs its suites CONCURRENTLY, and concurrent
    children streaming into one terminal interleave into a transcript in which
    no report can be read -- which would break that rule far worse than delay
    does.

    `stderr` is merged into `stdout` rather than captured beside it, so a
    warning printed between two test lines stays between them. Two streams
    concatenated afterwards would reorder the output of the very run someone is
    reading to debug.
    """
    full = {**os.environ, **(env or {})}
    result = subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd or IMPL,
        env=full,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    return result.returncode, result.stdout


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _port_is_busy(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


#: **`_pyproject_version()` was removed here by Plan 9 step 1**, and its absence
#: is the point rather than a tidy-up. It existed to name `schema/`'s in-flight
#: DDL file, and the build version is the wrong stream for a schema that three
#: implementations share. Nothing this runner freezes is named by a build version
#: any more: the OpenAPI document is named by `spec/VERSION`, the DDL by the
#: Alembic head. The build version is still published -- at
#: `capabilities.impl.version`, where it says what a container IS rather than
#: what it promises -- and `impl/claude-python/tests/test_api_meta.py` pins that
#: edge.


def _document_version() -> str:
    """The SPECIFICATION's version, which since Plan 8 step 5 is its own stream.

    `spec/VERSION` is the source of truth. The implementation repeats it in
    `agent_service/versions.py` because a container has no access to this file,
    and `impl/claude-python/tests/test_api_meta.py` is what stops the two
    drifting.
    """
    return (ROOT / "spec" / "VERSION").read_text(encoding="utf-8").strip()


#: `revision = "abc123"` / `down_revision = "def456"` at module level in an
#: Alembic revision file. Tolerates either quote style and the `Union[...]`
#: annotation Alembic's template emits on `down_revision`.
_REVISION_RE = re.compile(
    r"^(revision|down_revision)\s*(?::[^=]+)?=\s*['\"]?([0-9a-f]+)['\"]?",
    re.MULTILINE,
)


def _alembic_head() -> str:
    """The head revision of the migration tree, by reading it.

    **Parsed rather than imported, and that is not laziness.** This file is
    stdlib-only on purpose -- it must be able to drive an implementation that is
    not Python at all -- so it cannot `import alembic`, and shelling out to
    `uv run alembic heads` would make the `freeze` stage depend on a synced
    virtualenv for a string that is sitting in two files.

    The head is the revision that is nobody's `down_revision`. With a linear
    history that is the last one; the set arithmetic is what makes it also
    correct if a branch is ever merged, and it fails loudly rather than guessing
    if there is more than one.

    Plan 9 step 1: this is what `schema/`'s in-flight file is exempted by, in
    place of `pyproject.toml`'s version.
    """
    revisions: set[str] = set()
    parents: set[str] = set()
    versions = ALEMBIC / "migrations" / "versions"
    for path in sorted(versions.glob("*.py")):
        for key, value in _REVISION_RE.findall(path.read_text(encoding="utf-8")):
            (revisions if key == "revision" else parents).add(value)
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(
            f"expected exactly one Alembic head under {versions}, found "
            f"{sorted(heads) or 'none'}. `freeze` cannot decide which DDL file "
            f"is in flight until that is resolved."
        )
    return heads.pop()


# ---------------------------------------------------------------------------
# stage: freeze
# ---------------------------------------------------------------------------

#: The release manifest. `spec/README.md` carries a table of
#: `| version | tag | commit |` -- one row per delivered version. **The tag is
#: the freeze** (user, 2026-08-19): there are no version directories any more,
#: `spec/` holds the current version alone, and everything a release ships is
#: built from its tag.
#:
#: This reads the table rather than restating the pairs here -- a second list
#: would be a second thing to keep in step, which is the failure mode the table
#: already has.
RELEASE_MANIFEST = Path("spec/README.md")
_SHA1 = 40


def _release_manifest() -> list[tuple[str, str, str]]:
    """`(version, tag, recorded commit sha)` from the table in `spec/README.md`.

    Rows are recognised by shape rather than by position: three cells, the third
    a full 40-character sha1. A heading or a prose table cannot match that, so
    the parser needs no anchor and survives the README being rewritten around
    it.
    """
    text = (ROOT / RELEASE_MANIFEST).read_text(encoding="utf-8")
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        version, tag, commit = cells
        if len(commit) == _SHA1 and all(c in "0123456789abcdef" for c in commit):
            rows.append((version, tag, commit))
    return rows


def _check_release_tags() -> list[str]:
    """Every recorded tag still points where the manifest says it does.

    **This is the whole of AS-24 now, and it is stronger than what it replaces.**
    A version used to be a directory that a stage watched for edits; a directory
    can be edited, and the watch was a walk over git history looking for a
    content commit after a freeze point. A tag names an immutable commit, so the
    bytes cannot change at all -- the only remaining way to alter a delivered
    version is to MOVE the tag, and that is exactly what this catches.

    **A missing tag is a failure and not a warning.** A row in the manifest is a
    claim that a version was delivered; if the tag is gone, either the claim is
    false or the tag was deleted, and both need a person.
    """
    failures: list[str] = []
    for version, tag, recorded in _release_manifest():
        resolved = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{}}"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        if resolved.returncode != 0:
            failures.append(
                f"{tag} does not exist. `spec/README.md` says {version} was "
                f"delivered at {recorded[:9]}; without the tag the only copy of "
                f"that delivery is an unnamed commit. Restore it with "
                f"`git tag -a {tag} {recorded}`."
            )
            continue
        actual = resolved.stdout.strip()
        if actual != recorded:
            failures.append(
                f"{tag} has MOVED -- it points at {actual[:9]} and "
                f"`spec/README.md` records {recorded[:9]}. A release tag is the "
                f"freeze; moving one changes what a delivered version means, "
                f"and every artifact built from it now disagrees with the "
                f"manifest."
            )
            continue
        print(f"  released   {version}  {tag} @ {actual[:9]}")
    return failures


def _content_commits(rel: str) -> list[tuple[str, int]]:
    """Commits that CHANGED this file's content, oldest last. Renames excluded.

    **Plan 8 step 1 broke the previous form of this and the fix is the honest
    one.** It read `git log --format=%H -- <path>` and required exactly one
    commit. Moving the implementation into `impl/claude-python/` renamed every
    published document, and a plain `git log` on a path stops at the rename:
    before the migration commit it returns NOTHING ("not committed"), and after
    it returns the migration commit and reports every file as freshly published.
    Either way the rule stopped meaning what it says.

    `--follow` crosses the rename, and `--numstat` is what separates a move from
    an edit -- measured on a rename this repository already had:

        C 4da161e9
        0    0    docs/specification/{ => 0.5.1}/openapi-0.5.1.json
        C b7be5fc
        2360 0    docs/specification/openapi-0.5.1.json

    A pure rename adds and deletes nothing. So "written once and never edited"
    becomes exactly one commit with a nonzero line count anywhere in the
    followed history, which is what the rule always meant and is now insensitive
    to where the file lives.

    **`-M100%` is load-bearing and was found by this stage going red.** With
    git's default similarity threshold, `--follow` walks off the file: the
    published documents are successive versions of the same OpenAPI surface and
    are therefore near-identical, so git read the *addition* of
    `openapi-0.9.0.json` as a rename of `openapi-0.8.0.json`, and that as a
    rename of 0.7.0, all the way back to the commit that created `schema/`.
    Every file reported between 2 and 6 "content commits" and the stage failed
    on nine of sixteen. At 100% only a byte-identical move is followed -- which
    is exactly what a move is, and what a new version of a document is not.

    A binary file reports `-`/`-` rather than counts; that is read as a change,
    which is the safe direction. Nothing under `schema/` is binary today.
    """
    commits: list[tuple[str, int]] = []
    current: str | None = None
    stamp = 0
    log = _git("log", "--follow", "-M100%", "--format=%H %ct", "--numstat", "--", rel)
    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" not in line:
            current, _, raw = line.partition(" ")
            stamp = int(raw)
            continue
        added, deleted, _ = line.split("\t", 2)
        if current is not None and (added, deleted) != ("0", "0"):
            commits.append((current, stamp))
            current = None
    return commits


def _first_commit_time(rel: str) -> int | None:
    """When this file was ADDED, as a committer timestamp. `None` if untracked."""
    log = _git(
        "log", "--follow", "-M100%", "--diff-filter=A", "--format=%ct", "--", rel
    ).split()
    return int(log[-1]) if log else None


def stage_freeze() -> bool:
    """A delivered version is never edited (AS-24), and **the tag is the freeze**.

    **This stage was rewritten on 2026-08-19 (user) and is now a fraction of its
    old size**, because the layout it policed is gone. There used to be a
    directory per version under `spec/`, and a delivery was protected by walking
    git history for a content commit after the version moved on. That was real
    work and it was defending a weak position: a directory can be edited, and
    the walk could only notice afterwards.

    Now `spec/` carries the current version alone and every delivered version
    lives in its `release-<version>` git tag. Git makes the bytes immutable, so
    there is nothing to watch. **The one remaining way a delivered version can
    change is a MOVED TAG**, and `spec/README.md` records the commit each tag
    pointed at so that a move is visible. That is the openapi half of this stage
    now, and it is a stronger guarantee than the one it replaces.

    Three checks:

    1. **Every recorded release tag still resolves to its recorded commit.**
    2. **`spec/` carries exactly one version.** Two would mean a cut left a file
       behind, and a consumer reading the directory could not tell which is the
       specification.
    3. **A bare `spec/VERSION` must be tagged.** Main is always a `-snapshot`;
       the bare state exists at exactly one commit, the one the tag names. A
       bare version anywhere else is a cut that was never tagged, or a bump back
       to the next snapshot that was forgotten -- and either way an artifact
       built here would claim to be a release and be built from an unnamed
       commit.

    **The DDL keeps the old machinery**, unchanged, because its stream did not
    move: `spec/database/agent-service-<revision>.sql` is named by Alembic revision, a
    revision's DDL is written once, and the file at the current head is still in
    flight until a new revision appears.

    **`git diff` and not a byte comparison**, on purpose. Git for Windows sets
    `core.autocrlf=true` globally, and `.gitattributes` here is narrow enough
    that it says nothing about `schema/` -- so a blob's bytes and the working
    tree's bytes legitimately differ on this host. `git diff` applies the same
    filters git itself would, which is the comparison that means "unchanged".
    """
    failures: list[str] = []
    frozen = 0

    failures += _check_release_tags()

    # --- the current version, in `spec/` itself ------------------------------
    spec = ROOT / "spec" / "openapi"
    current = _document_version()
    documents = sorted(spec.glob(f"*-{current}.json"))
    stray = [p.name for p in sorted(spec.glob("*.json"))
             if not p.name.endswith(f"-{current}.json")]
    if stray:
        failures.append(
            f"spec/openapi/ carries a document for a version other than {current}: "
            f"{', '.join(stray)}. One version lives here and it is the one "
            f"`spec/VERSION` names; every other version is in its tag."
        )

    if "-snapshot" in current:
        print(f"  in flight  spec/  ({current} -- a snapshot is never frozen)")
    else:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip()
        tagged = subprocess.run(
            ["git", "rev-parse", f"release-{current}^{{}}"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        if tagged.returncode != 0:
            print(f"  cutting    spec/  ({current} is bare and release-{current} "
                  f"does not exist yet)")
        elif tagged.stdout.strip() != head:
            failures.append(
                f"spec/VERSION is the bare {current} and release-{current} names "
                f"a different commit ({tagged.stdout.strip()[:9]}, HEAD is "
                f"{head[:9]}). Either the cut moved on without bumping to the "
                f"next snapshot, or the tag is stale. Main is always a "
                f"`-snapshot`; the bare state belongs to one commit only."
            )
        else:
            print(f"  cut        spec/  ({current} @ release-{current})")

    # --- the DDL stream, which did not change --------------------------------
    candidates = [
        (path.relative_to(ROOT).as_posix(), path, "schema", _alembic_head())
        for path in sorted((ROOT / "spec" / "database").glob("agent-service-*.sql"))
    ]

    added: dict[str, tuple[str, int]] = {}
    for rel, _path, stream, _current in candidates:
        when = _first_commit_time(rel)
        if when is not None:
            added[rel] = (stream, when)

    def _frozen_at(rel: str) -> int | None:
        """The add-time of the next file published in the same STREAM."""
        if rel not in added:
            return None
        stream, mine = added[rel]
        later = [
            when for other, (s, when) in added.items() if s == stream and when > mine
        ]
        return min(later) if later else None

    for rel, path, _stream, revision in candidates:
        version = path.stem.removeprefix("agent-service-")
        if version == revision:
            print(f"  in flight  {rel}  (revision {revision} is still being cut)")
            continue

        commits = _content_commits(rel)
        if not commits:
            failures.append(
                f"{rel} is not committed. Every published artifact must be in "
                f"git -- a fresh clone that lacks it makes AS-24's promise "
                f"false, which is exactly what the old `schema/` ignore rule "
                f"cost (see .gitignore)."
            )
            continue

        horizon = _frozen_at(rel)
        if horizon is not None:
            after = [c for c, when in commits if when > horizon]
            if after:
                failures.append(
                    f"{rel} was edited AFTER it was published -- {len(after)} "
                    f"commit(s) changed it once a later revision existed. A "
                    f"published DDL is frozen from that moment; a change to its "
                    f"content needed a new revision, not an edit.\n"
                    f"      {'  '.join(c[:9] for c in after)}"
                )
                continue

        diff = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", rel],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if diff.returncode != 0:
            failures.append(
                f"{rel} differs from what git has for it. Restore it with "
                f"`git checkout HEAD -- {rel}` and publish the change under a "
                f"new revision instead. Its newest content commit is "
                f"{commits[0][0][:9]}."
            )
            continue

        frozen += 1
        print(f"  frozen     {rel}  @ {commits[0][0][:9]}")

    for problem in failures:
        print(f"  FAIL       {problem}")
    print(f"\n  {len(_release_manifest())} released version(s) verified at their "
          f"tags; {frozen} frozen DDL file(s) verified unchanged.")
    return not failures



# ---------------------------------------------------------------------------
# stage: links
# ---------------------------------------------------------------------------

#: Markdown files this stage checks, per level: the named trees plus the two
#: files at `<level>/` itself. The rest of the tree is code, and a path in a
#: code comment is prose rather than a link.
#:
#: TWO levels since Plan 8 step 1, and it has to be both: the platform's `docs/`
#: and the implementation's `docs/` link ACROSS the boundary (`../../docs/ci.md`
#: one way, `../impl/claude-python/docs/design.md` the other), which is exactly
#: the class of link a move breaks. Checking one level would leave half of them
#: unread.
#:
#: `spec/` is named explicitly because Plan 8 step 2 moved it OUT of `docs/` --
#: and a stage that silently stopped reading the signed bundle would be the
#: worst possible way to lose this check, since that is the one directory whose
#: links cannot be repaired by editing it.
#:
#: The outbox went out with it and came back on 2026-08-07, so it is covered by
#: the `docs` entry again rather than named. Worth knowing rather than
#: rediscovering: this tuple is the whole list of what `links` reads, so a
#: directory that leaves `docs/` needs adding here in the same commit.
_LINK_ROOTS = ("README.md", "CLAUDE.md")
#: **`docs/<build>/` is under the platform level since 2026-08-09** (user), so
#: every implementation document except the guide is scanned by the first entry
#: rather than needing one of its own. What is left under an implementation is
#: `docs/<build>-guide.md`, which still needs scanning -- and `codex-python`
#: needed adding, because it had never been scanned at all: its documents were
#: in a tree no level named, so a broken link in any of them was invisible to
#: this stage for as long as that build has existed.
_LINK_LEVELS: tuple[tuple[Path, tuple[str, ...]], ...] = (
    (Path("."), ("docs", "spec")),
    (Path("impl") / "claude-python", ("docs",)),
    (Path("impl") / "codex-python", ("docs",)),
)

#: ```fenced``` and ~~~fenced~~~ blocks, removed BEFORE scanning. This is not
#: tidiness: the claude build's references file contains a probe
#: transcript line reading
#: `AssistantMessage[model=...](tool_use(PowerShell ...))`, which is
#: indistinguishable from a markdown link to a regex. The ad-hoc version of this
#: check reported it as broken and the finding was hand-waved away as a "false
#: positive" -- which is the exact habit that makes a checker worthless.
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def _slug(heading: str) -> str:
    """GitHub's heading slug, near enough for a link check.

    **The underscore is KEPT, and that is the whole reason this is a function
    with a comment rather than an inline regex.** The ad-hoc checker used
    `[^a-z0-9 -]`, which drops `_`, so
    `#max_budget_usd-is-blind-to-interrupted-turns--measured` was compared as
    `maxbudgetusd...` and reported dead. It was not: `deployment.md` has that
    heading and five documents link to it correctly. Every anchor containing an
    underscore was a false negative until 2026-08-07.

    Not modelled: GitHub's `-1`, `-2` suffixes for repeated identical headings.
    No document here has two identical headings, and a wrong PASS on that case
    is better than teaching this function a rule nobody is relying on.
    """
    return re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")


#: Directory names never descended into. `.venv` is the one that bit: Plan 8
#: step 3 gave `spec/conformance/` its own uv project, `uv sync` put a
#: virtualenv inside a tree this stage scans, and the next run checked the links
#: in three third-party `LICENSE.md` files. Harmless that time and not in
#: general -- a dependency's README is somebody else's document, and this stage
#: going red because of one would be a check nobody could act on.
_LINK_SKIP = frozenset(
    {".venv", "__pycache__", ".pytest_cache", "node_modules", ".git"}
)


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for level, trees in _LINK_LEVELS:
        base = ROOT / level
        files += [base / name for name in _LINK_ROOTS]
        for tree in trees:
            files += sorted(
                path
                for path in base.joinpath(tree).rglob("*.md")
                if _LINK_SKIP.isdisjoint(path.parts)
            )
    return [f for f in files if f.is_file()]


def _anchors(path: Path) -> set[str]:
    text = _FENCE.sub("", path.read_text(encoding="utf-8", errors="replace"))
    return {_slug(h) for h in _HEADING.findall(text)}



#: Documents whose names may appear in a code comment. Nothing else may.
#:
#: **The rule (user, 2026-08-10): code cites ONE document per build, by ID.**
#: 170 code citations pointed at 14 documents and 50 were unusable one hour
#: after a directory move -- 31 bare filenames that resolve nowhere, 19 broken
#: paths, and 49 heading anchors nothing verified. None of it was visible to any
#: stage, because `links` reads markdown and citations live in prose.
#:
#: **A temp document is never a citation target.** `dev-todo.md` and `plans.md`
#: are written to be superseded and code outlives them.
_REFERENCE_DOCS = {
    "claude-python": "impl/claude-python/docs/claude-python-references.md",
    "codex-python": "impl/codex-python/docs/codex-python-references.md",
    #: **A build with no code yet, and it is still in this table.** gemini-python
    #: is probes and evidence; the rule applies from the first file rather than
    #: from the first `src/`, because the citations that rotted were written
    #: before anyone thought of them as load-bearing.
    "gemini-python": "impl/gemini-python/docs/gemini-python-references.md",
}

#: `(CX-07)`, and nothing longer. The prefix is per build: `CP` claude, `CX`
#: codex, `GP` gemini.
_REF_ID = re.compile(r"\b(C[XP]-\d{2,3}|GP-\d{2,3})\b")

#: The same set, anchored to a heading, for reading a references file's own IDs.
_REF_HEADING = re.compile(r"^##+\s*~?~?(C[XP]-\d{2,3}|GP-\d{2,3})", re.M)

#: Any path-shaped mention of a markdown file. `http` lines are skipped by the
#: caller: an SDK's documentation URL is not this rule's business.
_DOC_PATH = re.compile(r"[\w./-]*[\w-]+\.md(?:#[\w-]+)?")

#: **A markdown file the PRODUCT reads at runtime is not a citation.** `AGENTS.md`
#: is what Codex loads from a thread's `cwd` and `CLAUDE.md` is its Claude
#: equivalent -- naming one is naming a feature, the way `.env` is. They can no
#: more rot than a function name can, because the code that reads them is the
#: thing under discussion.
#:
#: `README.md` is here for a different reason: it is the file *beside* the code,
#: it moves with it, and no path reaches it. That is the one citation this rule
#: has nothing to fix.
_RUNTIME_FILES = {"AGENTS.md", "CLAUDE.md", "README.md"}

#: `(tree, build)`. A build's tree cites that build's references file; a tree
#: with `None` cites **nothing at all**.
#:
#: **The two `None` entries are the important ones.** `spec/conformance/` is the
#: suite that measures both implementations, and one that cites a build's
#: document has picked a reference implementation without saying so -- the exact
#: neutrality failure four of its own boot-gate assertions already committed by
#: naming one SDK's environment variables. `impl/common/` is shared by both, so
#: any document it names is the wrong one for one of its callers.
_SCANNED: tuple[tuple[str, str | None], ...] = (
    ("impl/claude-python", "claude-python"),
    ("impl/codex-python", "codex-python"),
    ("impl/gemini-python", "gemini-python"),
    ("impl/common", None),
    ("spec/conformance", None),
)

#: `#` comments in a non-Python file. Compose files and Dockerfiles carry the
#: same kind of prose as a module docstring and rot the same way; `deployment.md`
#: was cited from `compose.yaml` eleven times.
def _hash_comments(path: Path) -> list[tuple[int, str]]:
    return [
        (number, line)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if line.lstrip().startswith("#")
    ]


def _prose(path: Path) -> list[tuple[int, str]]:
    """`(line number, text)` for every comment and docstring in a module.

    **Prose only, and that is the whole distinction this rule turns on.** A path
    in executable code -- `tests/test_config.py` reads a document to check that
    every setting is described in it -- either resolves or fails a test the next
    time it runs. A path in a comment resolves to nobody and fails nothing, which
    is how 50 of them rotted unnoticed. Log messages are exempt for the same
    reason and a second one: their reader is outside the tree, where a
    repository-relative path is the only thing they can act on.
    """
    source = path.read_text(encoding="utf-8")
    out = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        first = 1 if isinstance(node, ast.Module) else node.body[0].lineno
        out += [(first + offset, text) for offset, text in enumerate(doc.splitlines())]
    return sorted(out)


def stage_references() -> bool:
    """Code may cite its build's references file, by ID, and nothing else.

    Two failures, and the second is the one that rots silently:

    * a **path-shaped** citation in code -- it will be wrong the next time
      anything moves, and no other stage looks at prose;
    * an **ID that does not resolve** to a heading in the references file.

    **Not a style check.** Every defect this rule exists to prevent was found by
    accident rather than by CI, which is the same shape as a capability nothing
    enforces -- published, believed, and false.
    """
    problems: list[str] = []
    known: dict[str, set[str]] = {}

    for build, rel in _REFERENCE_DOCS.items():
        doc = ROOT / rel
        if not doc.exists():
            problems.append(f"{rel} is missing; {build} has nowhere to cite")
            known[build] = set()
            continue
        text = doc.read_text(encoding="utf-8")
        known[build] = set(_REF_HEADING.findall(text))
        # Rule 2: the references file itself links to nothing. Fenced blocks
        # come out first for the reason `links` does it -- a probe transcript
        # is indistinguishable from a link to a regex.
        for link in _LINK.findall(_FENCE.sub("", text)):
            if not link.startswith("#"):
                problems.append(f"{rel} links out to {link} -- references files link to nothing")

    # **Only files git TRACKS are policed.** The rule is about what this
    # repository ships, and a walk of the working tree also finds whatever a
    # local run left behind: the Codex app-server unpacks 65 vendor skill files
    # into its gitignored `codex-home/` the first time it starts, and two of
    # them cite `SKILL.md`, which failed this stage for a developer who had
    # merely run the service. `.venv` was already special-cased for the same
    # reason; tracking is the general form of that guard and needs no list.
    #
    # Falls back to walking everything if git cannot answer, so this stays
    # usable outside a checkout.
    tracked: set[str] | None = None
    try:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
        tracked = {line.strip() for line in listed.splitlines() if line.strip()}
    except (OSError, subprocess.CalledProcessError):
        tracked = None

    for tree, build in _SCANNED:
        for path in sorted((ROOT / tree).rglob("*")):
            if ".venv" in path.parts or path.suffix not in (".py", ".yaml", ".yml") and path.name != "Dockerfile":
                continue
            if tracked is not None and path.relative_to(ROOT).as_posix() not in tracked:
                continue
            if path.is_dir():
                continue
            rel = path.relative_to(ROOT).as_posix()
            lines = _prose(path) if path.suffix == ".py" else _hash_comments(path)
            for number, line in lines:
                if "http" in line:
                    continue
                for match in _DOC_PATH.finditer(line):
                    cited = match.group(0)
                    if cited.rsplit("/", 1)[-1] in _RUNTIME_FILES:
                        continue
                    hint = "cite an ID instead" if build else "this tree cites no document"
                    problems.append(f"{rel}:{number} cites {cited!r} -- {hint}")
                for cid in _REF_ID.findall(line):
                    if build is None:
                        problems.append(f"{rel}:{number} cites {cid}; this tree is build-neutral")
                    elif cid not in known[build]:
                        problems.append(f"{rel}:{number} cites {cid}, which has no entry")

    for problem in problems:
        print(f"  FAIL       {problem}")
    total = sum(len(v) for v in known.values())
    print(f"\n  {total} reference ID(s); {len(problems)} problem(s).")
    return not problems


def stage_links() -> bool:
    """Every relative link and every `#anchor` in the documentation resolves.

    **Why this is a stage and not a habit.** The documents cross-reference each
    other constantly -- that is the house style, and it is what makes the
    reasoning followable -- so a moved file breaks readers silently. Three moves
    happened in two days (`spec/` into per-version directories, then
    `llm-provider-and-auth.md` into `draft/`), each repaired by hand and
    verified with a throwaway script retyped from memory. One of those scripts
    was wrong. This is that check, written down once.

    **External links are deliberately NOT checked.** `http(s)` needs the
    network, is slow, and fails for reasons that have nothing to do with this
    repository. A stage that goes red because a third party had an outage stops
    being read.

    **It covers the signed bundle too, and that is a feature.**
    A delivered version cannot be edited -- AS-24 -- so if a link inside it
    ever breaks, the fix is to put back whatever moved, not to touch the
    document. That is the correct outcome, and this stage is what forces it
    rather than leaving it to someone noticing.
    """
    failures: list[str] = []
    checked = 0

    for md in _markdown_files():
        raw = md.read_text(encoding="utf-8", errors="replace")
        text = _INLINE_CODE.sub("", _FENCE.sub("", raw))
        rel = md.relative_to(ROOT).as_posix()

        for match in _LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            checked += 1
            path, _, fragment = target.partition("#")
            resolved = (md.parent / path) if path else md
            if path and not resolved.exists():
                failures.append(f"{rel} -> {target}  (no such file)")
                continue
            if fragment and resolved.is_file() and resolved.suffix == ".md":
                if fragment not in _anchors(resolved):
                    failures.append(f"{rel} -> {target}  (no such heading)")

    for problem in failures:
        print(f"  FAIL       {problem}")
    print(
        f"  {checked} relative link(s) across {len(_markdown_files())} file(s); "
        f"{len(failures)} broken."
    )
    return not failures


# ---------------------------------------------------------------------------
# stage: unit
# ---------------------------------------------------------------------------


def stage_unit(*, fast: bool, serial: bool = False) -> bool:
    """EVERY implementation's in-process suite, plus the specification's
    no-service tier.

    **It loops since 2026-08-07**, when `codex-python` gained tests. A suite
    this runner does not run is a suite that reports nothing -- and the reason
    to fix it the day the second implementation got its first test is that the
    gap is invisible while it is small.

    `tests/dbharness.py` supplies its own Postgres -- an already-running server
    if `AGENT_SERVICE_TEST_DATABASE_URL` is set, else a testcontainer -- so the
    default run covers the persistence tests without being asked. `--fast`
    passes `-m "not postgres"` to skip starting one, which is the mode that
    needs no daemon.

    **TWO pytest runs since Plan 8 step 3, and the second one is not optional.**
    The conformance package used to be collected by the first run and skipped
    itself for want of `AGENT_SERVICE_TEST_BASE_URL` -- except for its DOCUMENT
    tier, which reads published JSON, needs no service, and includes the
    negative control. Moving that package to `spec/conformance/` took it out
    of the implementation's `testpaths`, so without this it would run only in
    `container`, i.e. only on a machine with Docker. A negative control that
    needs a container is a negative control nobody runs, which is the exact
    failure it exists to prevent.

    No `AGENT_SERVICE_TEST_BASE_URL` here either, so the live tiers skip exactly
    as they did before.

    **The suites run CONCURRENTLY since 2026-08-17, and the wall clock was the
    whole reason.** This stage is 94% of what the pre-commit hook costs, and it
    was the sum of five independent processes rather than the longest of them.
    Measured `--fast` on this host: 87.4s serial against a 33.0s slowest suite.
    Nothing about *what* runs changed -- same commands, same markers, same
    working directories.

    **Output is held per suite and printed in `UNIT_IMPLS` order**, not in the
    order the suites happen to finish, so two runs of a green tree produce the
    same transcript and a failure is always in the same place. `_run_captured`
    says why holding it does not violate `_run`'s streaming rule.

    **Every suite is still submitted before any result is read**, which is what
    keeps the property the serial loop had: three broken suites are three facts,
    and one run per defect is what this file deliberately does not do. A suite
    is not skipped because an earlier one failed -- there is no earlier one.

    `--serial-unit` puts the old streaming loop back for the case this trades
    away: watching a suite make progress live, or reading the interleaving of a
    hang against the other suites.
    """
    jobs: list[tuple[str, list[str], Path]] = []
    for name in UNIT_IMPLS:
        impl = ROOT / "impl" / name
        if not (impl / "pyproject.toml").is_file():
            print(f"  skip       impl/{name} (no pyproject.toml -- not a project yet)")
            continue
        if not (impl / "tests").is_dir():
            print(f"  skip       impl/{name} (no tests/ yet)")
            continue
        cmd = ["uv", "run", "pytest"]
        # `-m "not postgres"` only where the marker exists; an implementation
        # without a database has no such tests and pytest would warn about an
        # unknown marker rather than fail, which is noise nobody reads.
        #
        # **`and not live` IS LOAD-BEARING AND COSTS MONEY IF DROPPED.**
        # A command-line `-m` REPLACES the one in `addopts` -- pytest takes the
        # last -- so `-m "not postgres"` alone silently re-selects the tests
        # `addopts = "-m 'not live'"` exists to deselect. Measured 2026-08-08:
        # under `-m "not postgres"` the two paid tests in test_live.py are
        # collected, not deselected.
        #
        # Nothing was ever spent, because those tests carry a SECOND guard --
        # `skipif(not credentials_configured())` -- and pytest does not load
        # `.env`. But that is accidental safety: export ANTHROPIC_API_KEY in a
        # shell, as the quick start invites, and every `git commit` would spend
        # ~$0.125 through the pre-commit hook, which runs exactly this.
        # `agent-spec`'s tests need the OPTIONAL `db` extra: the base package is
        # pydantic-only on purpose, so a plain `uv run` there installs no
        # SQLAlchemy and every test in it fails to import. That extra is also
        # exactly why the entry earns its place -- a package whose database half
        # is optional needs someone running the half.
        if name.endswith("agent-spec"):
            cmd = ["uv", "run", "--extra", "db", "pytest"]
        if fast:
            if impl == IMPL:
                cmd += ["-m", "not postgres and not live"]
                # **`-n` ONLY HERE, and the placement is the whole safety
                # argument.** This build's Postgres tests share one server and
                # one schema and isolate themselves with `drop_all`/`create_all`
                # per test; `conftest.py`'s `postgres_server` says in as many
                # words that they are not safe to run in parallel across
                # processes. This branch is the one that just deselected them.
                #
                # So xdist is attached to `-m "not postgres"` rather than to the
                # build, and the default run below stays single-process. Moving
                # this line out of this branch re-selects a shared database
                # across N workers, which fails as flakes rather than as a clean
                # error.
                #
                # It earns its place by being the LONG POLE: the suites run
                # concurrently, so the stage floor is whichever suite is
                # slowest, and measured 2026-08-17 this one went 33.0s -> 14.3s.
                cmd += ["-n", str(UNIT_XDIST_WORKERS)]
            elif name.endswith("agent-spec"):
                # `and not live` even though this package HAS no live tests and
                # nothing in it can talk to a model. The guard in
                # `test_suite_integrity.py` forbids a bare `-m "not postgres"`
                # anywhere in this file, unconditionally -- and it is right to:
                # the rule "a command-line -m REPLACES addopts" is what cost
                # this repo the paid-test regression, and an exemption reasoned
                # per call site is how that rule stops being checkable.
                cmd += ["-m", "not postgres and not live"]
        # Outside the `if fast:` above, and unconditional: these builds have
        # nothing shared to protect, so there is no marker to pair `-n` with and
        # no reason for the default run to be slower than the fast one. See
        # `UNIT_XDIST_ALWAYS` for why `claude-python` cannot be listed there.
        if name in UNIT_XDIST_ALWAYS:
            cmd += ["-n", str(UNIT_XDIST_WORKERS)]
        jobs.append((f"impl/{name}", cmd, impl))

    # The conformance document tier, and it is a job in the same list rather
    # than a trailing call. It used to run after the loop with its own `and`,
    # which meant it also ran after the loop's WALL CLOCK -- and it is the
    # cheapest of the five (~0.1s), so there is nothing to be gained by making
    # it wait for the other four.
    jobs.append(("spec/conformance", ["uv", "run", "pytest"], CONFORMANCE))

    if serial:
        ok = True
        for label, cmd, cwd in jobs:
            print(f"  {label}")
            # AND, not short-circuit: three broken suites are three facts, and
            # one run per defect is what this file deliberately does not do.
            ok = (_run(cmd, cwd=cwd) == 0) and ok
        return ok

    ok = True
    with ThreadPoolExecutor(max_workers=min(len(jobs), UNIT_MAX_WORKERS)) as pool:
        # Submitted in one pass, read in a second. That ordering is the AND
        # above: every suite is already running before the first result is
        # looked at, so none of them can be short-circuited by another's
        # failure.
        running = [pool.submit(_run_captured, cmd, cwd=cwd) for _, cmd, cwd in jobs]
        for (label, cmd, _), future in zip(jobs, running):
            code, output = future.result()
            print(f"\n  {label}")
            print(f"$ {' '.join(shlex.quote(part) for part in cmd)}")
            print(output.rstrip(), flush=True)
            ok = (code == 0) and ok
    return ok


# ---------------------------------------------------------------------------
# stage: container
# ---------------------------------------------------------------------------


def _compose(
    impl: Containerised, *args: str, env_file: Path, persistence: bool = False
) -> list[str]:
    cmd = [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.ci.yaml",
        "-p",
        impl.project,
        # REPLACES the default `.env`, it does not add to it. That is the whole
        # reason this is here: compose reads a `.env` sitting beside
        # compose.yaml automatically, and the operator's `.env` holds a REAL
        # ANTHROPIC_API_KEY and mount paths pointing at a REAL repository. A CI
        # run must not boot an unconfined-Bash container over the operator's
        # working tree, and must not have a key it could spend.
        "--env-file",
        str(env_file),
    ]
    if persistence:
        cmd += ["--profile", "persistence"]
    return cmd + list(args)


def _write_env_file(impl: Containerised, name: str, *, database: bool) -> Path:
    """Write the hermetic environment the CI stack boots with.

    Under `temp/`, which is gitignored, because it carries a password -- a
    throwaway one for a container that is destroyed at the end of the run, but
    a password.

    `ANTHROPIC_API_KEY` is ABSENT rather than empty. compose.yaml passes
    `${ANTHROPIC_API_KEY:-}` through, so absent and empty reach the container
    identically; absent is written this way so that reading this file tells you
    the CI container has no credential, rather than that it has a blank one.
    **The same is true of `OPENAI_API_KEY` and `CODEX_API_KEY`** for the Codex
    stack -- no name is written, so no CI container can spend anything.

    **One file shape for every implementation, and the extra keys are
    deliberate.** The Codex stack's compose file names neither
    `REFERENCE_HOST_PATH` nor `POSTGRES_PASSWORD`, and compose ignores an
    env-file entry nothing interpolates. Writing the union keeps this function
    from branching on which build it is serving -- which is the branch that
    would eventually write the wrong port into the right file.
    """
    CI_TEMP.mkdir(parents=True, exist_ok=True)
    # Per-implementation, so two stacks up at once do not hand the same host
    # directory to two unconfined agents.
    workspace = CI_TEMP / f"workspace-{impl.name}"
    reference = CI_TEMP / f"reference-{impl.name}"
    workspace.mkdir(exist_ok=True)
    reference.mkdir(exist_ok=True)

    lines = [
        "# Generated by ci.py. Rewritten on every run; do not edit.",
        # Forward slashes even on Windows: compose's interpolation eats
        # backslashes (recorded in .env.compose.example).
        f"WORKSPACE_HOST_PATH={workspace.as_posix()}",
        f"REFERENCE_HOST_PATH={reference.as_posix()}",
        # The measured escape hatch: the free conformance tier needs no key.
        "AGENT_SERVICE_REQUIRE_CREDENTIALS=false",
        # Left at compose.yaml's default of true on purpose. The two paths
        # above really exist, so the gate should pass -- and if a future change
        # breaks how they are passed, this run should be what notices.
        "AGENT_SERVICE_REQUIRE_MOUNTS=true",
        f"CI_HOST_PORT={impl.host_port}",
        f"CI_PG_PORT={CI_PG_PORT}",
        f"POSTGRES_PASSWORD={CI_PG_PASSWORD}",
    ]
    if database:
        # `postgres:5432`, the compose-network name -- this value is read INSIDE
        # the container. The host-side migration below uses 127.0.0.1 and the
        # published port instead; they address the same server by two routes.
        lines.append(
            "AGENT_SERVICE_DATABASE_URL="
            f"postgresql://postgres:{CI_PG_PASSWORD}@postgres:5432/agent"
        )
    else:
        lines.append("AGENT_SERVICE_DATABASE_URL=")

    path = CI_TEMP / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _teardown(impl: Containerised, env_file: Path) -> None:
    """Always, including after a failure, and including `-v`.

    The volume matters: `agent-db` is project-scoped to `agentsvc-ci_agent-db`,
    and leaving it behind would carry a MIGRATED schema into the next run --
    which would make the migration step below a no-op and quietly stop testing
    the thing it exists to test. The Codex stack has a `codex-home` volume with
    a comparable property: it holds the app-server's auth store, so a surviving
    one would carry a login between runs.
    """
    _run(
        _compose(impl, "down", "-v", "--remove-orphans", env_file=env_file,
                 persistence=True),
        cwd=impl.path,
    )


def _conformance(base_url: str) -> int:
    """The suite, minus the boot gates -- those are the `gates` stage.

    Ignored rather than left to skip so that a run of this stage reports only
    tests that had a service to talk to.
    """
    return _run(
        ["uv", "run", "pytest", f"--ignore={BOOT_GATES}"],
        env={"AGENT_SERVICE_TEST_BASE_URL": base_url},
        cwd=CONFORMANCE,
    )


def stage_container() -> bool:
    """Build every implementation's image, and run the conformance suite
    against the ones whose live tier is expected to pass.

    **Every image is BUILT here, including one whose suite does not run**, and
    that is the point of separating the two: `gates` needs the image, the
    Dockerfile is the thing most likely to rot unnoticed, and a build failure is
    a failure of this stage whichever implementation it belongs to.

    Per implementation, the suite runs in BOTH deployments where there are two,
    **and not one, because of a negative control.** Only
    `spec/conformance/test_spec_persistence.py` skips on which stack is in
    front of it -- two tests want no database, three want one. The middle of
    those three,
    `test_an_unrecorded_id_is_a_PLAIN_404_not_the_disabled_one`, is the reason
    a single-stack run is not enough: this API returns 404 for two conditions a
    client must act on differently ("history is off here" vs "no such id") and
    tells them apart by the problem `type`. Against a stack with no database
    only the first condition is reachable, so an implementation that hard-coded
    the disabled `type` onto every 404 would pass. The database pass is what
    refuses it.

    `spec/conformance/test_spec_meta.py` also branches on the deployment
    without skipping -- `database_usable` must be `null` when unconfigured and
    a bool when configured -- so one stack silently exercises one arm of it.
    """
    ok = True
    for impl in CONTAINER_IMPLS:
        print(f"\n=== impl/{impl.name} " + "=" * (48 - len(impl.name)))
        ok = _container_one(impl) and ok
    return ok


class _SinkHandler(BaseHTTPRequestHandler):
    """Records the request and answers a plausible `401`. Forwards nothing.

    A `401` rather than a success: the turn is expected to FAIL, and what is
    being measured is that the request arrived at all.
    """

    protocol_version = "HTTP/1.1"
    received: list[str] = []

    def _record(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        type(self).received.append(self.path)
        payload = b'{"error":{"code":401,"message":"ci sink"}}'
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_PUT = do_POST = _record

    def log_message(self, *args: object) -> None:
        """Silence. The stage prints one line; the sink is not a log."""


def _redirect_check(impl: Containerised) -> bool:
    """**Does a turn actually leave the container through the published
    variable?** Free: no credential, no tokens, nothing reaches a provider.

    This is the rung between "the fake binary accepted our argv" and "a real turn
    costs money", and it exists because the gap between them shipped a build that
    could not take a single turn behind a gateway. The consumer found it, in a
    deployment, and nothing here could have: the unit suites drive a stand-in
    binary that has no auth to reject, the conformance suite takes no turn at
    all, and every live probe ran against the provider directly -- the one path
    on which the defect does not exist.

    **The endpoint is redirected at a sink on this machine**, so the turn fails
    at a `401` and the assertion is on the sink rather than on the turn: a
    request arrived, therefore the variable moved the endpoint, the agent
    selected an auth method, and the service's own session files were accepted.
    All three had to hold, and on `gemini-python` the middle one did not --
    setting the endpoint variable made its CLI infer an auth type its own
    validator rejects, so it exited before opening a socket.

    **A container, not compose**: no compose file here passes an endpoint
    variable through, and adding one to the product's compose file to make a test
    possible is the wrong direction.
    """
    sink_port = _free_port()
    _SinkHandler.received = []
    sink = ThreadingHTTPServer(("0.0.0.0", sink_port), _SinkHandler)  # noqa: S104
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    name = f"{impl.project}-redirect"
    port = impl.host_port + 100
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603, S607

    started = subprocess.run(  # noqa: S603
        [
            "docker", "run", "-d", "--name", name,
            "-p", f"127.0.0.1:{port}:8000",
            "--add-host", "host.docker.internal:host-gateway",
            "-e", "AGENT_SERVICE_REQUIRE_CREDENTIALS=false",
            "-e", "AGENT_SERVICE_REQUIRE_MOUNTS=false",
            "-e", f"{impl.credential_env_var}={impl.credential_dummy}",
            "-e", f"{impl.endpoint_env_var}=http://host.docker.internal:{sink_port}",
            impl.image,
        ],
        capture_output=True, text=True, check=False,
    )
    if started.returncode != 0:
        print(f"  FAIL       the redirect container did not start: {started.stderr.strip()}")
        sink.shutdown()
        return False

    base = f"http://127.0.0.1:{port}"
    try:
        if not _wait_for_health(base):
            print("  FAIL       the redirect container never became healthy")
            return False

        session = _http_json(f"{base}/v1/sessions", {"options": {}})
        sid = (session or {}).get("session_id")
        if not sid:
            print(f"  FAIL       no session from the redirect container: {session}")
            return False

        # The turn is EXPECTED to fail -- the sink answers 401. It runs in a
        # thread so the wait below can stop the moment a request lands rather
        # than sitting through the agent's own retries.
        turn = threading.Thread(
            target=_http_json,
            args=(f"{base}/v1/sessions/{sid}/messages", {"prompt": "hi"}),
            kwargs={"timeout": REDIRECT_TURN_TIMEOUT_S},
            daemon=True,
        )
        turn.start()
        deadline = time.monotonic() + REDIRECT_TURN_TIMEOUT_S
        while time.monotonic() < deadline and not _SinkHandler.received:
            time.sleep(1)

        if not _SinkHandler.received:
            print(
                f"  FAIL       impl/{impl.name}: a turn with "
                f"{impl.endpoint_env_var} set reached NOTHING in "
                f"{REDIRECT_TURN_TIMEOUT_S}s. The published endpoint variable "
                f"does not move this build's traffic, or the agent refused "
                f"before opening a socket -- which is what a missing auth "
                f"method looks like. Read the container log: docker logs {name}"
            )
            return False
        print(
            f"  ok         impl/{impl.name}: the turn reached the sink at "
            f"{_SinkHandler.received[0][:60]}"
        )
        return True
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603, S607
        sink.shutdown()


def _label_check(impl: Containerised) -> bool:
    """**Do the image's labels agree with the document they point at?**

    An image is built against two published artifacts -- an OpenAPI document and
    a DDL revision -- and the labels state both so `docker inspect` can answer
    without starting anything. Since 0.19.0 they are also the KEY: `impl` and
    `document-version` together name the one published document that states which
    credential variable this image reads, which variable moves its endpoint and
    which one delivers a private certificate authority.

    **The labels are a COPY, and a copy is safe exactly as long as something
    compares it** -- the same bargain `EXPECTED_REVISION` takes. Without this they
    rot at the first version bump and rot silently, because nothing else in the
    build reads them.

    **This used to run `agent-service-spec` inside the image and compare against
    its output.** That command was removed in 0.19.0, and nothing was lost: AS-24
    already asserts a running service serves EXACTLY its published document, and
    `PrebootSpec` is now part of that document -- so the image's own answer is
    verified byte-for-byte by the container stage. What is left for this check is
    the half AS-24 cannot reach: that the labels name a document that exists and
    says the same thing, which is what a consumer resolves before it starts
    anything.

    One `docker` invocation and one file read. No service, no credential, no
    network.
    """
    inspected = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", impl.image],  # noqa: S607
        capture_output=True, text=True, check=False,
    )
    if inspected.returncode != 0:
        print(f"  FAIL       impl/{impl.name}: cannot inspect {impl.image}")
        return False

    try:
        labels = json.loads(inspected.stdout) or {}
    except json.JSONDecodeError as exc:
        print(f"  FAIL       impl/{impl.name}: unreadable labels: {exc}")
        return False

    build = labels.get("com.npf.agent-service.impl")
    version = labels.get("com.npf.agent-service.document-version")
    if not build or not version:
        print(
            f"  FAIL       impl/{impl.name}: the image carries no impl or "
            f"document-version label, so nothing identifies which published "
            f"document states its pre-boot facts. Edit impl/{impl.name}/Dockerfile"
        )
        return False

    name = f"{build}-{version}.json"
    document_path = ROOT / "spec" / "openapi" / name
    if not document_path.is_file():
        print(
            f"  FAIL       impl/{impl.name}: the labels name {name}, which is "
            f"not published. A consumer following them reaches nothing"
        )
        return False

    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  FAIL       impl/{impl.name}: cannot read {name}: {exc}")
        return False

    component = document.get("components", {}).get("schemas", {}).get("PrebootSpec")
    if not isinstance(component, dict):
        print(
            f"  FAIL       impl/{impl.name}: {name} has no PrebootSpec component, "
            f"so a consumer holding the specification would still have to start "
            f"a container to learn which credential variable this image reads"
        )
        return False

    properties = component.get("properties", {})

    def _const(*path: str) -> object:
        node = properties
        for step in path[:-1]:
            node = (node.get(step) or {}).get("properties", {})
        return (node.get(path[-1]) or {}).get("const")

    expected = {
        "com.npf.agent-service.impl": _const("impl", "name"),
        "com.npf.agent-service.document-version": _const("document_version"),
        "com.npf.agent-service.schema-revision": _const("schema_revision"),
    }
    ok = True
    for key, want in expected.items():
        got = labels.get(key)
        if got != want:
            # The document is the published artifact and the label is the copy,
            # so the document is right and the Dockerfile is wrong. Say which
            # file to edit, not only which values differ.
            print(
                f"  FAIL       impl/{impl.name}: label {key} is {got!r} and "
                f"{name} says {want!r}. Edit impl/{impl.name}/Dockerfile -- the "
                f"published document is the authority."
            )
            ok = False
    if ok:
        print(
            f"  ok         impl/{impl.name}: labels agree with {name} -- "
            f"document {expected['com.npf.agent-service.document-version']}, "
            f"schema {expected['com.npf.agent-service.schema-revision']}"
        )
    return ok


def _free_port() -> int:
    """A port the OS picked, so two runs on one machine cannot collide."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_health(base: str, *, seconds: int = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=5) as answer:  # noqa: S310
                if answer.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    return False


def _http_json(url: str, body: dict, *, timeout: float = 30.0) -> dict | None:
    """POST JSON and return the parsed answer, or `None` on any failure.

    **A failure is not an error here.** Every caller either checks the payload it
    wanted or measures something else entirely -- the turn is expected to come
    back as a problem document, and its own outcome is not what is asserted.
    """
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
            return json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        try:
            return json.loads(refused.read())
        except (ValueError, OSError):
            return None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def _container_one(impl: Containerised) -> bool:
    if _port_is_busy(impl.host_port):
        print(
            f"  FAIL       127.0.0.1:{impl.host_port} is already in use. That "
            f"is this script's own port for impl/{impl.name}, not its "
            f"compose.yaml's, so the likely cause is another `ci.py` run rather "
            f"than your local stack."
        )
        return False

    no_db = _write_env_file(impl, f"env.{impl.name}.nodb", database=False)
    with_db = _write_env_file(impl, f"env.{impl.name}.db", database=True)
    base_url = f"http://127.0.0.1:{impl.host_port}"
    ok = True

    try:
        # One build, used by every pass below and by the `gates` stage.
        if _run(_compose(impl, "build", env_file=no_db), cwd=impl.path) != 0:
            return False

        # ---- does a turn actually leave through the published variable? -----
        # **Before the conformance passes and for EVERY build, including one
        # whose live tier is blocked.** It needs no credential and takes no
        # billable turn, and the thing it checks is the thing a blocked live
        # tier leaves unchecked -- which is exactly how a build that could not
        # take a single turn behind a gateway got as far as a consumer.
        print("\n--- the image's labels, against the image's own statement ---")
        ok &= _label_check(impl)

        print("\n--- the endpoint variable, against a sink on this machine ---")
        ok &= _redirect_check(impl)

        if impl.live_tier_blocked_by is not None:
            # The image is built and `gates` will still run against it. The
            # reason is printed on EVERY run, not filed in a document, because a
            # tier that is silently not running is indistinguishable from one
            # that passes.
            print(
                f"\n  built, live tier NOT run for impl/{impl.name}:\n"
                f"    {impl.live_tier_blocked_by}"
            )
            # `ok`, not `True`: the redirect check above ran for this build too,
            # and a blocked live tier must not swallow its verdict.
            return ok

        # ---- pass 1: no database ------------------------------------------
        print("\n--- conformance: default stack, NO database ---")
        if _run(_compose(impl, "up", "-d", "--wait", "agent-service", env_file=no_db),
                cwd=impl.path) != 0:
            print("  the service did not become healthy; see the log above")
            return False
        ok &= _conformance(base_url) == 0

        if not impl.persistence:
            return ok

        # A full teardown between passes, not a restart. The service reads
        # AGENT_SERVICE_DATABASE_URL once, at startup -- `get_settings()` POPS
        # it out of os.environ there -- so switching deployments means a new
        # container, and the two passes must not share a session registry
        # either.
        _teardown(impl, no_db)

        # ---- pass 2: with a database --------------------------------------
        print("\n--- conformance: persistence stack, WITH a database ---")
        if _run(_compose(impl, "up", "-d", "--wait", "postgres", env_file=with_db,
                         persistence=True), cwd=impl.path) != 0:
            print("  Postgres did not become healthy; see the log above")
            return False

        # BEFORE the service starts, because nothing in the service applies
        # migrations: `grep alembic src/` returns nothing and the image copies
        # no `alembic.ini` and no `migrations/` (persistence.md corrected the
        # opposite claim on 2026-08-06). An unmigrated database boots fine and
        # reports `database_usable: false`, which is precisely the state the
        # conformance fixture SKIPS on -- so getting this wrong would produce a
        # green run that tested nothing.
        # `-c` names the tree explicitly since Plan 9 step 2 moved it out of the
        # implementation. It is run with `cwd=impl.path` all the same, because
        # `uv run` needs a project to resolve alembic from and `impl/common/db/`
        # is not one -- which is exactly right for operator tooling: the tree is
        # shared, the interpreter that runs it belongs to whoever is running it.
        migrate = [
            "uv", "run", "alembic",
            "-c", str(ALEMBIC / "alembic.ini"),
            "-x",
            f"url=postgresql://postgres:{CI_PG_PASSWORD}@127.0.0.1:{CI_PG_PORT}/agent",
            "upgrade", "head",
        ]
        if _run(migrate, cwd=impl.path) != 0:
            print("  migrations failed; the conformance run would only skip")
            return False

        if _run(_compose(impl, "up", "-d", "--wait", "agent-service",
                         env_file=with_db, persistence=True), cwd=impl.path) != 0:
            print("  the service did not become healthy; see the log above")
            return False
        ok &= _conformance(base_url) == 0
    finally:
        _teardown(impl, with_db)

    return ok


# ---------------------------------------------------------------------------
# stage: gates
# ---------------------------------------------------------------------------


def stage_gates() -> bool:
    """The half the running-service suite cannot reach, for EVERY image.

    Every other conformance test asks a live service what it does, which can
    never check AS-2's actual claim: a service that exited 3 is not one
    anything can talk to. This module starts deliberately misconfigured
    containers and reads the exit code instead.

    **It loops where `container` may not.** The boot-gate tier is the part of
    the specification that is genuinely implementation-neutral -- exit 3, a
    refusal that names a credential the image itself publishes, a socket on
    every IPv4 interface -- and running it against a second image is what
    proved that in both directions on 2026-08-08: it passed for
    `codex-python` only after four assertions in that module stopped naming
    Anthropic's variables, which was a defect in the suite rather than in
    either build.

    Depends on `container` having built each image -- checked rather than
    assumed, because the failure otherwise is `docker: no such image` buried in
    a subprocess.
    """
    ok = True
    for impl in CONTAINER_IMPLS:
        exists = subprocess.run(
            ["docker", "image", "inspect", impl.image],
            capture_output=True,
            check=False,
        )
        if exists.returncode != 0:
            print(
                f"  FAIL       no image `{impl.image}` for impl/{impl.name}. Run "
                f"the `container` stage first (it builds every image), or "
                f"`docker compose -f compose.yaml -f compose.ci.yaml -p "
                f"{impl.project} build` from impl/{impl.name}."
            )
            ok = False
            continue
        print(f"\n  impl/{impl.name} -> {impl.image}")
        ok = (
            _run(
                ["uv", "run", "pytest", BOOT_GATES],
                env={"AGENT_SERVICE_TEST_IMAGE": impl.image},
                cwd=CONFORMANCE,
            )
            == 0
        ) and ok
    return ok


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    ok: bool
    seconds: float


#: Order matters: the two cheapest and most local first, so a broken link or
#: an edited published document is known in seconds rather than after a
#: container build.
ALL_STAGES = ("freeze", "links", "references", "unit", "container", "gates")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run everything this repository can check for free.",
        epilog="The paid tier (`-m live`) is not reachable from here by design.",
    )
    parser.add_argument(
        "--stages",
        default=",".join(ALL_STAGES),
        help=f"comma-separated subset of: {', '.join(ALL_STAGES)}",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="freeze + links + unit, with -m 'not postgres': no Docker daemon needed",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first failing stage (what the pre-commit hook uses)",
    )
    parser.add_argument(
        "--serial-unit",
        action="store_true",
        help="run the unit suites one at a time, streaming (slower; for debugging a hang)",
    )
    args = parser.parse_args(argv)

    if args.fast:
        stages = ["freeze", "links", "references", "unit"]
    else:
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = [s for s in stages if s not in ALL_STAGES]
    if unknown:
        parser.error(f"unknown stage(s): {', '.join(unknown)}")

    if not args.fast and any(s in stages for s in ("container", "gates")):
        if shutil.which("docker") is None:
            print("docker is not on PATH; use --fast, or --stages freeze,unit")
            return 2

    results: list[Result] = []
    for name in stages:
        print(f"\n{'=' * 72}\n== {name}\n{'=' * 72}")
        started = time.monotonic()
        if name == "freeze":
            ok = stage_freeze()
        elif name == "links":
            ok = stage_links()
        elif name == "references":
            ok = stage_references()
        elif name == "unit":
            ok = stage_unit(fast=args.fast, serial=args.serial_unit)
        elif name == "container":
            ok = stage_container()
        else:
            ok = stage_gates()
        results.append(Result(name, ok, time.monotonic() - started))
        # A DELIBERATE RUN IS NOT FAIL-FAST. Knowing that the freeze check and
        # the container suite are both broken is worth more than one run per
        # defect, and no stage's setup depends on an earlier one having
        # PASSED -- `gates` needs the image `container` builds, and checks for
        # it rather than assuming.
        #
        # THE HOOK IS, and passes --fail-fast for a reason that is about the
        # hook rather than about correctness: it stands between you and every
        # commit, and a failing `freeze` costing 3 s rather than 45 s is the
        # difference between fixing it and reaching for --no-verify. Measured:
        # a freeze violation blocked a commit in 45.4 s without this, because
        # `unit` ran anyway with the answer already known.
        if not ok and args.fail_fast:
            skipped = stages[stages.index(name) + 1:]
            if skipped:
                print(f"\n  stopping here (--fail-fast); not run: {', '.join(skipped)}")
            break

    print(f"\n{'=' * 72}")
    for result in results:
        print(f"  {'PASS' if result.ok else 'FAIL'}  {result.name:<10} {result.seconds:6.1f}s")
    for name in stages[len(results):]:
        print(f"  ----  {name:<10}    n/a")
    failed = [r.name for r in results if not r.ok]
    print(f"{'=' * 72}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("All stages passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
