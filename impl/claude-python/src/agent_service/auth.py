"""Service-level authentication (0.11.0) — Q6.

**What this answers: "is the caller the party that provisioned this
container?"** It does not answer "which user is calling", and deliberately: the
one consumer resolves the owner of a request from the Agent it belongs to, so a
per-request caller claim would be a second and weaker source of truth for
something already decided (CP-133).

## Read this before relying on it

**Authentication is the third control, not the first.** Network isolation and a
relay in front of this service remove more risk than a token does, and both sit
outside this repository. A token on an API that should not be reachable is a
second lock on a door standing in a field (CP-133).

**The token is readable by the agent this service runs.** Measured: the CLI
subprocess runs as the agent's own uid, `/proc` carries no `hidepid`, and the
environment is inherited (CP-075; `config.py` records the same
for `ANTHROPIC_API_KEY`). So this token must be **per-instance** and must grant
access to **nothing but this instance**. A token shared across a fleet is
readable by any user who can take one turn, and then buys the fleet.

**It does nothing about prompt injection**, which is the likeliest adversary and
arrives through a perfectly authorised call.

## Why middleware and not a dependency

A `Depends(...)` has to be remembered on every route, and the failure mode of
forgetting is an unauthenticated endpoint that looks exactly like the others.
This matches on the path prefix instead, so a route added tomorrow is covered by
having been added under `/v1`. The check that cannot be forgotten is worth more
than the one that reads more idiomatically.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_spec.openapi.schemas import Problem

#: Everything under here needs the credential. `/healthz` does NOT, and that is
#: load-bearing rather than an oversight: `compose.yaml`'s healthcheck is
#: `curl -fsS http://127.0.0.1:8000/healthz`, so authenticating it would make an
#: authenticated container permanently unhealthy and, with `restart: "no"`,
#: stopped. It reports posture and no session data.
#:
#: `/docs`, `/openapi.json` and `/redoc` are also open. They describe a surface
#: that is published in `schema/` anyway, so withholding them protects nothing
#: and costs the browsable documentation the README sends people to.
PROTECTED_PREFIX = "/v1"

_SCHEME = "Bearer"


def _unauthorized(detail: str) -> JSONResponse:
    """401 as `application/problem+json`, like every other error here.

    **401 and not 403.** The distinction is the one HTTP actually makes: 401 is
    "I do not know who you are", 403 is "I know, and no". This service never
    reaches the second -- there is one credential and it either matched or it
    did not.

    `WWW-Authenticate` is sent because 401 without it is malformed, and because
    it names the scheme rather than making a caller guess it from prose.
    """
    problem = Problem(
        title="Authentication required",
        status=401,
        detail=detail,
    )
    return JSONResponse(
        status_code=401,
        content=problem.model_dump(),
        media_type="application/problem+json",
        headers={"WWW-Authenticate": _SCHEME},
    )


def install_auth(app: FastAPI, token: str | None) -> None:
    """Require `Authorization: Bearer <token>` on `/v1` when a token is set.

    With `token` None the middleware is **not installed at all**, rather than
    installed and short-circuiting. Nothing then stands between a request and a
    route, which is the same code path the service has always had -- so the
    documented single-operator deployment is byte-for-byte unchanged rather than
    changed-but-equivalent.
    """
    if token is None:
        return

    @app.middleware("http")
    async def _require_bearer(request: Request, call_next):  # noqa: ANN001, ANN202
        if not request.url.path.startswith(PROTECTED_PREFIX):
            return await call_next(request)

        header = request.headers.get("authorization")
        if not header:
            return _unauthorized(
                "this deployment requires a credential: send "
                "`Authorization: Bearer <token>`. GET /healthz reports whether "
                "authentication is required and needs none itself."
            )

        scheme, _, presented = header.partition(" ")
        if scheme.lower() != _SCHEME.lower() or not presented:
            return _unauthorized(
                f"unsupported authorization scheme {scheme!r}; this service "
                f"accepts {_SCHEME} only."
            )

        # CONSTANT TIME. `==` on secrets leaks their length and their common
        # prefix through timing, and a token compared byte-by-byte against
        # attacker-supplied input is the textbook case. `compare_digest` is
        # cheap; there is no reason to earn the footnote.
        if not secrets.compare_digest(presented, token):
            # The SAME message as a missing credential, and no hint about which
            # part was wrong. "Wrong token" versus "no token" tells a prober
            # that the name is right and only the value is missing.
            return _unauthorized(
                "the presented credential was not accepted. Note that this "
                "token authenticates the CALLER to this instance only; it is "
                "not an identity and confers no scoping."
            )

        return await call_next(request)
