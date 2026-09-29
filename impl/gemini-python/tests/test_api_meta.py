"""The meta surface: `/healthz`, `/v1/deployment`, and the boot gates.

**Free: no agent, no credential, no container.** `create_app` deliberately does
not check the gates -- the lifespan does -- so an app can be built and its
document generated offline, which is how the published OpenAPI file is produced.

**The capability assertions are not restating the code.** Each one pins a
decision that a future edit could quietly reverse, and names what it would cost.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_spec.openapi.ordering import CANONICAL_PATHS
from agent_service.api import create_app
from agent_service.capabilities import ALWAYS_DISALLOWED_TOOLS, build_capabilities
from agent_service.config import BootRefused, Settings, check_boot
from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_NAME
from agent_spec.openapi.examples import flat


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "workspace_dir": tmp_path / "workspace",
        "agent_home_root": tmp_path / "home",
        "transcript_store": tmp_path / "store",
        "gemini_binary": Path("gemini-not-installed"),
        "require_credentials": False,
    }
    return Settings(**{**base, **kwargs})


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


def test_healthz_reports_the_credential_live(client: TestClient) -> None:
    """Credentials that disappear after boot do not stop a running service."""
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert set(body) >= {"credentials_configured", "workspace_dir", "auth_required"}


def test_the_document_version_is_the_contracts_not_the_builds(client: TestClient) -> None:
    """`info.version` is the DOCUMENT's, and the two streams diverge."""
    assert client.get("/openapi.json").json()["info"]["version"] == DOCUMENT_VERSION


def test_capabilities_names_this_build(client: TestClient) -> None:
    caps = flat(client.get("/v1/deployment").json())
    assert caps["impl"]["name"] == IMPLEMENTATION_NAME
    assert caps["spec"]["document_version"] == DOCUMENT_VERSION


def test_a_supplied_sdk_session_id_is_refused(client: TestClient) -> None:
    """GP-34, and the one most likely to break a client ported from another build.

    Neither interface accepts a caller's id on the durable resume path, so
    publishing `true` here would promise something no turn could keep.
    """
    assert flat(client.get("/v1/deployment").json())["allow_supplied_sdk_session_id"] is False


def test_the_shell_is_never_on_the_default_allowlist(client: TestClient) -> None:
    """GP-20: an unrestricted shell voids every other rule in the policy.

    Measured -- with `write_file` denied the agent wrote the file anyway through
    `run_shell_command`. If this ever passes with the shell present, the tool
    boundary has stopped being one.
    """
    caps = flat(client.get("/v1/deployment").json())
    assert "run_shell_command" not in caps["default_allowed_tools"]
    assert "run_shell_command" in caps["always_disallowed_tools"]
    assert set(ALWAYS_DISALLOWED_TOOLS) <= set(caps["always_disallowed_tools"])


def test_cost_cannot_be_promised_so_a_budget_is_refused(client: TestClient) -> None:
    """GP-16: the agent reports tokens and latency and no monetary figure.

    A build that accepted `max_budget_usd` would be accepting an option nothing
    could apply, which is the defect the Codex build shipped twice.
    """
    refused = {option["field"] for option in flat(client.get("/v1/deployment").json())["unsupported_options"]}
    assert {"max_budget_usd", "effort"} <= refused


def test_the_enforced_limits_are_promises_not_a_config_dump(client: TestClient) -> None:
    """A number in `limits` is a promise about behaviour.

    `turn_timeout_s` is enforced by killing the process, which is the only way
    to end a turn on this agent (GP-02).
    """
    limits = flat(client.get("/v1/deployment").json())["limits"]
    assert limits["turn_timeout_s"] > 0
    assert limits["max_sessions"] > 0


def test_permission_enforcement_is_none_and_that_is_not_no_boundary(
    tmp_path: Path,
) -> None:
    """The vocabulary has no value for what this build actually does.

    `Literal["none", "hook"]` was written for a build with an in-process hook.
    This one enforces with a generated admin policy, so `"none"` is the truthful
    answer to the question the field asks -- is there in-process write
    confinement -- and the Codex build reached the same place independently.
    Pinned so that nobody "fixes" it to `"hook"`, which would be false.
    """
    assert build_capabilities(_settings(tmp_path)).behaviour.permission_enforcement == "none"


def test_the_credential_gate_refuses_and_names_its_blind_spot(tmp_path: Path) -> None:
    """Exit 3, with a remedy -- including the route the gate cannot see (GP-07).

    A mounted home carrying an earlier login satisfies the agent and is invisible
    here, so the refusal says so rather than leaving it to be discovered.
    """
    with pytest.raises(BootRefused) as refused:
        check_boot(_settings(tmp_path, require_credentials=True))
    message = str(refused.value)
    assert "GEMINI_API_KEY" in message
    assert "settings.json" in message, "the blind spot is not named"
    assert "AGENT_SERVICE_REQUIRE_CREDENTIALS=false" in message


def test_the_gate_passes_when_a_provider_selector_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selector satisfies the boot gate while authenticating nothing (GP-07).

    That is why the two lists are published separately, and the positive control
    for the refusal above.
    """
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    check_boot(_settings(tmp_path, require_credentials=True))


def test_the_documents_paths_are_in_canonical_order(tmp_path: Path) -> None:
    """**All three builds publish their operations in ONE order** (AS-31).

    FastAPI writes `paths` in route-registration order, so this is the only
    thing standing between the document and whatever order the decorators
    happen to run in -- and nothing else would notice: `freeze` hashes each
    document against its own copy, the core is a set intersection, and AS-24's
    check is a dict comparison, which in Python ignores key order.

    So the three documents drifted into two different orders and stayed green.
    Isomorphism that has to be established by inspection is not obvious, and
    the point of the core is that it should be.

    **A new route fails HERE**, which is where the fix is one line: add it to
    `CANONICAL_PATHS` in the place a reader would look for it. `canonical()`
    appends an unlisted path rather than raising, deliberately -- a 500 on
    `/openapi.json` in a running service is a worse failure than a
    late-sorted entry.
    """
    served = list(create_app(_settings(tmp_path)).openapi()["paths"])
    assert served == list(CANONICAL_PATHS), (
        "the served document's path order is not the canonical one; "
        f"got {served}"
    )


def test_two_measured_facts_are_PUBLISHED_rather_than_left_in_prose(
    client: TestClient,
) -> None:
    """AS-32: a client acts on a value it reads, not on a document it was sent.

    Both of these lived only in this build's guide until 2026-08-12, and both
    are things a client must ACT on -- so prose was the wrong home:

    * `turn_token_overhead` -- ~7,000 input tokens before the prompt is read
      (GP-44). It decides whether batching matters, and here it does: turn COUNT
      predicts spend, not prompt length.
    * `usage_counts_tool_calls` -- **false**, measured (GP-43). A turn carrying
      a `tool_use` and a `tool_result` reported `0`, so a client that asks
      "did this turn use tools" must count events instead.

    `null` on either means a build has not measured it. This one has.
    """
    caps = flat(client.get("/v1/deployment").json())
    assert caps["turn_token_overhead"] == 7000.0
    assert caps["usage_counts_tool_calls"] is False


def test_limits_carries_only_things_this_build_ENFORCES(client: TestClient) -> None:
    """A number in `limits` is a promise about behaviour, not a measurement.

    Which is why `turn_token_overhead` is NOT in here: nothing enforces it, and
    a caller reading `limits` is reading what this service will do to them.
    """
    limits = flat(client.get("/v1/deployment").json())["limits"]
    assert set(limits) == {"turn_timeout_s", "max_sessions", "session_idle_ttl_s"}


def test_the_published_example_is_what_a_live_instance_actually_answers(
    client: TestClient,
) -> None:
    """**The document shows VALUES, not just a shape** -- and they must be true.

    An OpenAPI document describes the shape of `/v1/deployment` and says
    nothing about what this build answers, so a consumer holding all three
    builds' documents still could not see how the builds differ without starting
    three containers. The example closes that, and this test is what keeps it
    honest: an example nothing checks is a comment.

    **Deployment-dependent fields are excluded on purpose.** The example is
    built from this build's defaults, because AS-24 requires the service to
    serve exactly the published document -- an example carrying a live port or
    cap would break that for every deployment that changed one.
    """
    from agent_spec.openapi.examples import placeholdered  # noqa: PLC0415

    from agent_service.capabilities import DEPLOYMENT_DEPENDENT  # noqa: PLC0415

    document = client.app.openapi()  # type: ignore[attr-defined]
    published = flat(document["paths"]["/v1/deployment"]["get"]["responses"]["200"]
                 ["content"]["application/json"]["example"])
    live_payload = client.get("/v1/deployment").json()
    live = flat(live_payload)

    # The versions that move on the implementation stream are published as a
    # placeholder, so compare against a live payload with the same rule applied
    # rather than excluding whole objects: `sdk.name` stays checked, and the
    # rule is stated once, in the module that publishes it.
    expected = flat(placeholdered(live_payload))

    assert set(published) == set(live), "the example and the payload differ in SHAPE"
    differing = {
        field for field in live
        if field not in DEPLOYMENT_DEPENDENT and published[field] != expected[field]
    }
    assert not differing, (
        f"the published example no longer matches what this build answers: {differing}"
    )
    # And the excluded set must be real fields, so a rename cannot silently
    # widen the exemption into "nothing is checked".
    assert DEPLOYMENT_DEPENDENT <= set(live), "DEPLOYMENT_DEPENDENT names a field that is gone"


def test_the_example_carries_the_differences_a_consumer_compares_builds_on(
    client: TestClient,
) -> None:
    """The point of the exercise: the interesting facts are IN the document."""
    document = client.app.openapi()  # type: ignore[attr-defined]
    published = flat(document["paths"]["/v1/deployment"]["get"]["responses"]["200"]
                 ["content"]["application/json"]["example"])
    assert published["allow_supplied_sdk_session_id"] is False
    assert published["always_disallowed_tools"] == ["run_shell_command"]
    assert published["usage_counts_tool_calls"] is False
    assert published["turn_token_overhead"] == 7000.0
    assert published["mcp"]["transports"] == ["stdio", "sse", "http"]


# --- token_usage, against the payload a real turn actually produced ----------
#
# **This build published five nulls on every turn from 0.0.1 until 2026-08-15**
# -- the field was never mapped at all, while the counts sat in the raw `usage`
# beside them (GP-60). The consumer found it, not this suite, and the reason
# this suite could not is that the fake agent reported no per-direction counts
# either: a fixture consistent with the bug.
#
# The numbers below are one real turn's per-model telemetry, put through the
# conversion read out of the installed CLI. Do not tidy them -- the spelling
# and the arithmetic are the assertion.

#: Exactly the shape a `result` event carries in `stream-json` (GP-60).
_MEASURED_STATS = {
    "total_tokens": 11911,
    "input_tokens": 11251,
    "output_tokens": 39,
    "cached": 8103,
    "input": 3148,
    "duration_ms": 4257,
    "tool_calls": 0,
    "models": {
        "gemini-3.5-flash": {"total_tokens": 10877, "input_tokens": 10637,
                             "output_tokens": 3, "cached": 8103, "input": 2534},
        "gemini-3.1-flash-lite": {"total_tokens": 1034, "input_tokens": 614,
                                  "output_tokens": 36, "cached": 0, "input": 614},
    },
}


def test_the_named_counts_are_read_from_a_real_payload() -> None:
    """Three of five populated, and the two nulls are for a measured reason.

    This agent has no cache-WRITE counter at all, and its reasoning count --
    `thoughts`, which it does keep per model -- is dropped by the conversion
    into the `result` event. So both nulls mean *this build cannot report it*,
    which is what all five were saying untruthfully until this was fixed.
    """
    from agent_service.api import _token_usage  # noqa: PLC0415

    usage = _token_usage(_MEASURED_STATS)
    assert usage.input_tokens == 11251
    assert usage.output_tokens == 39
    assert usage.cache_read_tokens == 8103
    assert usage.cache_write_tokens is None
    assert usage.reasoning_output_tokens is None


def test_input_tokens_already_includes_the_cached_half() -> None:
    """**The row a consumer summing these must act on** (GP-60).

    The agent's `input_tokens` is the sum of `tokens.prompt`, and `cached` is a
    subset of it -- so `input_tokens + cache_read_tokens` double-counts here and
    is correct on the Claude build, where the SDK reports them disjointly. This
    test pins the arithmetic that makes that claim true rather than assumed:
    per model, `prompt == input + cached`.
    """
    from agent_service.api import _token_usage  # noqa: PLC0415

    usage = _token_usage(_MEASURED_STATS)
    assert usage.input_tokens is not None and usage.cache_read_tokens is not None
    assert usage.input_tokens >= usage.cache_read_tokens
    assert _MEASURED_STATS["input_tokens"] == (
        _MEASURED_STATS["input"] + _MEASURED_STATS["cached"]
    ), "prompt tokens are the non-cached half plus the cached half"


def test_a_stats_block_without_counts_is_all_null() -> None:
    """Null when the counts genuinely are not there -- an absent stats block, a
    turn that produced no envelope, or a shape whose keys moved. `null` is the
    honest answer to all three, and the mapping is pinned above so a rename
    cannot pass for one."""
    from agent_service.api import _token_usage  # noqa: PLC0415

    for payload in (None, {}, {"duration_ms": 10}, {"input_tokens": "many"}):
        usage = _token_usage(payload)
        assert usage.input_tokens is None, payload
        assert usage.output_tokens is None, payload
        assert usage.cache_read_tokens is None, payload


def test_the_published_document_embeds_no_version_that_moves_under_it() -> None:
    """The defect this rule exists for, checked against the FILE.

    A build bumps for any reason, several times between two documents. A
    published document is frozen -- by `freeze`, and by AS-24, which requires a
    running service to serve exactly the document published for its version. So
    a real implementation version inside the example means the first bump after
    a cut makes the served document differ from the published one, permanently,
    for a change that touched no route.

    It survived this long only because every version so far has been a
    `-snapshot` and a snapshot can be regenerated. Read from the file rather
    than from the app, because the file is the artifact that gets frozen.
    """
    import json  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    from agent_spec.openapi.examples import MOVING_VERSIONS, VERSION_PLACEHOLDER  # noqa: PLC0415

    from agent_service.versions import (  # noqa: PLC0415
        DOCUMENT_VERSION,
        IMPLEMENTATION_NAME,
        IMPLEMENTATION_VERSION,
    )

    root = _Path(__file__).resolve().parents[3]
    directory = root / "spec" / "releases" / DOCUMENT_VERSION
    if not directory.is_dir():
        directory = root / "spec" / "openapi"
    document = json.loads(
        (directory / f"{IMPLEMENTATION_NAME}-{DOCUMENT_VERSION}.json")
        .read_text(encoding="utf-8")
    )
    example = (document["paths"]["/v1/deployment"]["get"]["responses"]["200"]
               ["content"]["application/json"]["example"])

    for path in sorted(MOVING_VERSIONS):
        # Dotted through the groups since 2026-09-03: `service.impl.version`
        # rather than `impl.version`, because the payload is no longer flat.
        value = example
        for step in path.split("."):
            value = value[step]
        assert value == VERSION_PLACEHOLDER, (
            f"{path} is {value!r} in the published document. A version that "
            f"moves on the implementation stream cannot sit in an artifact "
            f"that gets frozen."
        )
    # **A BLANKET SUBSTRING SCAN, and it needs one exemption since 0.19.0.**
    # The loop above pins each field that must be a placeholder; this catches a
    # version that reached the example by some path nobody thought of.
    #
    # It cannot distinguish two versions that are the same STRING, and at 0.19.0
    # they are: all three implementations were set to the document's number, so
    # `spec.document_version` legitimately carries it. That field belongs in a
    # frozen document -- it is what the document IS -- so the scan runs over the
    # example with it removed rather than being deleted for being inconvenient.
    scanned = {k: v for k, v in example["service"].items() if k != "spec"}
    scanned.update({k: v for k, v in example.items() if k != "service"})
    assert IMPLEMENTATION_VERSION not in json.dumps(scanned), (
        "this build's version is somewhere in the published example"
    )
    # The one version that BELONGS there: it moves with the document itself.
    assert example["service"]["spec"]["document_version"] == DOCUMENT_VERSION
