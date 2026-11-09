"""Service-level authentication (0.11.0) — Q6.

**What is under test is narrow on purpose.** This answers "is the caller the
party that provisioned this container" and nothing else: no per-request
identity, no scoping, no tenancy. Agent Studio asked for exactly that and no
more — it resolves the owner of a request from the Agent, so a caller claim
would be a second and weaker source of truth (CP-133).

The properties worth pinning, in the order they would break something:

1. **`/healthz` is never protected.** The container healthcheck is
   `curl -fsS .../healthz`; protecting it makes an authenticated container
   permanently unhealthy and, with `restart: "no"`, stopped.
2. **Off by default changes nothing.** The documented single-operator
   deployment must be untouched, or turning this on for one caller breaks
   every other.
3. **A wrong token and a missing token answer identically**, so a prober
   cannot learn that the header name was right.
4. **The comparison is constant-time**, because it is a secret compared
   against attacker-supplied input.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.config import Settings, verify_auth
from agent_spec.openapi.examples import flat

TOKEN = "per-instance-token-6f2a"


def _client(**kwargs) -> TestClient:  # noqa: ANN003
    settings = Settings(
        require_credentials=False, require_mounts=False, **kwargs
    )
    return TestClient(create_app(settings))


# --- off by default ---------------------------------------------------------


def test_no_token_configured_leaves_every_route_open() -> None:
    """The shipped default, and it must be byte-for-byte the old behaviour.

    `install_auth` does not install the middleware at all when no token is set,
    rather than installing one that waves everything through — so this is the
    same code path the service has always had.
    """
    with _client() as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/deployment").status_code == 200
        assert client.get("/healthz").json()["auth_required"] is False
        assert flat(client.get("/v1/deployment").json())["auth_required"] is False


# --- what is protected, and what must never be ------------------------------


def test_healthz_is_never_protected() -> None:
    """Load-bearing, not a convenience.

    `compose.yaml`'s healthcheck is `curl -fsS http://127.0.0.1:8000/healthz`
    with no credential. Protect this route and an authenticated container is
    permanently unhealthy — and `restart: "no"` means it stays stopped.
    """
    with _client(auth_token=TOKEN) as client:
        response = client.get("/healthz")

        assert response.status_code == 200
        # And it still answers the question a caller needs before it can call
        # anything else.
        assert response.json()["auth_required"] is True


def test_the_documentation_routes_stay_open() -> None:
    """They describe a surface published in `schema/` anyway, so withholding
    them protects nothing and costs the browsable docs the README points at."""
    with _client(auth_token=TOKEN) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200


def test_v1_is_protected(  # noqa: PT006
) -> None:
    with _client(auth_token=TOKEN) as client:
        assert client.get("/v1/deployment").status_code == 401
        assert client.post("/v1/sessions", json={}).status_code == 401


def test_a_valid_credential_passes() -> None:
    with _client(auth_token=TOKEN) as client:
        response = client.get(
            "/v1/deployment", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert response.status_code == 200
        assert flat(response.json())["auth_required"] is True


# --- how it refuses ---------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        None,
        "Bearer wrong-token",
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "",
    ],
    ids=["missing", "wrong-token", "wrong-scheme", "no-value", "empty"],
)
def test_every_refusal_is_a_401_problem_naming_the_scheme(header: str | None) -> None:
    """401, not 403: this service never knows *who* is calling, so it can only
    ever say "I do not know you". And `WWW-Authenticate` is required on a 401 —
    without it the response is malformed, and a caller has to guess the scheme
    from prose."""
    headers = {} if header is None else {"Authorization": header}
    with _client(auth_token=TOKEN) as client:
        response = client.get("/v1/deployment", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 401


def test_a_wrong_token_and_a_missing_one_are_indistinguishable() -> None:
    """A prober must not learn that the header name was right and only the
    value was wrong. Same status, same scheme, same shape."""
    with _client(auth_token=TOKEN) as client:
        missing = client.get("/v1/deployment")
        wrong = client.get(
            "/v1/deployment", headers={"Authorization": "Bearer not-the-token"}
        )

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"] == wrong.headers["www-authenticate"]
    assert missing.json()["title"] == wrong.json()["title"]


def test_the_token_is_never_echoed_in_a_refusal() -> None:
    """A response that quoted the presented value back would put a secret into
    every log that records response bodies."""
    with _client(auth_token=TOKEN) as client:
        body = client.get(
            "/v1/deployment", headers={"Authorization": f"Bearer {TOKEN}x"}
        ).text

    assert TOKEN not in body


def test_the_comparison_is_constant_time() -> None:
    """`==` on a secret leaks its length and common prefix through timing, and
    this one is compared against attacker-supplied input. Asserted by reading
    the source rather than by timing, which would be flaky and would prove less:
    what matters is that the right primitive is used."""
    import inspect

    from agent_service import auth

    source = inspect.getsource(auth)
    assert "secrets.compare_digest" in source
    assert "presented == token" not in source


# --- the boot gate and the setting -----------------------------------------


def test_require_auth_without_a_token_refuses_to_boot() -> None:
    """The third gate, symmetric with `require_credentials` and
    `require_mounts`: for an operator who needs "this container is
    authenticated" to be a fact rather than a hope."""
    with pytest.raises(RuntimeError) as excinfo:
        verify_auth(Settings(require_auth=True, auth_token=None))

    assert "AGENT_SERVICE_AUTH_TOKEN" in str(excinfo.value)


def test_require_auth_with_a_token_is_satisfied() -> None:
    verify_auth(Settings(require_auth=True, auth_token=TOKEN))  # must not raise


def test_neither_gate_fires_by_default() -> None:
    """Both default off, so an existing deployment is unaffected."""
    settings = Settings()

    assert settings.auth_token is None
    assert settings.require_auth is False
    verify_auth(settings)  # must not raise


def test_the_token_is_not_in_the_settings_repr() -> None:
    """`repr(Settings())` reaches logs and tracebacks."""
    assert TOKEN not in repr(Settings(auth_token=TOKEN))
