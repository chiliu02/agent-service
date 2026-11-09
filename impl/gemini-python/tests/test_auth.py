"""The bearer token on `/v1`: what it protects, and what it deliberately does not.

**Free: no agent, no credential, no container.** Every assertion here is about a
request that never reaches a route.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.spec import specification
from agent_spec.openapi.examples import flat

TOKEN = "a-per-instance-token"


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
def guarded(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path, auth_token=TOKEN))) as running:
        yield running


@pytest.fixture
def open_service(tmp_path: Path) -> TestClient:
    with TestClient(create_app(_settings(tmp_path))) as running:
        yield running


# --- what the token protects ----------------------------------------------

def test_v1_without_a_credential_is_401(guarded: TestClient) -> None:
    """RFC 7807 like every other error, and `WWW-Authenticate` because a 401
    without it is malformed."""
    response = guarded.get("/v1/deployment")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_right_token_gets_through(guarded: TestClient) -> None:
    response = guarded.get("/v1/deployment",
                           headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_a_wrong_token_is_indistinguishable_from_no_token(
    guarded: TestClient,
) -> None:
    """**The same message deliberately.**

    "Wrong token" versus "no token" tells a prober the header name is right and
    only the value is off, which is half of what they came for.
    """
    missing = guarded.get("/v1/deployment")
    wrong = guarded.get("/v1/deployment",
                        headers={"Authorization": "Bearer not-the-token"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["title"] == missing.json()["title"]


def test_another_scheme_is_refused(guarded: TestClient) -> None:
    """One scheme, named in the refusal rather than left to be inferred."""
    response = guarded.get("/v1/deployment",
                           headers={"Authorization": "Basic abcdef"})
    assert response.status_code == 401
    assert "Bearer" in response.json()["detail"]


def test_every_v1_route_is_covered_by_the_prefix(guarded: TestClient) -> None:
    """**The reason it is middleware and not a dependency.**

    A `Depends(...)` has to be remembered on every route, and a forgotten one is
    an unauthenticated endpoint that looks exactly like the others. This build
    added three routes after its surface was first written, which is precisely
    the drift a per-route decorator loses to -- so the assertion is over the
    served document rather than over a list kept by hand.
    """
    document = guarded.app.openapi()  # type: ignore[attr-defined]
    checked = 0
    for path, operations in document["paths"].items():
        if not path.startswith("/v1"):
            continue
        # A concrete id: the guard must answer before any route resolves it, so
        # a 404 here would mean the request got through.
        url = path.replace("{sid}", "no-such").replace("{run_id}", "no-such")
        for method in operations:
            response = guarded.request(method.upper(), url, json={})
            assert response.status_code == 401, f"{method.upper()} {url} was not guarded"
            checked += 1
    # 13 of this build's 14 operations. The fourteenth is `/healthz`, which is
    # outside the prefix on purpose and has its own test below.
    # 14 since 2026-09-03: `GET /v1/schemas/run-options` joined the surface.
    # **The number is asserted rather than derived** so that a route added
    # without a thought about auth fails here rather than shipping open.
    assert checked == 14, f"{checked} operations were checked, expected 14"


# --- what it deliberately does not protect --------------------------------

def test_healthz_never_requires_it(guarded: TestClient) -> None:
    """**Load-bearing, not an oversight.** `compose.yaml`'s healthcheck curls
    this route, so authenticating it would make an authenticated container
    permanently unhealthy -- and with `restart: "no"`, stopped."""
    response = guarded.get("/healthz")
    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_the_document_stays_open(guarded: TestClient) -> None:
    """It describes a surface this repository publishes in `spec/` anyway, so
    withholding it protects nothing."""
    assert guarded.get("/openapi.json").status_code == 200


def test_with_no_token_nothing_is_installed(open_service: TestClient) -> None:
    """The open deployment is the SAME code path, not an equivalent one.

    With no token the middleware is never added, so nothing stands between a
    request and a route.
    """
    assert open_service.get("/v1/deployment").status_code == 200
    assert open_service.get("/healthz").json()["auth_required"] is False


# --- what is published about it -------------------------------------------

def test_auth_required_is_read_from_the_setting_not_hardcoded(
    tmp_path: Path,
) -> None:
    """Publishing `false` from a service that checks, or `true` from one that
    does not, is the defect `auth_enforced` exists to make visible."""
    with TestClient(create_app(_settings(tmp_path, auth_token=TOKEN))) as client:
        caps = flat(client.get("/v1/deployment",
                               headers={"Authorization": f"Bearer {TOKEN}"}).json())
    assert caps["auth_required"] is True

    with TestClient(create_app(_settings(tmp_path))) as client:
        assert flat(client.get("/v1/deployment").json())["auth_required"] is False


def test_the_preboot_specification_claims_enforcement() -> None:
    """`auth_enforced` means **this binary checks the header**, which is a
    different question from whether a token is configured on some instance -- and
    a caller provisioning a container has no service to ask.

    It was `false` while this build had no `auth.py`, which was the honest answer
    then and is the reason the field exists.
    """
    assert specification()["auth_enforced"] is True


def test_the_token_is_popped_so_the_agent_does_not_inherit_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GP-51. **The agent is handed `{**os.environ}`**, so anything left there
    goes to a process that runs tools.

    What this buys is precise and worth not overstating: a child does not
    INHERIT the token. It does not put the token beyond the agent's reach --
    measured, the agent runs as the same uid and `/proc/<pid>/environ` still
    carries the original value.
    """
    monkeypatch.setenv("AGENT_SERVICE_AUTH_TOKEN", "s3cret")
    settings = Settings.from_env()
    assert settings.auth_token == "s3cret"
    assert "AGENT_SERVICE_AUTH_TOKEN" not in os.environ, (
        "the token stayed in the environment the agent subprocess inherits"
    )
