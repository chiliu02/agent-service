"""Black-box conformance harness — the published document, and a RUNNING service.

THE RULE THIS PACKAGE KEEPS, and the reason it exists as a separate package:
**nothing here imports `agent_service`.** Every other test in this repo drives
the app in-process through `ASGITransport`, with fakes standing in for the agent,
so it cannot see the container, uvicorn's HTTP layer, real SSE framing, the boot
gates, or the CLI subprocess. This suite sees only what a consumer sees: a
published JSON document, and a URL that answers with status lines, headers and
bodies.

The only files it may read from the repo are the **published specs** — one
because "the running service matches its published document" is itself a
specification clause (AS-24), the other because the negative control needs a document
that must fail. No test here reads anything under `docs/`.

**It has its own `pyproject.toml` and belongs to the specification, not to any
implementation** (Plan 8 step 3). `uv run pytest` in this directory needs pytest
and httpx and a URL; the service behind that URL may be built from any language,
which is the whole point. The documents it reads are the specification's too, in
`../openapi/` since step 4, and the version it pins them to is `../VERSION`
since step 5.

**Nothing below resolves a path into `impl/`,** and as of step 5 that is
enforced by there being nothing left there to want: the last thread was "which
version does the document tier check", which used to be read from the Python
package's `pyproject.toml` and is now the specification's own number.

**Three tiers, and only two of them need a service.**

- **Document** — `test_spec_document.py` and `test_spec_negative_control.py`
  run `predicates.py` over published JSON. No service, no Docker, no tokens, no
  environment variable: they run on every `uv run pytest` and are **not** marked
  `conformance`, because that marker means "needs a running service" and they do
  not.
- **Free live** — a service, no turns. Sessions spawn the CLI and send no prompt.
- **Paid live** — marked `live`, deselected by default like the rest of the repo.

    # start a container however you like, then:
    AGENT_SERVICE_TEST_BASE_URL=http://127.0.0.1:8000 uv run pytest

The two live tiers are skipped, never failed, when that variable is unset -- the
same shape as the implementation's `tests/dbharness.py`: a machine without a
running service is not a machine with a broken one.

COST. Creating a session spawns the CLI and sends no prompt, so the whole free
tier costs **zero tokens** (T2 measured that creation does not even consume a
supplied session id). Tests that take a turn are marked `live` and are
deselected by default, exactly like the rest of the repo's paid tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

#: The specification root, one level up: `spec/conformance/` -> `spec/`.
_SPEC = Path(__file__).resolve().parents[1]

def _version_dir(version: str) -> Path:  # noqa: ARG001
    """Where a version's published documents live: **`spec/openapi/`.**

    **There are no version directories any more** (user, 2026-08-19). `spec/openapi/`
    carries exactly one version -- the current one, `-snapshot` or cut -- and
    every delivered version before it lives in its own `release-<version>` git
    tag rather than in the working tree. **The tag is the freeze**, and
    everything a release ships is built from it.

    So this takes a version and ignores it. It stays a function because the
    callers read better for saying which version they are after, and because a
    layout that has changed twice will change again.
    """
    return _SPEC / "openapi"


def _where(version: str) -> str:
    """`spec/` -- for failure messages, which still name the version themselves."""
    return f"spec/  (it holds the current version; {version} would be in its tag)"


def _document_path(version: str, impl: str | None = None) -> Path:
    """Where a published document lives.

    **Two shapes, because Plan 8 step 6 keyed the document to the implementation**
    (AS-24 restated): `<the version's directory>/openapi-<version>-<impl>.json` where
    `<impl>` is `capabilities.impl.name`. With `impl` omitted this returns the
    pre-0.19.0 shape, which is what the negative control needs -- it runs against
    a real 0.2.0 document from before any of this existed.

    **AS-24 keeps BYTE EQUALITY and was not relaxed to containment**, which is why
    a per-implementation filename was the answer. Containment would break the
    transfer that lets `test_spec_document.py` prove nine clauses with no service
    running: a proof about the published document would no longer be a proof about
    the thing answering requests.
    """
    if impl is None:
        return _version_dir(version) / f"openapi-{version}.json"
    return _version_dir(version) / f"{impl}-{version}.json"


def _core_path(version: str) -> Path:
    """The structural core every implementation's document must contain (AS-31)."""
    return _version_dir(version) / f"core-{version}.json"


def _document_version() -> str:
    """Which document version this suite checks against.

    `spec/VERSION`, and since Plan 8 step 5 that is the whole answer --
    nothing here reads an implementation's `pyproject.toml` any more, and
    nothing here resolves a path into `impl/`. That is what makes this suite
    runnable against a service built in another language.
    """
    return (_SPEC / "VERSION").read_text(encoding="utf-8").strip()

BASE_URL_ENV = "AGENT_SERVICE_TEST_BASE_URL"

_SKIP = pytest.mark.skipif(
    not os.environ.get(BASE_URL_ENV),
    reason=(
        f"{BASE_URL_ENV} is not set. Start a container and point this at it, "
        "e.g. AGENT_SERVICE_TEST_BASE_URL=http://127.0.0.1:8000"
    ),
)


_HERE = Path(__file__).parent

#: A test that requests any of these is talking to a service. The document tier
#: requests none of them, which is what keeps it running on a bare checkout.
_LIVE_FIXTURES = frozenset(
    {"api", "base_url", "published_spec", "served_core", "session_factory"}
)


def pytest_collection_modifyitems(items) -> None:  # noqa: ANN001
    """Skip the tests in this package THAT NEED A SERVICE, and only those.

    **`items` is every test pytest collected, not this directory's.** A conftest
    living in a subdirectory does not narrow the hook's argument, so the
    filtering below is load-bearing: without it this marks the entire repository
    skipped whenever `AGENT_SERVICE_TEST_BASE_URL` is unset, which is the
    default. Caught by running the full suite and reading the count -- 550
    skipped, 0 run, exit 0. A green suite that executes nothing is the worst
    possible failure mode, so `tests/test_suite_integrity.py` now pins it.

    **The predicate is the fixture list, not the file name.** Marking the whole
    package would switch off the document tier too, and that tier's entire value
    is that it needs nothing -- a negative control that only runs on a machine
    with a container is a negative control nobody runs.
    """
    for item in items:
        if _HERE not in item.path.parents:
            continue
        if not _LIVE_FIXTURES.intersection(getattr(item, "fixturenames", ())):
            continue
        item.add_marker(_SKIP)
        item.add_marker(pytest.mark.conformance)


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get(BASE_URL_ENV)
    if not url:  # pragma: no cover - the skip marker above fires first
        pytest.skip(f"{BASE_URL_ENV} is not set")
    return url.rstrip("/")


@pytest.fixture
async def api(base_url: str):
    """A plain HTTP client. No ASGI transport, no app object, no shortcuts."""
    async with AsyncClient(base_url=base_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def published_spec() -> dict[str, Any]:
    """The spec file this repo publishes for the version under test.

    Resolved from the version the SERVICE reports, not from the newest file on
    disk -- the point of AS-24 is that a running service matches its own
    published document, and reading the newest file would quietly test the wrong
    pair.
    """
    import httpx

    url = os.environ[BASE_URL_ENV].rstrip("/")
    served = httpx.get(f"{url}/openapi.json", timeout=30.0).json()
    version = served["info"]["version"]
    # **Which implementation is answering, asked over HTTP.** AS-24 keys the
    # document to the version AND the build since 0.19.0, and the suite must not
    # learn the build from a path, an environment variable or a guess -- the
    # service publishes it, so the service is asked.
    impl = httpx.get(f"{url}/v1/capabilities", timeout=30.0).json()["impl"]["name"]
    path = _document_path(version, impl)
    if not path.exists():
        pytest.fail(
            f"the service reports version {version} and implementation {impl}, "
            f"but {path.name} is not published at {_where(version)}/ (AS-24)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def served_core() -> dict[str, Any]:
    """The core document for the version the SERVICE reports (AS-31).

    Separate from `published_spec` because the core is not keyed to an
    implementation -- that is the whole point of it.
    """
    import httpx

    url = os.environ[BASE_URL_ENV].rstrip("/")
    version = httpx.get(f"{url}/openapi.json", timeout=30.0).json()["info"]["version"]
    path = _core_path(version)
    if not path.exists():
        pytest.fail(
            f"the service reports version {version} but {path.name} is not "
            f"published at {_where(version)}/ (AS-31)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


#: The document the negative control runs against. A REAL non-conforming
#: document -- the one Studio actually read and built against -- not a mutated
#: copy of the current one. What it lacked is on the record in the signed
#: bundle's conformance history.
NON_CONFORMING_VERSION = "0.2.0"

#: **Vendored as a FIXTURE, not read as a delivery** (2026-08-19). It used to be
#: loaded from a version directory under `spec/`; there are none any more
#: now, and this suite must run from a plain checkout -- and for a consumer, from
#: a directory with no git at all. Copying it here is the honest shape anyway:
#: its role is *a known-bad document the predicates must reject*, which is a test
#: fixture rather than something this platform still publishes.
#:
#: It is the document Studio actually read, copied here unchanged, and it is
#: never regenerated.
#:
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _published(version: str, impl: str | None = None) -> dict[str, Any]:
    if version == NON_CONFORMING_VERSION:
        return json.loads(
            (FIXTURES / f"openapi-{version}.json").read_text(encoding="utf-8")
        )
    path = _document_path(version, impl)
    if not path.exists():
        pytest.fail(f"{path.name} is not published at {_where(version)}/ (AS-24)")
    return json.loads(path.read_text(encoding="utf-8"))


def _pinned_implementations() -> list[str]:
    """Every implementation with a published document for the current version.

    Read from the directory at collection time, so a third implementation is
    covered by having published a document rather than by editing this suite.
    Empty means a pre-0.19.0 layout, where one document served every build.
    """
    version = _document_version()
    suffix = f"-{version}.json"
    # **`core` is not an implementation**, and it shares the prefix on purpose:
    # every file here is `openapi-<version>-<what>.json`, where `<what>` is a
    # build name or the intersection over all of them. One namespace, one
    # exclusion.
    return sorted(
        name
        for path in _version_dir(version).glob(f"*{suffix}")
        if (name := path.name[: -len(suffix)]) != "core"
    )


@pytest.fixture(scope="session", params=_pinned_implementations() or [None])
def pinned_spec(request) -> dict[str, Any]:  # noqa: ANN001
    """The document this repo publishes for the CURRENT version. No service.

    **Parametrised over every implementation since 0.19.0**, so the document tier
    proves its nine clause predicates for *each* build rather than for one of
    them. That is what makes AS-24's transfer worth having with more than one
    implementation: each build serves its own document byte for byte, and each of
    those documents has been shown to satisfy the clauses -- with no service, no
    Docker and no token.

    `None` is the pre-0.19.0 shape, kept so the negative control and any older
    version still resolve.

    Pinned to `../VERSION` rather than the newest file in `../openapi/`:
    publishing 0.13.0 while the specification still says 0.12.0 should fail here, not
    quietly move the tier onto a document nothing serves.

    **It read the implementation's `pyproject.toml` until Plan 8 step 5**, which
    was the same number and the wrong source: this suite is the specification's, and
    asking a particular build which document to check is exactly the coupling
    the split removed. The implementation's
    `tests/test_api_meta.py` pins the other edges -- that what the app serves
    equals `spec/VERSION`, and that the published file equals what the app
    serves.
    """
    return _published(_document_version(), request.param)


@pytest.fixture(scope="session")
def non_conforming_spec() -> dict[str, Any]:
    """A published document that predates the specification. No service."""
    return _published(NON_CONFORMING_VERSION)


@pytest.fixture
async def session_factory(api):  # noqa: ANN001
    """Opens sessions and guarantees they are closed.

    Sessions hold one of `max_sessions` slots and a CLI subprocess each, so a
    test that leaks one degrades every test after it -- and the cap test would
    then fail for the wrong reason.
    """
    opened: list[str] = []

    async def open_session(**body: Any) -> dict[str, Any]:
        response = await api.post("/v1/sessions", json=body)
        assert response.status_code == 201, response.text
        record = response.json()
        opened.append(record["session_id"])
        return record

    yield open_session

    for sid in opened:
        try:
            await api.delete(f"/v1/sessions/{sid}")
        except Exception:  # noqa: BLE001 - teardown must not mask a failure
            pass


@pytest.fixture(scope="session")
def capabilities(base_url: str) -> dict[str, Any]:
    """`GET /v1/capabilities` from the service under test.

    **The join between an optional clause and the build in front of you.**
    A clause that only some implementations can satisfy is asserted against
    what this one PUBLISHES, not against what one SDK happens to do -- which is
    the defect that made four assertions in this package Anthropic-specific and
    the reason `allow_supplied_sdk_session_id` exists.
    """
    import httpx

    return httpx.get(f"{base_url}/v1/capabilities", timeout=30.0).json()


#: The model the paid tier opens its sessions on, if the operator names one.
#:
#: **Unset means "use whatever the deployment defaults to"**, which is the only
#: answer this package can give on its own: a cheap model on one SDK is not a
#: model name on another, and a conformance suite that hardcodes
#: `claude-haiku-4-5` is a suite that only runs against one build. It did, until
#: 2026-08-09.
_TEST_MODEL_VAR = "AGENT_SERVICE_TEST_MODEL"


def cheap_option_payload(
    unsupported: list[Any] | None, model: str | None = None
) -> dict[str, Any]:
    """The paid tier's session options, given what a build refuses.

    **A function rather than four lines inside the fixture, because the rule was
    got backwards on the first attempt** and a session-scoped fixture that needs
    two running containers is not a thing anyone will re-check by hand.
    `test_suite_integrity.py` pins it against both builds' real published lists,
    for free.
    """
    wanted: dict[str, Any] = {
        # One turn, no tools: every clause in the paid tier is about
        # identifiers, headers, framing and the TYPE of a cost field. None of it
        # is model-dependent, so the turn should be as small as the build allows.
        "max_turns": 1,
        "allowed_tools": [],
    }
    if model:
        wanted["model"] = model

    refused = {
        # `{field, types?, values?}` -- `types` since 2026-08-09, `values` since
        # 2026-08-12. This fixture sends a list, a number and an object, so an
        # entry with either restriction still applies to what it would have
        # sent, and treating every entry as whole-field here is the conservative
        # direction: it drops an option it might have been allowed to send,
        # rather than sending one that 400s. None of the three fields it sends
        # carries a value-scoped refusal today.
        entry["field"] if isinstance(entry, dict) else str(entry)
        for entry in unsupported or []
    }
    return {
        key: value
        # Dropped only when it is BOTH refused and non-empty, which is the exact
        # condition the service refuses on. `max_turns: 1` goes; `allowed_tools:
        # []` stays even on a build that lists it.
        for key, value in wanted.items()
        if key not in refused or not value
    }


@pytest.fixture(scope="session")
def cheap_options(capabilities: dict[str, Any]) -> dict[str, Any]:
    """Session options for the paid tier: as small as this build will accept.

    **Built from what the service PUBLISHES rather than from a literal**, and
    that is AS-32 earning its keep inside the suite that defines it. The old
    literal named `claude-haiku-4-5` and set `max_turns`, and `codex-python`
    refuses `max_turns` with a 400 -- so a live run against that build failed at
    session creation, before a single clause was reached, for a reason that had
    nothing to do with any clause.

    Three rules, and none of them names an implementation:

    * **Never send an option the build publishes as unsupported.** `unsupported_options`
      is exactly the list of fields that would turn this into a 400.
    * **Strip only what would actually be refused.** The refusal is truthiness
      based -- an empty container asks for nothing, so a build refusing
      `allowed_tools` still accepts `allowed_tools: []`. Dropping it anyway
      would discard the "no tools" intent for no gain, and this fixture applies
      the same rule the service does rather than a coarser one.
    * **Never name a model.** Set `AGENT_SERVICE_TEST_MODEL` to something cheap
      for the build under test; unset, the deployment's own default is used.

    **What actually bounds a turn therefore differs per build, and that is a
    cost fact rather than a detail.** Where `max_turns` survives, the turn is
    bounded by a turn count. Where it is refused, the only bound left is the
    deployment's own turn deadline (`limits.default_request_timeout_s`), which
    is wall-clock and not a token budget. A run against such a build is bounded
    but not cheap by construction -- which is the strongest reason to set
    `AGENT_SERVICE_TEST_MODEL`.

    **The cost warning the old literal carried still stands and is now the
    operator's to act on:** unset that variable and a paid run costs whatever
    the deployment's default model costs. The suite cannot choose for you
    without naming a build.
    """
    import os

    return {
        "options": cheap_option_payload(
            capabilities.get("unsupported_options"),
            os.environ.get(_TEST_MODEL_VAR),
        )
    }


@pytest.fixture(scope="session")
def allows_supplied_sdk_session_id(capabilities: dict[str, Any]) -> bool:
    """AS-13's condition (0.18.0).

    **Read, never defaulted.** A missing field is a build older than 0.18.0 or
    one that forgot to publish it; either way the suite must say so rather than
    guess an answer and assert against it.
    """
    value = capabilities.get("allow_supplied_sdk_session_id")
    if not isinstance(value, bool):
        pytest.fail(
            "the service publishes no boolean `allow_supplied_sdk_session_id` "
            "on /v1/capabilities. AS-13 is conditional on it since 0.18.0, so "
            "there is no safe default to assume."
        )
    return value
