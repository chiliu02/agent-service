"""Conformance: the clauses that need a real turn. AS-7 … AS-10, AS-17, AS-26.

**THESE COST MONEY** and carry the repo's `live` marker, so they are deselected
by default. Prompts are one word, and the session options are kept as small as
the build under test will accept -- `max_turns: 1` where that is supported.

    AGENT_SERVICE_TEST_BASE_URL=http://127.0.0.1:8000 \
    AGENT_SERVICE_TEST_MODEL=claude-haiku-4-5 uv run pytest -m live

**Name a cheap model for the build you are pointing at.** Without
`AGENT_SERVICE_TEST_MODEL` the run takes the deployment's own default, which on
some deployments is not the cheap one. The suite cannot pick for you: a model
name belongs to one SDK, and this package is not allowed to know which one it is
talking to.

They are the only way to verify the header clauses against a real server: an
in-process test proves the value is put on the response object, not that it
survives uvicorn, and Studio deletes a scanner on the strength of AS-8.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.live

PROMPT = {"prompt": "Reply with only the word: OK"}

# **The session options are a FIXTURE now, not a literal here** (2026-08-09).
# `cheap_options` in `conftest.py` builds them from `/v1/capabilities`: it drops
# anything the build publishes in `unsupported_options`, and it names a model
# only if `AGENT_SERVICE_TEST_MODEL` says so.
#
# What it replaced was `{"model": "claude-haiku-4-5", "max_turns": 1,
# "allowed_tools": []}`, and it had to go for a reason worth keeping: **it made
# this whole tier unrunnable against the second implementation.** `codex-python`
# refuses `max_turns` with a 400, so every test here failed at session creation
# -- before a single clause was reached, for a reason no clause is about. A
# suite that names one SDK's model is a suite that measures one build.
#
# The intent behind the old literal survives: every clause here is about
# identifiers, headers, framing and the TYPE of a cost field, none of it
# model-dependent, so the turn should be as small as the build will accept.
# **The cost warning is now the operator's to act on** -- unset the variable and
# a run costs whatever the deployment's default model costs.


async def test_as7_as10_the_header_is_sent_and_matches_the_body(
    api, session_factory, cheap_options, allows_supplied_sdk_session_id
) -> None:  # noqa: ANN001
    """AS-7 and AS-10: the header is sent, and it matches the body.

    **The supplied id is now conditional, and it had to be.** This test opened
    every session with `sdk_session_id=<uuid>` regardless of what the build
    publishes -- so on `codex-python`, which answers **400** to a supplied id,
    it failed at session creation with a problem document, never reaching the
    header it exists to check. That is the third assertion in this package found
    encoding one SDK's ability as everyone's requirement, after the four in
    `test_boot_gates.py` and the `CHEAP` literal above.

    AS-13 stopped being absolute in 0.18.0 and this is what it costs to honour
    that: the clause under test here is about the HEADER, so it is asserted
    either way, and the supplied id is added only where the build accepts one.
    """
    body_kwargs = dict(cheap_options)
    supplied = str(uuid.uuid4()) if allows_supplied_sdk_session_id else None
    if supplied:
        body_kwargs["sdk_session_id"] = supplied

    sid = (await session_factory(**body_kwargs))["session_id"]

    r = await api.post(f"/v1/sessions/{sid}/messages", json=PROMPT, timeout=180.0)
    assert r.status_code == 200

    body = r.json()
    assert r.headers["x-sdk-session-id"] == body["sdk_session_id"]
    if supplied:
        # AS-13 end to end, and only where the build publishes that it adopts
        # one: the id we assigned is the id the SDK used. On a build that
        # refuses the field there is no such claim to make -- the header
        # assertion above is the whole of AS-7 and AS-10 there.
        assert body["sdk_session_id"] == supplied


async def test_as8_the_header_is_present_on_the_first_streaming_turn(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    """The clause Studio deletes code on the strength of.

    A FRESH session, so this is genuinely turn 1 -- and no supplied id, so the
    value can only have come from the turn's own init message. If this passes,
    the streaming route really does read the first message before committing
    the response ON A REAL SERVER, not just in an ASGI transport.
    """
    sid = (await session_factory(**cheap_options))["session_id"]

    async with api.stream(
        "POST", f"/v1/sessions/{sid}/messages/stream", json=PROMPT, timeout=180.0
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        header = r.headers.get("x-sdk-session-id")
        # Read AFTER asserting the header: the header must be there before any
        # frame is consumed, which is the whole claim.
        body = "".join([chunk async for chunk in r.aiter_text()])

    assert header, "AS-8: the header was absent on a first streaming turn"
    assert f'"sdk_session_id": "{header}"' in body.replace('"sdk_session_id":"', '"sdk_session_id": "') or header in body


async def test_as26_the_stream_frames_arrive_as_sse_with_a_terminal_done(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    """Real SSE framing over a real server: `event:`/`data:` pairs, and a
    terminal `done` that carries the summary."""
    sid = (await session_factory(**cheap_options))["session_id"]

    names: list[str] = []
    async with api.stream(
        "POST", f"/v1/sessions/{sid}/messages/stream", json=PROMPT, timeout=180.0
    ) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                names.append(line.removeprefix("event: ").strip())

    assert names, "no SSE frames arrived"
    assert names[-1] == "done", names
    assert "system" in names


async def test_as17_cost_is_a_number_or_null_but_never_a_bare_zero_claim(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    """A completed turn either priced honestly or said it could not.

    Not asserting a value -- the point is the TYPE specification: `null` means
    nobody can say, a number means it was attributed. `0` is only legitimate
    alongside real token counts.
    """
    sid = (await session_factory(**cheap_options))["session_id"]
    body = (
        await api.post(f"/v1/sessions/{sid}/messages", json=PROMPT, timeout=180.0)
    ).json()

    cost = body["total_cost_usd"]
    usage = body.get("usage") or {}
    tokens = [v for k, v in usage.items() if "token" in k.lower() and isinstance(v, int)]

    assert cost is None or isinstance(cost, (int, float))
    if cost == 0 and tokens:
        assert any(t > 0 for t in tokens), (
            "AS-17: reported 0 with every token count zero -- that is the "
            "unpriced shape and must be null"
        )


async def test_the_session_record_reports_the_turn_afterwards(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    sid = (await session_factory(**cheap_options))["session_id"]
    await api.post(f"/v1/sessions/{sid}/messages", json=PROMPT, timeout=180.0)

    record = (await api.get(f"/v1/sessions/{sid}")).json()
    assert record["turns"] >= 1
    assert record["last_turn"] is not None
    assert record["last_turn"]["outcome_recorded"] is True
    # AS-16: the record and the turn agree about the SDK id.
    assert record["sdk_session_id"] == record["last_turn"]["sdk_session_id"]


# --- AS-34: a named field is null only when the build does not know ----------
#
# **The standing rule, and it is here because four defects of one shape landed
# in one day** (2026-08-09, user). The other three were each caught by looking:
# a helper nobody called, a capability nothing enforced, a permission mode that
# self-approved. This one was caught by accident while writing them up, and it
# is the only one a test could have found on its own.
#
# One build published five `token_usage` nulls on every real turn while the
# raw `usage` pass-through beside it carried
# `input_tokens: 15810, output_tokens: 320, cached_input_tokens: 15488`. The
# mapping read the wrong spelling at the wrong nesting level, and `.get`
# degrading to `null` made a wrong key indistinguishable from an absent one.
#
# **Why `null` is not a free answer.** AS-17a's rule is that `null` means NOT
# KNOWN -- never "not told", never "not bothered". A build that HAS the number
# and publishes `null` is making a false statement about its own capability, and
# it is the kind of false statement no document diff and no schema check can
# see, because the shape is perfectly correct.


def _count_leaves(payload, depth: int = 0) -> dict[str, int]:
    """Every integer leaf in the raw `usage`, keyed by its own name.

    Recursive because the pass-through is verbatim and its shape is the SDK's:
    one build reports counts at the top level, another nests them under `last`
    beside a cumulative `total`. This clause must not care which.
    """
    found: dict[str, int] = {}
    if isinstance(payload, dict) and depth < 3:
        for key, value in payload.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                found.setdefault(key, value)
            else:
                found.update(_count_leaves(value, depth + 1))
    return found


async def test_as34_a_count_the_build_reports_is_not_published_as_null(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    """If the raw `usage` carries counts, `token_usage` carries some of them.

    **Deliberately weak in one direction and strict in the other.** This suite
    cannot know any SDK's spellings -- that is the implementation's business --
    so it does not assert WHICH named field maps to which raw key. What it
    asserts is the thing that cannot be true of a correct build: **a response
    whose raw payload is full of numbers and whose named counts are entirely
    null.**

    That is exactly the failing state, and no correct mapping can produce it.
    A build whose SDK reports nothing at all passes, correctly and vacuously.
    """
    sid = (await session_factory(**cheap_options))["session_id"]
    body = (await api.post(f"/v1/sessions/{sid}/messages", json=PROMPT, timeout=180.0)).json()

    named = body["token_usage"]
    assert isinstance(named, dict), "AS-17a: token_usage is an object, never null"

    raw_counts = _count_leaves(body.get("usage"))
    if not raw_counts:
        pytest.skip("this build reported no usage at all; nothing to contradict")

    assert any(value is not None for value in named.values()), (
        "AS-34: the raw `usage` carries "
        f"{sorted(raw_counts)} and every named count in `token_usage` is null. "
        "A build that has the number and publishes null is stating it cannot "
        "report something it just reported"
    )


async def test_as34_input_and_output_are_populated_when_the_raw_payload_has_them(
    api, session_factory, cheap_options
) -> None:  # noqa: ANN001
    """The two counts every SDK reports, checked by name.

    Matched on the raw key rather than on a per-build table: any spelling of
    "input tokens" in the pass-through obliges `token_usage.input_tokens`. The
    cache and reasoning counts are deliberately NOT checked this way -- those
    genuinely differ per SDK, and one build's honest `null` there is another's
    defect.
    """
    sid = (await session_factory(**cheap_options))["session_id"]
    body = (await api.post(f"/v1/sessions/{sid}/messages", json=PROMPT, timeout=180.0)).json()

    raw = {k.lower().replace("_", ""): v for k, v in _count_leaves(body.get("usage")).items()}
    named = body["token_usage"]

    for direction in ("input", "output"):
        if f"{direction}tokens" in raw:
            assert named[f"{direction}_tokens"] is not None, (
                f"AS-34: the raw `usage` reports {direction} tokens and "
                f"`token_usage.{direction}_tokens` is null"
            )
