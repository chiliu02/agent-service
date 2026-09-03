"""Service-level authentication — the same contract the Claude build ships.

**0.11.0's bearer auth, on this build.** `AGENT_SERVICE_AUTH_TOKEN` sets it;
`/v1` requires `Authorization: Bearer <token>`; `/healthz` does not. Until today
this build read the variable, published `auth_required` from it and **enforced
nothing**, so `config.verify_auth` refused to boot rather than report a
protection that did not exist (CX-42). It exists now, and
that refusal is gone.

**This is deliberately a second copy rather than a shared import** (CX-45), and
it is the third control rather than the first (CX-42). It does nothing about
prompt injection, which arrives through a perfectly authorised call.
"""

from __future__ import annotations

import secrets

from agent_spec.openapi.schemas import Problem
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

#: Everything under here needs the credential. **`/healthz` does NOT**, and that
#: is load-bearing rather than an oversight: `compose.yaml`'s healthcheck curls
#: it, so authenticating it would make an authenticated container permanently
#: unhealthy. It reports posture and no session data.
#:
#: `/docs`, `/openapi.json` and `/redoc` stay open too -- they describe a surface
#: that is published anyway, so withholding them protects nothing.
PROTECTED_PREFIX = "/v1"

_SCHEME = "Bearer"


def _unauthorized(detail: str) -> JSONResponse:
    """401 as `application/problem+json`, like every other error here (AS-21).

    **401 and not 403.** 401 is "I do not know who you are"; 403 is "I know, and
    no". This service never reaches the second -- there is one credential and it
    either matched or it did not.

    `WWW-Authenticate` is sent because a 401 without it is malformed, and because
    naming the scheme beats making a caller infer it from prose.
    """
    return JSONResponse(
        status_code=401,
        content=Problem(title="Authentication required", status=401, detail=detail).model_dump(),
        media_type="application/problem+json",
        headers={"WWW-Authenticate": _SCHEME},
    )


def install_auth(app: FastAPI, token: str | None) -> None:
    """Require `Authorization: Bearer <token>` on `/v1` when a token is set.

    With `token` None the middleware is **not installed at all**, rather than
    installed and passing everything through: nothing then stands between a
    request and a route, so the no-credential deployment is the same code path it
    has always been rather than an equivalent one.
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
            # The SAME message as a missing credential. "Wrong token" versus "no
            # token" tells a prober the name is right and only the value is off.
            return _unauthorized(
                "the presented credential was not accepted. Note that this "
                "token authenticates the CALLER to this instance only; it is "
                "not an identity and confers no scoping."
            )

        return await call_next(request)
