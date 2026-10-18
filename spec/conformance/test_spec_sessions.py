"""Conformance: session lifecycle and identifiers. AS-6, AS-13 … AS-16, AS-20.

Free. Creating a session spawns the CLI but sends no prompt, and T2 measured
that creation does not even consume a supplied session id -- so every id used
here can be reused afterwards and nothing is spent.
"""

from __future__ import annotations

import uuid

import pytest
from .predicates import flat


async def test_as13_a_supplied_id_is_adopted_or_refused_as_published(
    api, session_factory, allows_supplied_sdk_session_id: bool
) -> None:  # noqa: ANN001
    """AS-13, conditional on `allow_supplied_sdk_session_id` since 0.18.0.

    **Both branches are the clause**, which is why this is one test rather than
    a test and a skip. A build publishing `true` must adopt the id before any
    model call -- the mapping is the whole point. A build publishing `false`
    must REFUSE with 400: adopting the field and returning a different id would
    break that mapping silently, which is worse than not offering it at all.

    The clause was absolute until 0.18.0 and encoded one SDK's ability as a
    requirement on everyone. `AsyncCodex.thread_start()` takes no id."""
    supplied = str(uuid.uuid4())

    if not allows_supplied_sdk_session_id:
        r = await api.post("/v1/sessions", json={"sdk_session_id": supplied})
        assert r.status_code == 400, (
            "this build publishes allow_supplied_sdk_session_id=false, so a "
            "supplied id must be refused rather than ignored"
        )
        assert r.headers["content-type"].startswith("application/problem+json")
        # **The refusal is machine-readable, and it is owed** -- Agent Studio
        # asked for it and this side accepted: `POST /v1/sessions` answers 400
        # for several reasons, and a client telling this one apart by its
        # `title` is matching prose that is allowed to change. The URI names the
        # condition rather than the build.
        assert r.json().get("type") == (
            "https://agent-service.invalid/problems/sdk-session-id-unsupported"
        ), (
            "a build that refuses a supplied id must say so with a documented "
            "problem `type`, not with a sentence"
        )
        return

    record = await session_factory(sdk_session_id=supplied)
    assert record["sdk_session_id"] == supplied
    # Two identifiers, never merged: the path handle is the service's own.
    assert record["session_id"] != supplied


async def test_as15_sdk_session_id_is_null_only_while_it_is_unknown(
    session_factory
) -> None:  # noqa: ANN001
    """AS-15, restated in 0.18.0 to say what the FIELD always said.

    The clause read *"without a supplied id, `sdk_session_id` is null on the
    201 and populated from the first turn"* -- true of a CLI that mints its id
    when the conversation starts, false of an SDK that mints one at creation.
    The field's own description has always said *"or null when it is **not
    known yet**"*, and that is the rule: null means unknown, not reserved.

    **No capability of its own.** A consumer handles null regardless, so there
    is nothing to branch on -- only a value to check for honesty. This asserts
    the type, not the timing."""
    record = await session_factory()
    value = record["sdk_session_id"]
    assert value is None or isinstance(value, str), (
        "sdk_session_id must be a string or null -- never absent, so that null "
        "can never mean 'not told'"
    )
    if value is not None:
        assert value != record["session_id"], (
            "a build that knows the SDK id at creation must still keep it "
            "distinct from the service-side path handle (AS-20)"
        )


async def test_as13_the_deprecated_spelling_gets_the_same_answer(
    api, session_factory, allows_supplied_sdk_session_id: bool
) -> None:  # noqa: ANN001
    """`session_id` on the REQUEST was 0.4.0's name for this field.

    It folds into the same field, so it must meet the same answer -- adopted on
    a build that allows it, refused on one that does not. An alias slipping past
    the refusal would be a way to supply an id the build cannot honour."""
    supplied = str(uuid.uuid4())

    if not allows_supplied_sdk_session_id:
        r = await api.post("/v1/sessions", json={"session_id": supplied})
        assert r.status_code == 400
        return

    record = await session_factory(session_id=supplied)
    assert record["sdk_session_id"] == supplied


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "7ad25f07-08d4-4b3a-9f21"])
async def test_as14_a_non_uuid_id_is_400_over_the_wire(api, bad: str) -> None:  # noqa: ANN001
    r = await api.post("/v1/sessions", json={"sdk_session_id": bad})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["detail"], "a 400 must say something a caller can act on"
    # **The STATUS is the clause; the wording is not.** This asserted
    # `"UUID" in detail` until 0.18.0, which made it a test of one build's
    # prose: a build that refuses EVERY supplied id answers 400 for a
    # different and equally correct reason, and the grep failed it while the
    # behaviour was right.


async def test_as14_an_id_with_resume_is_400(api) -> None:  # noqa: ANN001
    r = await api.post(
        "/v1/sessions",
        json={
            "sdk_session_id": str(uuid.uuid4()),
            "options": {"resume": str(uuid.uuid4())},
        },
    )
    assert r.status_code == 400
    # Same reasoning as above: the conflict is a 400 whatever the build's reason.
    assert r.json()["detail"]


async def test_conflicting_spellings_are_refused(api) -> None:  # noqa: ANN001
    """Two names for one value that disagree: refused, never silently resolved."""
    r = await api.post(
        "/v1/sessions",
        json={"session_id": str(uuid.uuid4()), "sdk_session_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422


async def test_as20_the_sdk_id_is_not_a_path_handle(api, session_factory) -> None:  # noqa: ANN001
    """Measured as a 404 in-process; here it is a 404 over a real server.

    **Reads the id off the record rather than supplying one**, so it holds
    on a build that mints its own. The two identifiers are different
    namespaces and using one where the other belongs is a 404 rather than a
    lookup that happens to work -- however the SDK id came to exist."""
    record = await session_factory()
    sdk_id = record["sdk_session_id"]
    if sdk_id is None:
        pytest.skip("this build reports no SDK id until the first turn")

    r = await api.get(f"/v1/sessions/{sdk_id}")
    assert r.status_code == 404


async def test_a_session_appears_in_the_list_and_deletes_cleanly(
    api, session_factory
) -> None:  # noqa: ANN001
    record = await session_factory()
    sid = record["session_id"]

    listed = (await api.get("/v1/sessions")).json()["sessions"]
    assert any(s["session_id"] == sid for s in listed)

    detail = await api.get(f"/v1/sessions/{sid}")
    assert detail.status_code == 200
    # The detail route issues a live control request to the CLI -- a genuine
    # round trip to the subprocess, which no in-process test performs.
    assert "context_usage" in detail.json()

    assert (await api.delete(f"/v1/sessions/{sid}")).status_code == 204
    assert (await api.get(f"/v1/sessions/{sid}")).status_code == 404


async def test_patch_changes_the_model_and_reads_back(api, session_factory) -> None:  # noqa: ANN001
    sid = (await session_factory())["session_id"]
    r = await api.patch(f"/v1/sessions/{sid}", json={"model": "claude-haiku-4-5"})
    assert r.status_code == 200
    assert r.json()["model"] == "claude-haiku-4-5"


async def test_interrupting_an_idle_session_is_200_and_says_it_did_nothing(
    api, session_factory
) -> None:  # noqa: ANN001
    sid = (await session_factory())["session_id"]
    r = await api.post(f"/v1/sessions/{sid}/interrupt")
    assert r.status_code == 200
    body = r.json()
    assert body["interrupted"] is False
    assert body["status"] in ("idle", "running", "closed")


@pytest.mark.slow
async def test_as6_the_published_cap_is_the_enforced_cap(api, session_factory) -> None:  # noqa: ANN001
    """Fills the service to `max_sessions` and asks for one more.

    SLOW rather than costly: each session spawns a CLI process (seconds each,
    zero tokens). This is the only test that proves the published denominator is
    the real one, which is the entire reason `max_sessions` was published.
    """
    cap = flat((await api.get("/v1/deployment")).json())["max_sessions"]
    existing = len((await api.get("/v1/sessions")).json()["sessions"])

    for _ in range(cap - existing):
        await session_factory()

    r = await api.post("/v1/sessions", json={})
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert str(cap) in r.json()["detail"]
