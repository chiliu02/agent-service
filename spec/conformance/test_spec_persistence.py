"""Conformance: the history routes, in BOTH deployments.

Free -- no turn is taken. A session is created and read back; nothing is sent
to a model.

`/v1/sessions/{sid}/transcript` and `/v1/runs/{run_id}` were the last uncovered
routes in this suite, for a reason worth stating: the default compose stack has
no database, so the only behaviour reachable there is the *refusal*. That made
them look untestable. They are not — the refusal is itself the specification, and it
is the half a client meets first.

**The property under test is that two 404s are distinguishable.** Nothing else
in this API returns the same status code for two conditions a caller must act on
differently:

- *history is switched off for this whole service* — stop asking, hide the tab
- *this particular session or run was never recorded* — the feature works, this
  id is not there

`errors.py` sets a non-default `type` for exactly one failure in the codebase,
and this is it. A client that told them apart by matching on the title's prose
would break on a reworded sentence. So the assertion is on the `type` URI.

The module adapts to the service in front of it rather than requiring one shape:
it probes once, then asserts what that deployment must do. Run it against both
stacks — the tests that do not apply skip, and say which mode they wanted.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

PERSISTENCE_DISABLED = "https://agent-service.invalid/problems/persistence-disabled"


@pytest.fixture(scope="session")
def persistence_enabled(base_url: str) -> bool:
    """Does the service under test have a WORKING database?

    Read from `/healthz`, which reports both halves since 0.6.0. It used to be
    inferred from an unknown-run probe -- 404 with the disabled `type` meant no
    database -- and that inference had a blind spot this very suite created the
    evidence for: a service whose database is configured but unusable answers
    **500**, matching neither branch, and the fixture asserted its way to a
    confusing error inside every test that depended on it.

    Asking the service what it knows about itself is both simpler and the thing
    an operator would do.
    """
    import httpx

    health = httpx.get(f"{base_url}/healthz", timeout=30.0).json()
    if not health["database_configured"]:
        return False
    if not health["database_usable"]:
        pytest.skip(
            "this service has a database configured but reports it UNUSABLE "
            "(/healthz database_usable=false) -- neither branch of these tests "
            "applies, and the deployment needs fixing before the suite can say "
            "anything. Check the service log for the probe's WARNING; an "
            "unmigrated schema is the usual cause."
        )
    return True


@pytest.fixture
def needs_history(persistence_enabled: bool) -> None:
    if not persistence_enabled:
        pytest.skip(
            "this service has no database configured; run the suite against a "
            "`docker compose --profile persistence` stack to cover these"
        )


@pytest.fixture
def needs_no_history(persistence_enabled: bool) -> None:
    if persistence_enabled:
        pytest.skip(
            "this service has a database configured; the refusal path is covered "
            "by the default stack"
        )


# --------------------------------------------------------------------------
# Persistence OFF -- the default stack, and what most callers meet first
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("needs_no_history")
async def test_both_history_routes_refuse_with_the_documented_type(api) -> None:  # noqa: ANN001
    """The refusal a console reads to say "history is off" rather than "empty"."""
    for path in (
        f"/v1/sessions/{uuid.uuid4().hex}/transcript",
        f"/v1/runs/{uuid.uuid4().hex}",
    ):
        r = await api.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/problem+json"), path
        body = r.json()
        assert body["type"] == PERSISTENCE_DISABLED, path
        # The detail names the variable that turns it on. A refusal that does
        # not say what to do about it sends the reader to the source.
        assert "AGENT_SERVICE_DATABASE_URL" in (body.get("detail") or ""), path


@pytest.mark.usefixtures("needs_no_history")
async def test_the_refusal_does_not_depend_on_the_session_existing(
    api, session_factory
) -> None:  # noqa: ANN001
    """A REAL session's transcript refuses identically to an invented one.

    The gate is checked before the lookup, so "history is off" never arrives
    dressed as "no such session" -- which is the failure that would make a
    client retry against a service that will never answer.
    """
    sid = (await session_factory())["session_id"]

    r = await api.get(f"/v1/sessions/{sid}/transcript")
    assert r.status_code == 404
    assert r.json()["type"] == PERSISTENCE_DISABLED


# --------------------------------------------------------------------------
# Persistence ON -- needs `docker compose --profile persistence`
# --------------------------------------------------------------------------


async def _wait_for_transcript(api, sid: str, timeout_s: float = 10.0):  # noqa: ANN001
    """Poll until the recorded session appears, or give up.

    **The write is asynchronous and this is by design**, so a read immediately
    after the 201 is a race. `DatabaseRecorder.session_opened` enqueues to
    `QueueWriter` and returns; the whole persistence design turns on there being
    no database round trip on the request path. The row lands shortly after.

    Written as a poll after the first version of this test asserted 200
    immediately and failed about one run in three. **Measured on this stack:
    0.25-0.38 s from the 201 to the transcript answering (n=6.)** The bound
    below is 30x that -- generous on purpose, because the point is that the
    write lands, not how fast.
    """
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = await api.get(f"/v1/sessions/{sid}/transcript")
        if last.status_code == 200:
            return last
        await asyncio.sleep(0.05)
    return last


@pytest.mark.usefixtures("needs_history")
async def test_a_session_is_recorded_at_creation_before_any_turn(
    api, session_factory
) -> None:  # noqa: ANN001
    """Creating a session writes it; the transcript is present and empty.

    Free, and it pins something a paid test would obscure: the row comes from
    `session_opened`, not from the first turn. A console can open a brand-new
    session and get an empty conversation rather than a 404.

    **The consumer-visible caveat, measured here rather than assumed:** "before
    any turn" does not mean "the instant the 201 returns". There is a window --
    0.25-0.38 s on this stack -- where the session exists and its transcript
    404s. A UI that opens a session and immediately fetches its history will hit
    it. See `_wait_for_transcript`.
    """
    sid = (await session_factory())["session_id"]

    r = await _wait_for_transcript(api, sid)
    assert r.status_code == 200, (
        f"the session was never recorded: {r.status_code} {r.text}"
    )
    page = r.json()
    assert page["session_id"] == sid
    assert isinstance(page["events"], list)


@pytest.mark.usefixtures("needs_history")
async def test_an_unrecorded_id_is_a_PLAIN_404_not_the_disabled_one(api) -> None:  # noqa: ANN001
    """The other half of the discriminator, and the half that can only be
    checked here: with history ON, an unknown id must NOT claim history is off.

    Without this, `type` could be hard-coded to the disabled URI on every 404
    and the refusal tests above would still pass.
    """
    for path in (
        f"/v1/sessions/{uuid.uuid4().hex}/transcript",
        f"/v1/runs/{uuid.uuid4().hex}",
    ):
        r = await api.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/problem+json"), path
        assert r.json()["type"] != PERSISTENCE_DISABLED, (
            f"{path} reports history as disabled on a service that has a database"
        )


@pytest.mark.usefixtures("needs_history")
async def test_the_transcript_route_takes_no_control_request(
    api, session_factory
) -> None:  # noqa: ANN001
    """It reads stored rows, so a closed session still has a transcript.

    `GET /v1/sessions/{sid}` issues a live control request and 404s once the
    session is gone. This route must not: history outliving the session is most
    of why it is stored.
    """
    sid = (await session_factory())["session_id"]
    # Wait for the row BEFORE deleting: otherwise a 404 afterwards is ambiguous
    # between "history does not outlive the session" and "the write had not
    # landed yet", and the test would be reporting the wrong defect.
    assert (await _wait_for_transcript(api, sid)).status_code == 200

    assert (await api.delete(f"/v1/sessions/{sid}")).status_code == 204
    assert (await api.get(f"/v1/sessions/{sid}")).status_code == 404

    r = await api.get(f"/v1/sessions/{sid}/transcript")
    assert r.status_code == 200, (
        "the stored transcript vanished with the live session, so history does "
        "not outlive the thing it is history of"
    )
