"""Service-level authentication: a bearer token on `/v1`, and nothing more.

**What it answers: "is the caller the party that provisioned this container?"**
Not "which user is calling" — this service has no identity model, nothing is
scoped by the token, and there is exactly one credential.

**A THIRD COPY, deliberately.** The Claude and Codex builds ship the same
contract as their own modules, and this is the third. Ninety lines of middleware
is not what makes these builds separate, and a shared one would put a per-build
security decision in a package that names no build.

## Read this before relying on it

**Authentication is the third control, not the first.** Network isolation and a
relay in front of this service remove far more risk than a token does, and both
sit outside this repository. A token on an API that should not be reachable is a
second lock on a door standing in a field.

**It does nothing about prompt injection**, which is the likeliest adversary here
and arrives through a perfectly authorised call.

**The token must be per-instance.** See `config.auth_token` for what popping it
out of the environment does and does not buy: the agent does not inherit it, and
that is not the same as the agent being unable to read it.

## Why middleware and not a dependency

A `Depends(...)` has to be remembered on every route, and the failure mode of
forgetting is an unauthenticated endpoint that looks exactly like the others.
This matches on the path prefix, so a route added tomorrow is covered by having
been added under `/v1`. A check that cannot be forgotten beats one that reads
more idiomatically — and this build added three routes after the surface was
first written, which is precisely the drift a per-route decorator loses to.
"""

from __future__ import annotations

import secrets

from agent_spec.openapi.schemas import Problem
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

#: Everything under here needs the credential. **`/healthz` does NOT**, and that
#: is load-bearing rather than an oversight: `compose.yaml`'s healthcheck curls
#: it, so authenticating it would make an authenticated container permanently
#: unhealthy — and with `restart: "no"`, stopped. It reports posture and no
#: session data.
#:
#: `/docs`, `/openapi.json` and `/redoc` stay open too. They describe a surface
#: this repository publishes in `spec/` anyway, so withholding them protects
#: nothing.
PROTECTED_PREFIX = "/v1"

_SCHEME = "Bearer"


def _unauthorized(detail: str) -> JSONResponse:
    """401 as `application/problem+json`, like every other error here.

    **401 and not 403.** 401 is "I do not know who you are"; 403 is "I know, and
    no". This service never reaches the second — there is one credential and it
    either matched or it did not.

    `WWW-Authenticate` is sent because a 401 without it is malformed, and because
    naming the scheme beats making a caller infer it from prose.
    """
    return JSONResponse(
        status_code=401,
        content=Problem(title="Authentication required", status=401,
                        detail=detail).model_dump(),
        media_type="application/problem+json",
        headers={"WWW-Authenticate": _SCHEME},
    )


def install_auth(app: FastAPI, token: str | None) -> None:
    """Require `Authorization: Bearer <token>` on `/v1` when a token is set.

    With `token` None the middleware is **not installed at all**, rather than
    installed and passing everything through: nothing then stands between a
    request and a route, so the open deployment is the same code path it has
    always been rather than an equivalent one.
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

        # CONSTANT TIME. `==` on a secret leaks its length and common prefix
        # through timing, and a token compared byte-by-byte against
        # attacker-supplied input is the textbook case. `compare_digest` costs
        # nothing; there is no reason to earn the footnote.
        if not secrets.compare_digest(presented, token):
            # **The SAME message as a missing credential.** "Wrong token" versus
            # "no token" tells a prober the header name is right and only the
            # value is off.
            return _unauthorized(
                "the presented credential was not accepted. Note that this "
                "token authenticates the CALLER to this instance only; it is "
                "not an identity and confers no scoping."
            )

        return await call_next(request)
