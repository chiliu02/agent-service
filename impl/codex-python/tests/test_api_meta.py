"""The meta routes, the boot gate and AS-21.

These are the two gaps the specification's conformance suite found in this build
on 2026-08-08 — no boot gate, and a 404 that was not a problem document. Pinned
here so they cannot come back between conformance runs, which need a container.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_spec.openapi.schemas import Deployment, Health
from fastapi.testclient import TestClient

from agent_spec.openapi.ordering import CANONICAL_PATHS
from agent_service.api import create_app
from agent_spec.openapi.examples import flat
from agent_service.config import (
    MissingCredentials,
    MissingMounts,
    Settings,
    verify_credentials,
    verify_mounts,
)

#: Both gates off. **`require_mounts=False` is not decoration**: the gate landed
#: after these tests did, and with it left at its default every one of them
#: would refuse to boot -- an in-process test has no bind mount and never will.
_OPEN = Settings(require_credentials=False, require_mounts=False)


@pytest.fixture
def client() -> TestClient:
    # `with` matters: the lifespan -- and therefore the boot gate -- only runs
    # inside the context manager. A bare TestClient would skip it silently.
    with TestClient(create_app(_OPEN)) as c:
        yield c


# --- AS-2: the boot gate ----------------------------------------------------


def test_no_credential_refuses_to_boot(monkeypatch) -> None:  # noqa: ANN001
    """**The gap the conformance suite found.** The service started without a
    credential while `require_credentials` was true, which AS-2 forbids.

    Raising from the lifespan is what makes uvicorn `sys.exit(3)` -- the same
    exit code every implementation uses, and one an orchestrator can tell from
    a crash.
    """
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(MissingCredentials):
        with TestClient(create_app(Settings(require_credentials=True))):
            pass


def test_any_published_credential_satisfies_the_gate(monkeypatch) -> None:  # noqa: ANN001
    """Driven from the published list, not a copy: AS-2 says *any one* of the
    names this build publishes satisfies the gate, so a name added to
    `CREDENTIAL_ENV_VARS` without the gate reading it fails here."""
    from agent_service.config import CREDENTIAL_ENV_VARS

    for name in CREDENTIAL_ENV_VARS:
        for other in CREDENTIAL_ENV_VARS:
            monkeypatch.delenv(other, raising=False)
        monkeypatch.setenv(name, "probe-value")
        verify_credentials(Settings(require_credentials=True))


def test_the_gate_message_names_the_app_server_auth_store(monkeypatch) -> None:  # noqa: ANN001
    """**Codex-specific and load-bearing.** A deployment authenticated through
    the app-server's own store has no variable set, and this gate cannot see it.

    Without this sentence that operator hunts for a variable they deliberately
    did not set. The Claude build's message has no equivalent because it has no
    equivalent auth route.
    """
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(MissingCredentials) as excinfo:
        verify_credentials(Settings(require_credentials=True))
    message = str(excinfo.value)
    assert "app-server" in message
    assert "AGENT_SERVICE_REQUIRE_CREDENTIALS=false" in message


def test_the_gate_and_the_login_read_the_environment_the_same_way(monkeypatch) -> None:  # noqa: ANN001
    """**A gate that accepts what the login rejects is worse than no gate**: the
    service boots, then fails every turn with a 401 that points at the key.

    Whitespace is the case that actually happens -- a key pasted into a `.env`
    file arrives with a trailing newline often enough to be worth pinning.
    """
    from agent_service.config import api_key, credentials_configured

    for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert api_key() is None
    assert credentials_configured() is False, "the gate accepted a key the login would reject"

    monkeypatch.setenv("OPENAI_API_KEY", "  sk-padded  \n")
    assert api_key() == "sk-padded", "the key was not stripped before use"
    assert credentials_configured() is True


def test_the_first_published_name_wins(monkeypatch) -> None:  # noqa: ANN001
    """Precedence is **this service's** decision, not the SDK's: the app-server
    reads neither variable, so nothing upstream defines an order to defer to.
    List order is the rule, and it is pinned so it cannot drift silently."""
    from agent_service.config import CREDENTIAL_ENV_VARS, api_key

    for name in CREDENTIAL_ENV_VARS:
        monkeypatch.setenv(name, f"key-for-{name}")
    assert api_key() == f"key-for-{CREDENTIAL_ENV_VARS[0]}"


# --- the mounts gate --------------------------------------------------------
#
# Not a numbered clause, but the specification's `test_boot_gates.py` asserts it
# against any image, and AS-5 makes this build PUBLISH `require_mounts` on
# `/v1/deployment`. Publishing a gate that does not fire is worse than not
# having one: a consumer reads `true` and provides the mount that nothing was
# ever going to check.


def test_an_unmounted_workspace_refuses_to_boot(tmp_path) -> None:  # noqa: ANN001
    """The state the gate exists for: a directory that EXISTS and is not a mount.

    `tmp_path` is exactly what a container with no `-v` has -- a real, writable
    directory on the container's own filesystem, whose contents vanish with it.
    An `exists()` check would pass here, which is why `_mounted_under` does not
    use one.
    """
    with pytest.raises(MissingMounts) as excinfo:
        verify_mounts(Settings(require_mounts=True, workspace_dir=tmp_path))

    message = str(excinfo.value)
    # The message is read by an operator with no source in front of them, and by
    # `spec/conformance/test_boot_gates.py` in the container's log.
    assert "AGENT_SERVICE_WORKSPACE_DIR" in message
    assert "AGENT_SERVICE_REQUIRE_MOUNTS=false" in message
    assert str(tmp_path) in message


def test_the_escape_hatch_lets_an_unmounted_workspace_boot(tmp_path) -> None:  # noqa: ANN001
    """The control. Without it the test above would pass against a gate that
    refused unconditionally, which is a different defect with the same symptom.
    """
    verify_mounts(Settings(require_mounts=False, workspace_dir=tmp_path))


def test_a_mount_point_satisfies_the_gate(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """The gate ACCEPTS a mounted workspace. Without this, every test above
    would pass against a gate that refused unconditionally.

    **`ismount` is patched, and there is no honest alternative on this host.**
    The one path that is a real mount everywhere is the filesystem root, and
    `_mounted_under` deliberately never tests it -- the walk stops *at* the
    anchor, so that a path merely UNDER `/` is not accepted on the strength of
    the container's own root being a mount. That exclusion is the whole point of
    the function, so borrowing `/` to prove acceptance would test the one branch
    that must not exist. A real bind mount is the container tier's job:
    `spec/conformance/test_boot_gates.py` boots the image with and without one.
    """
    import os.path

    real = tmp_path / "ws"
    real.mkdir()
    monkeypatch.setattr(
        os.path, "ismount", lambda p: Path(p) == real.resolve(), raising=True
    )
    verify_mounts(Settings(require_mounts=True, workspace_dir=real))


def test_a_subdirectory_of_a_mount_is_accepted(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """`-v /host:/data` with `AGENT_SERVICE_WORKSPACE_DIR=/data/ws` is a
    legitimate layout, which is why `_mounted_under` walks up rather than
    calling `ismount` on the path itself."""
    import os.path

    mount = tmp_path / "data"
    nested = mount / "ws"
    nested.mkdir(parents=True)
    monkeypatch.setattr(
        os.path, "ismount", lambda p: Path(p) == mount.resolve(), raising=True
    )
    verify_mounts(Settings(require_mounts=True, workspace_dir=nested))


def test_the_walk_up_stops_before_the_filesystem_root(tmp_path) -> None:  # noqa: ANN001
    """The exclusion that makes the whole check mean something.

    A container's `/` IS a mount point. If the walk tested the anchor, every
    path in every container would satisfy the gate and it would quietly do
    nothing -- passing while measuring nothing is the failure mode a boot gate
    can least afford. `tmp_path` is nested several levels below the root and
    unmounted, so a refusal here is that exclusion working.
    """
    nested = tmp_path / "ws"
    nested.mkdir()
    with pytest.raises(MissingMounts):
        verify_mounts(Settings(require_mounts=True, workspace_dir=nested))


# --- bearer auth, which this build enforces since 2026-08-08 ----------------
#
# **These replace `test_a_configured_auth_token_refuses_to_boot`**, which existed
# to pin the refusal this build used to make instead of having the feature. Its
# docstring said it was *"meant to fail the day bearer auth is implemented"*, and
# it did, on the run that implemented it. (CX-42) is the
# history.

_AUTHED = Settings(require_credentials=False, require_mounts=False, auth_token="s3cret")


@pytest.fixture
def authed_client() -> TestClient:
    with TestClient(create_app(_AUTHED)) as c:
        yield c


def test_v1_without_a_credential_is_401_as_a_problem_document(
    authed_client: TestClient,
) -> None:
    r = authed_client.get("/v1/deployment")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    # A 401 without this header is malformed, and naming the scheme beats making
    # a caller infer it.
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["status"] == 401


def test_the_right_token_is_let_through(authed_client: TestClient) -> None:
    r = authed_client.get("/v1/deployment", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_a_wrong_token_and_a_missing_one_are_indistinguishable(
    authed_client: TestClient,
) -> None:
    """"Wrong token" versus "no token" tells a prober the name is right and only
    the value is off. Both answers must be the same 401 with the same shape."""
    missing = authed_client.get("/v1/deployment")
    wrong = authed_client.get("/v1/deployment", headers={"Authorization": "Bearer nope"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["title"] == wrong.json()["title"]


def test_the_token_never_appears_in_any_response(authed_client: TestClient) -> None:
    for r in (
        authed_client.get("/v1/deployment"),
        authed_client.get("/v1/deployment", headers={"Authorization": "Bearer nope"}),
        authed_client.get("/healthz"),
    ):
        assert "s3cret" not in r.text


def test_another_scheme_is_refused_and_named(authed_client: TestClient) -> None:
    r = authed_client.get("/v1/deployment", headers={"Authorization": "Basic s3cret"})
    assert r.status_code == 401
    assert "Basic" in r.json()["detail"]


def test_healthz_needs_no_credential_and_reports_the_requirement(
    authed_client: TestClient,
) -> None:
    """**Load-bearing, not an oversight.** `compose.yaml`'s healthcheck curls
    `/healthz`, so authenticating it would make an authenticated container
    permanently unhealthy -- and with `restart: "no"`, stopped."""
    r = authed_client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["auth_required"] is True


def test_the_open_docs_stay_open(authed_client: TestClient) -> None:
    """They describe a surface published in `spec/` anyway, so withholding them
    protects nothing and costs the browsable documentation."""
    assert authed_client.get("/openapi.json").status_code == 200


def test_no_token_installs_no_middleware_and_publishes_false(
    client: TestClient,
) -> None:
    """The control, and the shipped default."""
    assert client.get("/v1/deployment").status_code == 200
    assert client.get("/healthz").json()["auth_required"] is False


def test_verify_auth_no_longer_refuses_anything() -> None:
    """The gate survives the feature it guarded -- see its docstring for why --
    and a token is now the ordinary case rather than a refusal."""
    from agent_service.config import verify_auth

    verify_auth(Settings())
    verify_auth(_OPEN)
    verify_auth(_AUTHED)


# --- AS-21: every error is a problem document -------------------------------


def test_an_unknown_path_is_a_problem_document(client: TestClient) -> None:
    """**The other gap.** A 404 is produced by the FRAMEWORK, not by this code,
    so wiring only our own exceptions left AS-21 false."""
    r = client.get("/v1/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404
    assert r.json()["title"]


def test_a_malformed_body_is_a_problem_document_and_echoes_nothing() -> None:
    """422 is also the framework's, and it needs a route that TAKES a body.

    This build has no POST routes yet, so one is added to the real app -- the
    handlers under test are already registered on it. When the turn routes
    land this keeps testing the same wiring and the added route becomes
    redundant rather than wrong.

    **The validation errors are not echoed**: they quote the offending input,
    and this service is unauthenticated by default.
    """
    app = create_app(_OPEN)

    @app.post("/probe-validation")
    async def _probe(body: dict) -> dict:  # noqa: ANN001
        return body

    with TestClient(app) as c:
        r = c.post(
            "/probe-validation",
            content=b"not-json-at-all",
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "not-json-at-all" not in str(r.json()), "the offending input was echoed"


def test_the_problem_shape_is_the_published_one(client: TestClient) -> None:
    """Validated against the shared model, so a change to the specification's
    `Problem` fails here rather than at a consumer."""
    from agent_spec.openapi.schemas import Problem

    Problem.model_validate(client.get("/v1/nope").json())


# --- the meta routes --------------------------------------------------------


def test_healthz_validates_against_the_shared_model(client: TestClient) -> None:
    Health.model_validate(client.get("/healthz").json())


def test_capabilities_validates_against_the_shared_model(client: TestClient) -> None:
    Deployment.model_validate(client.get("/v1/deployment").json())


def test_database_usable_is_null_not_false_when_unconfigured(client: TestClient) -> None:
    """"Not configured" must never read as "configured and broken" -- the
    specification distinguishes them and this build has no database yet."""
    body = client.get("/healthz").json()
    assert body["database_configured"] is False
    assert body["database_usable"] is None


def test_the_served_version_is_the_specification_version(client: TestClient) -> None:
    """`info.version` is the DOCUMENT's, never this build's. Two implementations
    satisfying one specification report the same value."""
    from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_VERSION

    assert client.get("/openapi.json").json()["info"]["version"] == DOCUMENT_VERSION
    caps = flat(client.get("/v1/deployment").json())
    assert caps["spec"]["document_version"] == DOCUMENT_VERSION
    assert caps["impl"]["version"] == IMPLEMENTATION_VERSION


# --- declared responses vs what `errors.py` can actually produce -------------
#
# **The defect these pin is written up as (CX-24).**
# `errors.py` could produce three statuses this document did not declare, and
# one of them -- 503 -- was declared by NEITHER implementation, so the
# document-to-document comparison that found the others was structurally
# incapable of finding it. These tests exist so the gap cannot reopen.
#
# The rule they encode is AS-33 (CX-44): a build declares every status its own
# error mapping can reach on that route, and **absence means unreachable**.


def _declared(doc: dict, path: str, method: str) -> set[str]:
    return set(doc["paths"][path][method]["responses"])


def test_every_status_the_error_table_maps_is_declared_by_some_route(
    client: TestClient,
) -> None:
    """The guard that would have caught 503 on its own.

    **Reads `errors.py`'s table rather than a list written here**, so adding a
    mapping forces a decision about which routes can reach it instead of
    silently producing a status no document mentions.
    """
    from agent_service.errors import _TABLE

    doc = client.get("/openapi.json").json()
    declared: set[str] = set()
    for item in doc["paths"].values():
        for method, op in item.items():
            if method in {"get", "post", "patch", "delete"}:
                declared |= set(op.get("responses", {}))

    for exc, status, _title in _TABLE:
        assert str(status) in declared, (
            f"errors.py maps {exc.__name__} to {status} and no route declares "
            f"it -- see (CX-24)"
        )


def test_the_turn_routes_declare_the_busy_and_unclassified_statuses(
    client: TestClient,
) -> None:
    """A turn reaches the model, so both are reachable there.

    503 is `ServerBusyError`/`RetryLimitExceededError` -- retries exhausted
    inside the SDK, the request itself fine. A client without that branch reads
    the one retryable condition as a failed turn.
    """
    doc = client.get("/openapi.json").json()
    for path in ("/v1/sessions/{sid}/messages", "/v1/query"):
        assert {"500", "502", "503"} <= _declared(doc, path, "post"), path


def test_interrupt_declares_a_wedged_runtime_but_not_a_busy_upstream(
    client: TestClient,
) -> None:
    """`TurnHandle.interrupt()` is a control message over the transport, so a
    dead runtime is reachable (502, and 500 for anything unclassified) -- but an
    interrupt is never a model call, so `ServerBusyError` has no path to it."""
    declared = _declared(client.get("/openapi.json").json(), "/v1/sessions/{sid}/interrupt", "post")
    assert {"404", "500", "502"} <= declared
    assert "503" not in declared


def test_the_lookup_routes_are_lean_because_they_reach_nothing(
    client: TestClient,
) -> None:
    """**The other half of AS-33, and the reason it is not "declare everything".**

    On this build `GET` and `PATCH /v1/sessions/{sid}` issue nothing to the
    agent -- Codex exposes no context-window control request and takes model and
    approval mode per turn rather than as connection state -- so the 500 and 502
    the Claude build declares there are genuinely unreachable here. That is a
    legitimate difference and not a missing declaration.

    Pinned so that adding a control request to either route fails this test
    rather than silently producing an undeclared status.
    """
    doc = client.get("/openapi.json").json()
    for method in ("get", "patch"):
        declared = _declared(doc, "/v1/sessions/{sid}", method)
        assert "502" not in declared, method
        assert "500" not in declared, method


def test_the_stream_routes_declare_only_what_can_precede_the_commit(
    client: TestClient,
) -> None:
    """Once a 200 is committed a failure is an in-band `event: error`, never a
    status. So the session stream declares its pre-flight 404/409 and nothing
    else, and the one-shot stream -- which commits before the session exists --
    declares no error status at all."""
    doc = client.get("/openapi.json").json()
    session_stream = _declared(doc, "/v1/sessions/{sid}/messages/stream", "post")
    assert {"404", "409"} <= session_stream
    assert not session_stream & {"500", "502", "503"}
    one_shot = _declared(doc, "/v1/query/stream", "post")
    assert not one_shot & {"400", "500", "502", "503"}


# --- token_usage, against the payload a real turn actually produced ----------
#
# **This field shipped with no test at all on either build**, which is how it
# reached a release reading camelCase keys off the wrong nesting level and
# publishing five nulls on every turn -- (CX-13).
#
# The fixture below is VERBATIM from a measured turn (gpt-5-mini, 2026-08-09),
# not a shape written from the docstring. That distinction is the whole point:
# the old code was consistent with its own documentation and with nothing else.

#: Exactly what `outcome.usage` held after a real turn. Do not tidy it -- the
#: nesting and the spelling are the assertion.
_MEASURED_USAGE = {
    "last": {
        "cached_input_tokens": 15488,
        "input_tokens": 15810,
        "output_tokens": 320,
        "reasoning_output_tokens": 256,
        "total_tokens": 16130,
    },
    "model_context_window": 258400,
    "total": {
        "cached_input_tokens": 15488,
        "input_tokens": 29857,
        "output_tokens": 1989,
        "reasoning_output_tokens": 1856,
        "total_tokens": 31846,
    },
}


def test_the_named_counts_are_read_from_a_real_payload() -> None:
    """Four of five populated, and `cache_write_tokens` null for a real reason.

    Codex has no cache-WRITE counter, so that one `null` means *this build
    cannot report it* -- which is exactly what the other four were saying
    untruthfully until this was fixed.
    """
    from agent_service.api import _token_usage

    usage = _token_usage(_MEASURED_USAGE)
    assert usage.input_tokens == 15810
    assert usage.output_tokens == 320
    assert usage.cache_read_tokens == 15488
    assert usage.reasoning_output_tokens == 256
    assert usage.cache_write_tokens is None


def test_the_counts_come_from_last_and_not_from_total() -> None:
    """`TokenUsage` is scoped to THIS run. `total` is the thread's running sum,
    so reading it would inflate every turn after the first by the whole
    conversation -- and the two are the same shape, so nothing else would
    notice."""
    from agent_service.api import _token_usage

    assert _token_usage(_MEASURED_USAGE).input_tokens == 15810  # last, not 29857


def test_a_usage_shape_this_build_does_not_recognise_is_all_null() -> None:
    """Null when the counts genuinely are not there -- an absent `usage`, or a
    shape without `last`. **No fallback to the top level**: a silent second
    chance is what let the wrong keys look like an absent payload for a whole
    release."""
    from agent_service.api import _token_usage

    for payload in (None, {}, {"input_tokens": 5}, {"last": None}):
        usage = _token_usage(payload)
        assert usage.input_tokens is None, payload
        assert usage.output_tokens is None, payload


def test_the_sandbox_capability_matches_what_was_measured(client: TestClient) -> None:
    """**Measured, not read off a default** -- (CX-03)
    egress section.

    `read_only` and `workspace_write` both block the agent's shell from opening
    a socket, and the control -- `curl` from the container, outside the sandbox
    -- returned `HTTP:200`, which is what makes those two rows mean anything.
    The schema's own default said the same thing, and a default in a schema is a
    claim about a field rather than a measurement of a container.

    `sandbox_workspace_write.network_access` would switch it on. This build
    leaves it alone, so `false` is the honest answer, and this test keeps the
    published value and the configuration in step.
    """
    sandbox = flat(client.get("/v1/deployment").json())["sandbox"]

    assert sandbox["network_access"] is False
    assert sandbox["confines_writes_to_workspace"] is True


def test_session_create_declares_the_capacity_503(client: TestClient) -> None:
    """**AS-33, and this one was found by measuring rather than by reading.**

    `max_sessions` is a number this service enforces; the container's
    `pids_limit` is the thing underneath it, and the two are configured
    independently. Measured 2026-08-09: ~30 pids per session, so `pids_limit:
    512` carries about **16** sessions -- and a deployment that raises
    `max_sessions` past that met `500 "Unhandled error" / BlockingIOError`, the
    unclassified case `errors.py` calls the sign of a gap in its own table.

    503 rather than 429: a 429 says the caller asked for too much, which is the
    `max_sessions` story. This says the deployment is out of room, and closing a
    session clears it.
    """
    responses = client.get("/openapi.json").json()["paths"]["/v1/sessions"]["post"][
        "responses"
    ]

    assert "503" in responses, (
        "AS-33: session create can exhaust the container's pid limit and answer "
        "503, and a status a client cannot see in the document is one it has no "
        "branch for"
    )


def test_the_documents_paths_are_in_canonical_order() -> None:
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
    served = list(create_app(_OPEN).openapi()["paths"])
    assert served == list(CANONICAL_PATHS), (
        "the served document's path order is not the canonical one; "
        f"got {served}"
    )


def test_the_published_example_is_what_a_live_instance_actually_answers() -> None:
    """**The document shows VALUES, not just a shape** -- and they must be true.

    An OpenAPI document describes the shape of `/v1/deployment` and says
    nothing about what this build answers, so a consumer holding all three
    builds' documents could not see how the builds differ without starting three
    containers. The example closes that; this test is what keeps it honest,
    because an example nothing checks is a comment.

    Deployment-dependent fields are excluded: the example is built from
    DEFAULTS, since AS-24 requires the service to serve exactly its published
    document and a live port or cap in the example would break that everywhere.
    """
    from agent_spec.openapi.examples import DEPLOYMENT_DEPENDENT, placeholdered

    with TestClient(create_app(_OPEN)) as client:
        document = client.app.openapi()
        live_payload = client.get("/v1/deployment").json()
        live = flat(live_payload)
    published = flat(document["paths"]["/v1/deployment"]["get"]["responses"]["200"]
                      ["content"]["application/json"]["example"])

    # Versions that move on the implementation stream are published as a
    # placeholder, so compare against a live payload with the same rule
    # applied rather than excluding whole objects: `sdk.name` stays checked,
    # and the rule is stated once, in the module that publishes it.
    expected = flat(placeholdered(live_payload))

    assert set(published) == set(live), "the example and the payload differ in SHAPE"
    differing = {
        field for field in live
        if field not in DEPLOYMENT_DEPENDENT and published[field] != expected[field]
    }
    assert not differing, (
        f"the published example no longer matches what this build answers: {differing}"
    )
    assert DEPLOYMENT_DEPENDENT <= set(live), "DEPLOYMENT_DEPENDENT names a field that is gone"


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
