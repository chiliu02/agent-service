"""Conformance: the core, and the extensions a client must be told about.

**AS-31, AS-32 and AS-33 — Plan 8 step 6.** All three exist because the platform
grew a second implementation and one clause could not survive it: AS-24 demanded
one byte-identical document from every build, and a document that *documents
behaviour* cannot be identical across builds without one of them being wrong about
the service serving it.

The answer was not to relax AS-24. It keys the document to the implementation
instead, and three clauses take over what it used to imply:

| | |
|---|---|
| **AS-31** | every implementation's document is structurally identical to `openapi-<version>-core.json`. Prose may differ; status codes and headers may be **added** |
| **AS-32** | an extension a client must act on is published on `/v1/deployment`, so a client branches on a value it reads rather than on which image it believes it has |
| **AS-33** | a build declares every status its own error table can produce. Enforced in each implementation's own suite, because reachability is a fact about source and this package imports no implementation |

**Why AS-32 is the load-bearing one.** AS-31 permits additions, and without AS-32
that permission absorbs defects: a build could add a status code, or fail to have
one, and nothing would tell a client which. The measured case is a 503 that
*neither* build declared and one could produce — invisible to any comparison of the
two documents, because comparison only finds what one has and the other lacks.

**These need a running service and no turn**, so they cost nothing to run.
"""

from __future__ import annotations

from typing import Any

import pytest

# **A SECOND implementation of the core walk, on purpose** -- see the long comment
# at the foot of `predicates.py`. A conformance suite that imported the generator
# could not see a bug in it.
from .predicates import core_failures, document_leaves
from .predicates import DEPLOYMENT_GROUPS, flat


async def test_as31_the_served_document_contains_the_core(
    api, served_core: dict[str, Any]
) -> None:  # noqa: ANN001
    """The served document contains every leaf the core states.

    **One-directional, and that is AS-31 rather than a weaker check.** An
    implementation may ADD -- a status code it can reach, a header it can send --
    and the clause permits it; what it may not do is lack or contradict anything
    the core states. Extras are governed by AS-32 below.
    """
    served = (await api.get("/openapi.json")).json()
    failures = core_failures(served, served_core)
    assert not failures, (
        f"AS-31: the served document fails to contain the core in "
        f"{len(failures)} place(s):\n  " + "\n  ".join(failures[:15])
    )


async def test_as31_the_core_is_not_trivially_small(
    served_core: dict[str, Any]
) -> None:
    """A guard on the guard, and it is not paranoia.

    The core is DERIVED by intersecting the implementations' documents, and
    intersection is monotonic: a build that lacks a route silently removes it for
    every build. The failure mode is not an error -- it is a core that quietly
    shrinks toward empty while every implementation goes on "conforming" against
    it.

    So this pins an order of magnitude rather than an exact number. It was 586
    leaves when two implementations existed; a core that has collapsed to a
    handful means the generator intersected something it should not have.
    """
    count = len(document_leaves(served_core))
    assert count > 400, (
        f"AS-31: the core has only {count} leaves. Intersection is monotonic, so "
        "this is what a build that lacks whole routes looks like -- check what "
        "the last implementation to publish a document actually served"
    )


async def test_as32_the_query_header_capability_predicts_the_document(
    api,
) -> None:  # noqa: ANN001
    """`query_reports_sdk_session_id` agrees with the document, both directions.

    **This is the clause that replaced a prohibition.** AS-11 used to forbid
    `/v1/query` from declaring `x-sdk-session-id` -- a rule generalised out of one
    SDK's timing, which forbade a build from giving a consumer *more*. A build
    whose conversation id exists before the first turn can send that header, and
    one whose id arrives with the turn cannot, because its 200 is already
    committed.

    So the difference is real, permitted, and **published**: a relay reads the id
    off a header when this is true and must scan the body when it is false. Both
    directions are asserted, because a capability that only has to be right when
    it says `true` is a capability a build can get right by accident.
    """
    capabilities = flat((await api.get("/v1/deployment")).json())
    declared = "query_reports_sdk_session_id" in capabilities
    assert declared, (
        "AS-32: /v1/capabilities does not publish query_reports_sdk_session_id, "
        "so nothing tells a client whether the one-shot route sends the header"
    )
    served = (await api.get("/openapi.json")).json()
    headers = served["paths"]["/v1/query"]["post"]["responses"]["200"].get("headers", {})
    in_document = "x-sdk-session-id" in headers

    assert capabilities["query_reports_sdk_session_id"] == in_document, (
        f"AS-32: capabilities says query_reports_sdk_session_id="
        f"{capabilities['query_reports_sdk_session_id']} but the document "
        f"{'declares' if in_document else 'does not declare'} the header on "
        f"POST /v1/query. A client branching on the capability would be wrong"
    )


async def test_as32_the_session_slot_capability_predicts_the_429(
    api,
) -> None:  # noqa: ANN001
    """`query_consumes_a_session_slot` agrees with the document, both directions.

    A one-shot implemented as a real throwaway session competes with the caller's
    own sessions for `max_sessions` and can answer 429; one that drives the SDK
    directly cannot. That decides whether a caller needs a retry path on that
    route at all, which is a branch, which is why it is published.
    """
    capabilities = flat((await api.get("/v1/deployment")).json())
    assert "query_consumes_a_session_slot" in capabilities, (
        "AS-32: /v1/capabilities does not publish query_consumes_a_session_slot"
    )
    served = (await api.get("/openapi.json")).json()
    declares_429 = "429" in served["paths"]["/v1/query"]["post"]["responses"]

    assert capabilities["query_consumes_a_session_slot"] == declares_429, (
        f"AS-32: capabilities says query_consumes_a_session_slot="
        f"{capabilities['query_consumes_a_session_slot']} but the document "
        f"{'declares' if declares_429 else 'does not declare'} a 429 on "
        f"POST /v1/query"
    )


#: A truthy value per `RunOptions` field that a build may refuse, so the probe
#: below sends something the refusal can actually see. Truthiness matters: an
#: empty list or object asks for nothing, and a build is right not to refuse it.
_OPTION_PROBES: dict[str, Any] = {
    "allowed_tools": ["Read"],
    "disallowed_tools": ["Bash"],
    "setting_sources": ["project"],
    "max_turns": 5,
    "max_budget_usd": 1.0,
    "mcp_servers": {"probe": {"type": "http", "url": "https://mcp.example.invalid/mcp"}},
    "system_prompt": {"type": "preset", "preset": "claude_code"},
    # Added 2026-08-11 for a third implementation, which refuses both. The
    # table is a probe rather than a clause: a build that does not publish one
    # of these is unaffected, and a build that does could not be checked at all
    # until the suite knew how to send it.
    "effort": "high",
    "strict_mcp_config": True,
}


async def test_as32_every_unsupported_option_published_is_really_refused(
    api,
) -> None:  # noqa: ANN001
    """`unsupported_options` predicts a 400, and the 400 says which condition.

    **This is the clause's own failure mode, measured.** A build published
    `allow_mcp_servers: false` and accepted `mcp_servers` anyway; the helper that
    computed the refusal list was unit-tested six ways and called by nothing. A
    capability that says one thing while the code does another is worse than no
    capability, because a client has no way to find out.

    **Empty is a passing answer.** A build whose SDK covers the whole surface
    refuses nothing, the loop below does not run, and that is the clause holding
    rather than being skipped -- there is no difference for a client to act on.

    **`values` is checked in BOTH directions, and the second one is the point**
    (2026-08-12). An entry narrowed to particular values claims two things: those
    values are refused, and the others are honoured. A build that published
    `values: [false]` and then refused `true` as well would be back to the defect
    this clause exists for, wearing a narrower coat -- so where the probe table
    holds a value the entry does NOT name, it is sent and must not be refused.

    Free: the refusal is answered before a session exists, so nothing spawns. The
    accepted direction does open a session, which takes no turn and costs
    nothing, and it is closed again below.
    """
    published = flat((await api.get("/v1/deployment")).json()).get("unsupported_options")
    assert isinstance(published, list), (
        "AS-32: /v1/capabilities does not publish unsupported_options as a list"
    )

    for entry in published:
        # `{field, types?, values?}`. **It was a bare string until a consumer showed the
        # string could not be acted on**: six entries were identifiers and one
        # was `"system_prompt (preset form)"`, so a client comparing field names
        # never matched it. A difference published in a form nobody can branch
        # on is the failure this clause exists to prevent.
        assert isinstance(entry, dict) and "field" in entry, (
            f"AS-32: unsupported_options carries {entry!r}, which is not an "
            "object with a `field`. A client cannot compare prose to the key it "
            "was about to send"
        )
        field = entry["field"]
        assert field in _OPTION_PROBES, (
            f"unsupported_options names {field!r}, which is not a RunOptions field "
            "this suite knows how to send. Either the name is wrong or the probe "
            "table needs the new field"
        )
        # **A value-scoped entry must be probed with a value it names**, or the
        # test asks the wrong question: the table's `strict_mcp_config: True` is
        # the value one build HONOURS, so sending it would assert a 400 that
        # should not happen and fail a build for being correct.
        values = entry.get("values")
        probe = values[0] if values else _OPTION_PROBES[field]

        r = await api.post("/v1/sessions", json={"options": {field: probe}})
        assert r.status_code == 400, (
            f"AS-32: {field}={probe!r} is published as unsupported and "
            f"POST /v1/sessions answered {r.status_code}. Publishing a refusal "
            "that does not happen is the failure this clause exists to prevent"
        )
        assert r.headers["content-type"].startswith("application/problem+json")
        problem_type = r.json().get("type") or ""
        if values:
            # **A narrower entry earns a narrower type, and demanding the
            # generic one here would be wrong.** The field IS supported -- it is
            # this value that is not -- so a document saying `unsupported-options`
            # would name a condition that did not occur. What the clause needs is
            # that the reason is a stable identifier rather than prose.
            assert problem_type.startswith(
                "https://agent-service.invalid/problems/"
            ), (
                f"AS-32: refusing {field}={probe!r} answered type "
                f"{problem_type!r}, which is not a documented problem type. A "
                "client must be able to branch on the reason, and a title is "
                "prose"
            )
        else:
            assert problem_type == (
                "https://agent-service.invalid/problems/unsupported-options"
            ), (
                "a refusal a client must branch on carries a documented problem "
                "`type`; a title is prose and prose may change"
            )

        # The other direction: a value the entry does not name must be honoured,
        # which is what makes `values` narrower than naming the field outright.
        allowed = _OPTION_PROBES[field]
        if values and allowed not in values:
            r = await api.post("/v1/sessions", json={"options": {field: allowed}})
            assert r.status_code != 400, (
                f"AS-32: {field} publishes values={values!r}, so {allowed!r} is "
                "not among what it refuses -- and POST /v1/sessions refused it "
                "anyway. An entry narrowed to some values promises the rest work"
            )
            if r.status_code < 300:
                await api.delete(f"/v1/sessions/{r.json()['session_id']}")


def _group_properties(served: dict, group: str) -> dict:
    """One group's declared properties, resolved through `Deployment`'s `$ref`.

    The suite resolves the reference itself rather than trusting a name: a
    document that declared a group and pointed it at nothing would otherwise
    pass a check about what it declares.
    """
    schemas = served.get("components", {}).get("schemas", {})
    ref = (schemas.get("Deployment", {}).get("properties", {})
           .get(group, {}).get("$ref", ""))
    assert ref, f"the document declares no {group!r} group on Deployment"
    return schemas.get(ref.rsplit("/", 1)[-1], {}).get("properties", {})


async def test_as32_every_published_capability_is_in_the_document(
    api,
) -> None:  # noqa: ANN001
    """A capability the running service publishes is declared in its document.

    **The failure this catches is a field that exists only at runtime**, which is
    worse than a missing one: a client that reads it works against this container
    and cannot know the field is not part of the contract. Generated clients would
    not have it at all.
    """
    capabilities = flat((await api.get("/v1/deployment")).json())
    served = (await api.get("/openapi.json")).json()
    declared = set(
        prop
        for group in DEPLOYMENT_GROUPS
        for prop in _group_properties(served, group)
    )
    undeclared = sorted(set(capabilities) - declared)
    assert not undeclared, (
        f"AS-32: the service publishes {undeclared} on /v1/capabilities and the "
        "document's Deployment groups do not declare them, so a generated "
        "client cannot see them"
    )


async def test_the_named_token_counts_are_declared_and_always_present(
    api,
) -> None:  # noqa: ANN001
    """`RunResponse.token_usage` is required, and its fields are nullable.

    Asked for by a consumer whose only structured record of a turn's cost was an
    untyped pass-through with a different shape per implementation.

    **Required object, nullable fields**, and the asymmetry is the whole design: a
    `null` object could not be told apart from "this build reports no counts",
    while a `null` field says *not reported* about one specific number. `null` is
    never zero -- a build with no cache-write counter reporting `0` would show a
    premium charge as free.
    """
    served = (await api.get("/openapi.json")).json()
    schemas = served["components"]["schemas"]
    assert "TokenUsage" in schemas, "TokenUsage is not in the document"

    run_response = schemas["RunResponse"]
    assert "token_usage" in run_response.get("properties", {}), (
        "RunResponse does not carry token_usage"
    )

    properties = schemas["TokenUsage"].get("properties", {})
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_output_tokens",
    ):
        assert field in properties, f"TokenUsage does not declare {field}"
        # Pydantic v2 emits `anyOf: [{integer}, {null}]`, never `nullable: true`.
        any_of = properties[field].get("anyOf", [])
        assert any(member.get("type") == "null" for member in any_of), (
            f"TokenUsage.{field} is not nullable, so it cannot report "
            "'not counted' as anything but a misleading zero"
        )


async def test_the_idle_ttl_is_published_so_a_reconciliation_window_can_be_sized(
    api,
) -> None:  # noqa: ANN001
    """`limits.session_idle_ttl_s` is published.

    **The one figure in `limits` that bounds how long the SERVICE keeps something**
    rather than what a request may ask for, and it is there because a consumer
    reconciling a lost `201` does it by listing sessions -- so it needs to know how
    long an unmatched record survives the idle reaper. A window longer than the TTL
    searches for a record that has been closed and forgotten.
    """
    limits = flat((await api.get("/v1/deployment")).json())["limits"]
    assert "session_idle_ttl_s" in limits, (
        "limits does not publish session_idle_ttl_s, so a consumer cannot size a "
        "reconciliation window"
    )
    assert limits["session_idle_ttl_s"] > 0


async def test_every_limit_published_is_one_this_build_enforces(
    api,
) -> None:  # noqa: ANN001
    """A figure in `limits` is a promise about behaviour, not a config dump.

    **Measured as a real defect on the Codex build**, which published a 600-second
    turn budget, a turn cap and a spend cap while applying none of them: the
    options were named as service-enforced and enforced by nothing. Publishing a
    limit nothing applies is the same failure as declaring a status code nothing
    produces, pointing the other way.

    This asserts the *pairing* rather than the values: a `max_allowed_*` without
    its `default_*` sibling, or the reverse, means one of them was published by
    habit.
    """
    limits = flat((await api.get("/v1/deployment")).json())["limits"]
    for default, cap in (
        ("default_max_turns", "max_allowed_turns"),
        ("default_max_budget_usd", "max_allowed_budget_usd"),
        ("default_request_timeout_s", "max_allowed_timeout_s"),
    ):
        assert (default in limits) == (cap in limits), (
            f"limits publishes exactly one of {default}/{cap}. Either both are "
            "enforced and both belong, or neither is and neither does"
        )
        if default in limits:
            assert limits[default] <= limits[cap], (
                f"limits.{default} exceeds limits.{cap}, so the default is a "
                "value a request may not ask for"
            )


@pytest.mark.parametrize(
    "field",
    ["auth_enforced", "endpoint_source", "ca_bundle_source", "model_api", "schema_revision"],
)
async def test_the_preboot_fields_are_not_also_on_capabilities(
    api, field: str
) -> None:  # noqa: ANN001
    """These three belong to the PRE-BOOT surface only.

    **Both are facts about the binary, and the pre-boot spec is where a caller can
    read them before starting a container** -- which is the moment the decision
    they inform is made. `auth_required` on `/v1/deployment` is the different,
    instance-level fact: *a token is configured here*.

    Publishing them in both places would create two sources for one fact and
    invite them to disagree. `test_boot_gates.py` asserts they are present where
    they belong; this asserts they are absent where they do not.
    """
    capabilities = flat((await api.get("/v1/deployment")).json())
    assert field not in capabilities, (
        f"{field} is on /v1/capabilities as well as the pre-boot spec. One fact, "
        "one source -- and this one is needed before a service exists to ask"
    )


async def test_as32_the_sandbox_capability_is_published(api) -> None:  # noqa: ANN001
    """What confines the AGENT's tools is a difference a client must act on.

    **The measured case is the two builds this platform has.** One runs its
    shell under a sandbox that blocks egress; the other runs it unconfined and
    relies on the container. The same Agent -- one whose capability is *install
    this package* or *call this API from a shell command* -- works on one and
    fails on the other, and until this field existed nothing published said so.

    **Shape only, and deliberately.** Proving `network_access: false` means
    taking a turn and watching a tool fail, which is a paid measurement each
    implementation makes for itself and records in its own build's notes.
    What the specification requires here is that every build ANSWER -- a third
    implementation cannot leave it out and be conforming.
    """
    capabilities = flat((await api.get("/v1/deployment")).json())

    sandbox = capabilities.get("sandbox")
    assert isinstance(sandbox, dict), (
        "AS-32: /v1/capabilities does not publish `sandbox`, so nothing tells a "
        "client whether the agent's own tools are confined inside the container"
    )
    for field in ("network_access", "confines_writes_to_workspace"):
        assert isinstance(sandbox.get(field), bool), (
            f"AS-32: sandbox.{field} is {sandbox.get(field)!r} rather than a "
            "boolean. A build must answer this rather than leave it unsaid -- "
            "absent reads as 'not told', which is the ambiguity AS-17a rejects"
        )


async def test_as32_what_bounds_a_long_mcp_tool_call_is_published(api) -> None:  # noqa: ANN001
    """A tool call that runs for minutes must not be discoverable by experiment.

    **The measured case is the three builds this platform has**, and no two are
    bounded by the same timer: one abandons a call that has not begun, one
    abandons a call that has gone quiet, one abandons a healthy call on wall
    clock, and one imposes nothing at all. A client whose MCP tool waits on a
    human or on another agent gets a named timeout, a bare transport error or a
    success from one mistake, and would reasonably read that as three defects.

    **Shape only, and deliberately.** Proving a bound means holding a call open
    until it dies, which is a measurement each implementation makes for itself
    against its own agent. What the specification requires is that every build
    ANSWER -- with a number, or with `null` meaning it imposes no bound of that
    kind. Absent reads as 'not told', which is the ambiguity AS-17a rejects.

    **`progress_resets_idle` is the one field allowed a third answer**, and the
    consistency rule is what makes it readable: it may be null only where the
    build has **no bound of any kind** — nothing to reset and nothing to say.
    The moment one timer exists the build must answer true or false, and `false`
    is not a formality: a build may ask for progress, sending a `progressToken`
    on every call, and still run a wall-clock cap underneath that progress
    cannot move. Declining to say which is publishing half a fact.
    """
    # **`behaviour.mcp_tool_call` since 2026-09-03**, when the timers left the
    # object describing what a caller may express. The clause is unchanged: a
    # build must still say what ends a long tool call.
    tool_call = (await api.get("/v1/deployment")).json()["behaviour"].get("mcp_tool_call")

    assert isinstance(tool_call, dict), (
        "AS-32: /v1/deployment does not publish `behaviour.mcp_tool_call`, so nothing "
        "tells a client how long an MCP tool call may be held open"
    )
    for field in ("request_timeout_s", "idle_timeout_s", "total_timeout_s"):
        value = tool_call.get(field, "missing")
        assert value is None or (isinstance(value, int) and value > 0), (
            f"AS-32: mcp.tool_call.{field} is {value!r}. It must be a positive "
            "number of seconds, or null to say this build imposes no bound of "
            "that kind -- a build must answer rather than leave it unsaid"
        )

    resets = tool_call.get("progress_resets_idle", "missing")
    assert resets is None or isinstance(resets, bool), (
        f"AS-32: mcp.tool_call.progress_resets_idle is {resets!r} rather than a "
        "boolean or null"
    )
    unbounded = all(
        tool_call[field] is None
        for field in ("request_timeout_s", "idle_timeout_s", "total_timeout_s")
    )
    if unbounded:
        assert resets is None, (
            "mcp.tool_call.progress_resets_idle answers true/false about timers "
            "this build does not have; null is the only honest value there"
        )
    else:
        assert resets is not None, (
            "mcp.tool_call publishes a bound and will not say whether "
            "`notifications/progress` clears it -- which is the difference "
            "between a stream that survives and one that dies looking healthy, "
            "and `false` is a real answer: a build can send a `progressToken` "
            "on every call and still run a cap that progress cannot move"
        )


async def test_a_422_matches_the_schema_its_own_document_declares(api) -> None:  # noqa: ANN001
    """The clause that would have caught it, and nothing did for months.

    **The consumer found this, not the suite** (2026-08-19). One build answered a
    422 with a shape its own document did not describe: `detail` a string where
    the declared schema said an array, three properties the schema did not
    define, and no `loc`. Two builds satisfied the declaration and contradicted
    their own consumer guide instead. Three artifacts, no two agreeing, and every
    tier green throughout.

    **Nothing here asserted that a declared response body matches its schema.**
    AS-24 compares the served document to the published one -- both were equally
    wrong. AS-31 compares the three documents to the core -- all three declared
    the same thing. AS-33 asserts a build declares every status it can produce,
    which this build did. The gap was between the document and the wire, on a
    path no clause looked at.

    **A malformed body is the cheapest response to provoke**, needs no session
    and costs nothing, which is why this is checked here rather than left to each
    build's own suite.
    """
    served = (await api.get("/openapi.json")).json()
    declared = (
        served["paths"]["/v1/sessions"]["post"]["responses"]
        .get("422", {})
        .get("content", {})
    )
    assert declared, "AS-33: POST /v1/sessions declares no 422 body at all"

    media_type, body_spec = next(iter(declared.items()))
    ref = body_spec.get("schema", {}).get("$ref", "")
    component = ref.rsplit("/", 1)[-1]
    assert component, f"the 422 declares no schema reference, only {body_spec}"

    response = await api.post("/v1/sessions", json={"options": "not-an-object"})
    assert response.status_code == 422, (
        f"a string where `options` must be an object should be a 422, got "
        f"{response.status_code}"
    )
    assert response.headers["content-type"].startswith(media_type), (
        f"the document declares `{media_type}` for the 422 and the service "
        f"answered `{response.headers['content-type']}`"
    )

    schema = served["components"]["schemas"][component]
    body = response.json()
    missing = [
        name for name in schema.get("required", ()) if name not in body
    ]
    assert not missing, (
        f"the 422 body is missing {missing}, which `{component}` declares as "
        f"required. A document that describes a shape the service does not "
        f"answer with is the defect this clause exists for"
    )
    undeclared = [name for name in body if name not in schema.get("properties", {})]
    assert not undeclared, (
        f"the 422 body carries {undeclared}, which `{component}` does not "
        f"declare. A client validating against the document would reject a "
        f"response the service considers correct"
    )


async def test_the_deployment_payload_is_four_groups_and_nothing_else(api) -> None:  # noqa: ANN001
    """`GET /v1/deployment` answers in four groups, and nothing sits outside them.

    **The shape is the contract now, not a convention.** The payload was flat
    until 2026-09-03 and answered four unrelated questions at once -- who is
    answering, how this instance was configured, what a caller may send, and how
    the build behaves -- with no way for a reader to tell which was which. A
    field left at the top level would be that flat payload growing back one key
    at a time, which is exactly how it happened the first time.

    **Empty groups are a failure too.** A build that publishes `accepts: {}` has
    not simplified anything; it has stopped answering one of the four questions.
    """
    payload = (await api.get("/v1/deployment")).json()

    assert set(payload) == set(DEPLOYMENT_GROUPS), (
        f"the payload's top level is {sorted(payload)}, and the contract is "
        f"exactly {sorted(DEPLOYMENT_GROUPS)}. A field outside a group is the "
        "flat payload returning"
    )
    for group in DEPLOYMENT_GROUPS:
        assert isinstance(payload[group], dict) and payload[group], (
            f"{group} is {payload[group]!r}: every group answers a question, and "
            "an empty one answers nothing"
        )


async def test_the_two_maps_that_were_split_stay_split(api) -> None:  # noqa: ANN001
    """`limits` and the MCP timers are cut along the line the groups draw.

    **These two are why grouping was worth doing.** `limits` mixed ceilings on a
    request with figures the service enforces on its own, distinguishable only
    by a key prefix; `mcp` mixed transports a caller may express with timeouts a
    server author must design around. A build that puts a `max_allowed_*` in
    `behaviour.limits`, or the timers back inside `accepts.mcp`, has undone the
    distinction while still looking grouped.
    """
    payload = (await api.get("/v1/deployment")).json()

    for name in payload["behaviour"].get("limits", {}):
        assert not name.startswith(("max_allowed_", "default_")), (
            f"behaviour.limits carries {name!r}, which bounds a REQUEST and "
            "belongs in accepts.limits"
        )
    assert "tool_call" not in payload["accepts"].get("mcp", {}), (
        "accepts.mcp carries the tool-call timers again; they are behaviour, "
        "published as behaviour.mcp_tool_call"
    )


async def test_the_run_options_schema_agrees_with_what_accepts_publishes(api) -> None:  # noqa: ANN001
    """`GET /v1/schemas/run-options` is `accepts` in another shape, not a second opinion.

    **Two published shapes of one fact drift unless something compares them.**
    The capability payload is what a client branches on; the schema is what a
    client validates against. A build whose schema still offers a field its
    payload refuses has told two different stories to two different readers, and
    each is individually plausible.

    Deliberately narrow: it checks the claims that a client acts on -- the
    refusals and the permission-mode vocabulary -- rather than re-deriving the
    whole schema here, which would just be the generator written twice.
    """
    payload = (await api.get("/v1/deployment")).json()
    accepts = payload["accepts"]

    response = await api.get("/v1/schemas/run-options")
    assert response.status_code == 200, (
        "a build publishing `accepts` must serve the schema rendering of it"
    )
    assert response.headers["content-type"].startswith("application/schema+json"), (
        f"the schema is served as {response.headers['content-type']!r}; a "
        "validator selects on the media type"
    )
    schema = response.json()

    assert schema.get("$schema", "").endswith("2020-12/schema"), (
        "the document does not declare the 2020-12 dialect it is written in"
    )
    forbidden = {clause["not"]["required"][0] for clause in schema.get("allOf", [])}

    for entry in accepts.get("unsupported_options") or []:
        field, types, values = entry["field"], entry.get("types"), entry.get("values")
        if types or values:
            # A narrowed refusal keeps the property: the field works in the
            # shapes that were not named, and removing it would refuse those too.
            assert field in schema["properties"], (
                f"{field} is refused only for {types or values}, so the schema "
                "must keep the property and narrow it"
            )
            continue
        assert field not in schema["properties"], (
            f"{field} is in unsupported_options and the schema still offers it"
        )
        assert field in forbidden, (
            f"{field} is removed from the schema but not forbidden by name, so "
            "sending it is indistinguishable from a typo"
        )

    published_modes = {mode["id"] for mode in accepts.get("permission_modes") or []}
    if published_modes and "permission_mode" in schema["properties"]:
        in_schema = {branch["const"]
                     for branch in schema["properties"]["permission_mode"].get("oneOf", [])}
        assert in_schema == published_modes, (
            f"the schema offers {sorted(in_schema)} and the payload publishes "
            f"{sorted(published_modes)}"
        )
