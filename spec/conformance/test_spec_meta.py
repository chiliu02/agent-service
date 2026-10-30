"""Conformance: the discovery surface. AS-1 … AS-5, AS-21, AS-22, AS-24.

Free -- no session, no turn, no tokens.
"""

from __future__ import annotations

from typing import Any
from .predicates import flat


async def test_healthz_answers(api) -> None:  # noqa: ANN001
    r = await api.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["credentials_configured"], bool)
    assert body["workspace_dir"]


async def test_healthz_reports_the_database_without_ever_failing_on_it(api) -> None:  # noqa: ANN001
    """`null` means "no database configured" and nothing else.

    Both fields are required, so a client never has to tell absence from
    not-configured. And `status` stays `ok` even when the database is unusable:
    persistence is optional, the container healthcheck reads the status code,
    and a broken optional subsystem must not restart a service whose agent side
    works.
    """
    body = (await api.get("/healthz")).json()

    assert "database_configured" in body, "the field is required, not optional"
    assert "database_usable" in body, "the field is required, not optional"
    assert isinstance(body["database_configured"], bool)

    if body["database_configured"]:
        assert isinstance(body["database_usable"], bool)
    else:
        assert body["database_usable"] is None, (
            "null is reserved for 'no database configured'"
        )

    # Whatever the database is doing, this route answered 200 and said ok.
    assert body["status"] == "ok"


async def test_as24_the_running_service_matches_its_published_spec(
    api, published_spec: dict[str, Any]
) -> None:  # noqa: ANN001
    """The clause that makes every other published guarantee checkable.

    It is also the hinge the document tier hangs on: `test_spec_document.py`
    proves the published document satisfies AS-1/5/7/8/11/13/17/17a/23 with no
    service running, and this proves the service serves that exact document —
    so those clauses hold for the service without a second set of live checks.
    That is why the declaration-only assertions were removed from this module
    rather than duplicated here.
    """
    served = (await api.get("/openapi.json")).json()
    assert served == published_spec


async def test_as1_as3_capabilities_publishes_two_credential_lists(api) -> None:  # noqa: ANN001
    """AS-1 and AS-3, asserted as the CLAUSES say them.

    **This test used to hardcode `ANTHROPIC_API_KEY` and `CLAUDE_CODE_USE_*`,
    and that was a defect in this suite.** AS-1 requires two separate arrays;
    it says nothing about their contents, and this suite belongs to the
    specification rather than to any implementation. The hardcoded version
    failed the first non-Claude build it ever met -- which is how it was found,
    on 2026-08-08, and is the whole reason a second implementation is worth
    having before the specification is called settled.

    **`provider_selectors` may legitimately be EMPTY.** A build whose SDK has no
    cloud-provider selectors -- Codex has none measured -- publishes `[]`, and an
    empty list is a truthful answer to "which variables select a provider". Only
    `credential_sources` must be non-empty: a build that accepts no credential
    at all could not authenticate.
    """
    caps = flat((await api.get("/v1/deployment")).json())

    assert isinstance(caps["credential_sources"], list)
    assert isinstance(caps["provider_selectors"], list)
    assert caps["credential_sources"], (
        "AS-1: credential_sources is empty, so no credential could ever satisfy "
        "the boot gate"
    )
    assert all(isinstance(n, str) and n for n in caps["credential_sources"])
    assert all(isinstance(n, str) and n for n in caps["provider_selectors"])

    # AS-3: the two sets are disjoint, so a selector can never be read as a
    # credential -- the failure the split exists to prevent. This is the half
    # that is genuinely implementation-independent, and it always was.
    assert set(caps["credential_sources"]).isdisjoint(caps["provider_selectors"])


async def test_as5_capabilities_publishes_the_cap_and_the_boot_gates(api) -> None:  # noqa: ANN001
    caps = flat((await api.get("/v1/deployment")).json())
    assert isinstance(caps["max_sessions"], int) and caps["max_sessions"] >= 1
    assert isinstance(caps["require_credentials"], bool)
    assert isinstance(caps["require_mounts"], bool)


async def test_as2_a_running_service_proves_its_own_boot_gate_passed(api) -> None:  # noqa: ANN001
    """A service that is answering has, by definition, satisfied its gate.

    Weak on its own, and worth stating: it pins the *shape* of the claim -- if
    `require_credentials` is true then `credentials_configured` cannot be false
    on a service that booted, because the gate would have exited 3 instead.
    """
    caps = flat((await api.get("/v1/deployment")).json())
    health = (await api.get("/healthz")).json()
    if caps["require_credentials"]:
        assert health["credentials_configured"] is True


async def test_as22_the_advertised_version_is_a_real_version(api) -> None:  # noqa: ANN001
    served = (await api.get("/openapi.json")).json()
    version = served["info"]["version"]
    assert version.count(".") == 2, version


async def test_as21_an_error_is_a_problem_document(api) -> None:  # noqa: ANN001
    """Over a real server, not a test transport: content-type and shape."""
    r = await api.get("/v1/sessions/definitely-not-a-session")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404
    assert body["title"]
    # A sentence, not a Python repr leaking through the wire.
    assert "Traceback" not in (body.get("detail") or "")


async def test_as32_permission_modes_are_declared_by_the_build(api) -> None:  # noqa: ANN001
    """AS-32, applied to `permission_modes` (0.19.0).

    **Shape only, and deliberately.** The specification cannot assert WHICH
    modes a build has -- that is the whole point of the change: the list was a
    closed union of one SDK's enum, which every implementation had to accept
    whether or not it could honour it. What every build must do is DECLARE, so
    that a caller reads the vocabulary instead of assuming one.

    The same trade `capabilities.sandbox` already makes: every build must
    answer, and what the answer is belongs to the build.
    """
    modes = flat((await api.get("/v1/deployment")).json())["permission_modes"]
    assert isinstance(modes, list) and modes, "a build must declare at least one mode"
    for mode in modes:
        assert {"id", "name", "description"} <= set(mode), mode
        # An id a client branches on, and prose it must not.
        assert isinstance(mode["id"], str) and mode["id"].strip(), mode
        assert isinstance(mode["name"], str) and mode["name"].strip(), mode
        assert isinstance(mode["description"], str) and mode["description"].strip(), mode
    ids = [mode["id"] for mode in modes]
    assert len(ids) == len(set(ids)), f"duplicate mode ids: {ids}"


async def test_an_undeclared_permission_mode_is_refused(api) -> None:  # noqa: ANN001
    """The other half of the clause, and the half that costs something.

    Declaring a list means nothing if a build accepts an id outside it: the
    field stopped being validated by the shared model in 0.19.0, so a build
    that does not refuse hands an unknown mode to its SDK. **Free -- the refusal
    happens before any session is opened.**
    """
    response = await api.post(
        "/v1/sessions", json={"options": {"permission_mode": "definitely-not-a-mode"}}
    )
    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
