"""Configuration, and the constants the pre-boot specification publishes.

**Stdlib only, deliberately.** `agent_service.spec` imports this and has to run
in an image whose service cannot start, so nothing here may reach for a web
stack, a settings library or the agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- credentials, as the agent itself names them ----------------------------
#
# **Not invented here.** A keyless run of the agent refuses and names its own
# accepted variables, and these are that list (GP-07). One real credential and
# two provider selectors, which is the split `credential_sources` /
# `provider_selectors` exists for -- a selector satisfies nothing by itself.

CREDENTIAL_ENV_VARS: list[str] = [
    "GEMINI_API_KEY",
]

PROVIDER_SELECTOR_ENV_VARS: list[str] = [
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_GENAI_USE_GCA",
]

#: **A fourth auth channel no boot gate can see** (GP-07). The agent also reads
#: an auth method from `<home>/.gemini/settings.json`, so a mounted home
#: carrying an earlier login is authenticated with no variable set. Such a
#: deployment starts with `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, and the
#: refusal message says so rather than leaving it to be discovered.
CREDENTIAL_GATE_BLIND_SPOT = (
    "An auth method configured in <home>/.gemini/settings.json satisfies the "
    "agent but is invisible to this gate. If that is your deployment, start "
    "with AGENT_SERVICE_REQUIRE_CREDENTIALS=false."
)

# --- the agent's own environment --------------------------------------------

#: **This, and NOT `--skip-trust`** (GP-08). The two are offered by the agent as
#: alternatives and they are not: under the flag the agent silently gets no MCP
#: servers at all, with nothing on stderr and no symptom beyond the model saying
#: it lacks a tool. An untrusted folder otherwise refuses the whole run, exit 55.
TRUST_ENV_VAR = "GEMINI_CLI_TRUST_WORKSPACE"

#: What every agent invocation this service makes must carry.
AGENT_ENV_OVERRIDES: dict[str, str] = {TRUST_ENV_VAR: "true"}

#: **A wall clock is mandatory on this target, not a refinement** (GP-02,
#: GP-18). Turns can fail to terminate, and ACP registers no `session/cancel`,
#: so the only way to end one is to kill the subprocess. 600 s matches the other
#: builds' per-turn default; what differs here is that it is load-bearing.
DEFAULT_TURN_TIMEOUT_S = 600

# --- the listen specification, published in the document --------------------
#
# AS-28: all IPv4 interfaces, never loopback -- a consumer reaches this across a
# container boundary, and a service bound to 127.0.0.1 inside a container is
# reachable from nothing. The host publication is where an address is narrowed.

LISTEN_ADDRESS = "0.0.0.0"  # noqa: S104 - see above
LISTEN_PORT = 8000
#: The numeric uid and gid the container runs as, published as
#: `PrebootSpec.runs_as`. **Numbers, because a host directory needs numbers**: a
#: consumer bind-mounting a directory it composes must chown it before the
#: container exists, and `Config.User` on the image answers `agent` -- a name,
#: which resolves to a number only by running the container.
#:
#: **A hand-written copy of the Dockerfile's `usermod` of the base image's
#: `node` user**, which already owns 1000 -- `useradd --uid 1000` fails with
#: exit 4 there. It moves in the same commit as the Dockerfile or not at all, like the document
#: label beside it, and it moves in the same commit or not at all. The
#: conformance suite reads it out of a running container and compares.
RUNS_AS_UID = 1000
RUNS_AS_GID = 1000


#: **Read from the binary, not guessed** (GP-42). `process.env["GOOGLE_GEMINI_BASE_URL"]`
#: appears 32 times in the bundle and is interpolated into the request URL, so
#: this is the variable the agent itself reads.
#:
#: This field published `null` until the platform's boot-gate suite refused it:
#: AS-29 requires every image to name one. The refusal was right and the
#: original caution was too -- what closed the gap was measuring rather than
#: choosing a plausible name. The redirect itself is measured and it works
#: (GP-53) -- but setting it also disables the agent's own auth selection unless
#: the session's settings file names one, which is GP-54 and `AUTH_SELECTION`.
#: **The agent target this build drives** (user, 2026-08-16; GP-61).
#: `gemini`, not `gemini`: this names the FAMILY, and the implementation
#: suffix is deliberately not in it. `impl.name` is `gemini-python` and carries the
#: language; a second build of the same target in another language would
#: publish the same `gemini` here and a different `impl.name` there, which is
#: why this is not a restatement of that field.
#:
#: **The consumer maps it to a vendor API themselves** -- `gemini` -> the
#: Gemini API. That mapping was offered to us as this field's value and
#: the user chose the family name instead; GP-61 carries the decision and what
#: was traded for it.
MODEL_API = "gemini"

ENDPOINT_ENV_VAR: str | None = "GOOGLE_GEMINI_BASE_URL"

#: The variable this build reads an ADDITIONAL certificate authority from,
#: published as `ca_bundle_source` (GP-55). **`SSL_CERT_FILE` does nothing here**,
#: which is the answer that makes the field worth publishing at all: it is what
#: the other two builds read, so one variable set fleet-wide covers two of three
#: and silently fails on this one.
#:
#: This is the only build of the three with a visible Node runtime, and the
#: variable is Node's own -- it ADDS to the root store rather than replacing it,
#: measured against a public host with only a private authority configured.
CA_BUNDLE_SOURCE: dict[str, object] | None = {
    "variable": "NODE_EXTRA_CA_CERTS",
    "shape": "file",
    "replaces_default_trust": False,
}


# --- the auth method the session's settings file must name -------------------
#
# **Setting the endpoint variable makes the agent choose an auth method its own
# validator then rejects** (GP-54): `getAuthTypeFromEnv` returns `gateway` when
# `GOOGLE_GEMINI_BASE_URL` is set, ahead of the branch that would have chosen
# `gemini-api-key`, and the CLI's `validateAuthMethod` has no case for it. Exit
# 41, no request attempted. An explicitly configured method takes precedence
# over that inference, so writing one is the fix and it belongs to us -- the
# settings file is ours, written per session.

#: What the agent's own `AuthType` calls each method, and the order is the
#: agent's own minus the `gateway` branch that cannot validate (GP-54).
AUTH_SELECTION: tuple[tuple[str, str], ...] = (
    ("GOOGLE_GENAI_USE_GCA", "oauth-personal"),
    ("GOOGLE_GENAI_USE_VERTEXAI", "vertex-ai"),
)

#: The method a bare `GEMINI_API_KEY` selects, which is every deployment that
#: reaches this service through a gateway.
AUTH_SELECTION_API_KEY = "gemini-api-key"


def auth_selection() -> str | None:
    """The `security.auth.selectedType` for this deployment, or `None`.

    **`None` means write no auth block**, which leaves the agent to its own
    inference and its own message. This service does not invent a method for an
    environment that names none -- a wrong one fails at the gateway with a
    refusal naming neither the endpoint nor the credential, which is exactly the
    failure GP-53 warned about.
    """
    for variable, method in AUTH_SELECTION:
        if os.environ.get(variable) == "true":
            return method
    if any(os.environ.get(name) for name in CREDENTIAL_ENV_VARS):
        return AUTH_SELECTION_API_KEY
    return None


def credentials_configured() -> bool:
    """Whether any credential or provider selector is set.

    **The same list the pre-boot command publishes**, so what is advertised
    cannot drift from what is checked.
    """
    return any(
        os.environ.get(name)
        for name in (*CREDENTIAL_ENV_VARS, *PROVIDER_SELECTOR_ENV_VARS)
    )


# --- settings ---------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Everything this build reads from its environment, resolved once.

    **A frozen dataclass and not a settings library**, for the reason `spec.py`
    imports this module: it has to be constructible in an image whose service
    cannot start, and a validation framework is a dependency that boot gate does
    not need.
    """

    workspace_dir: Path
    #: Where the AGENT's own session storage goes -- ours, not the container's
    #: (GP-39). One directory per session lives under here.
    agent_home_root: Path
    #: Where transcripts are kept once copied out of the agent's reach (GP-10).
    transcript_store: Path
    #: A path, or a command vector. **The agent is a Node program** and the
    #: test double is a Python one, so a field that can only hold one executable
    #: shape cannot be exercised without the real thing.
    gemini_binary: Path | tuple[str, ...]
    model: str | None = None
    max_sessions: int = 8
    turn_timeout_s: int = DEFAULT_TURN_TIMEOUT_S
    #: How long an idle session is kept. **Published in `limits`, so it is a
    #: promise**: a consumer sizes a reconciliation window from it, and a number
    #: nothing enforces would be worse than none.
    session_idle_ttl_s: int = 1800
    require_credentials: bool = True
    require_mounts: bool = False
    #: Whether a caller may send `options.mcp_servers`. **A deployment setting,
    #: published as `capabilities.allow_mcp_servers`.** An MCP server on the
    #: stdio transport is a SUBPROCESS this service starts with the session and
    #: which appears in no turn's events, so an operator who needs every process
    #: start attributable to a turn turns this off.
    allow_mcp_servers: bool = True
    #: Where runs and transcripts are recorded. `None` disables persistence
    #: entirely, and that is a supported configuration rather than a degraded
    #: one: the history routes then refuse with a NAMED type, `/healthz` reports
    #: `database_usable: null`, and SQLAlchemy is never imported.
    database_url: str | None = None
    #: The container's `AGENT_ID`, stamped on every row this instance writes so
    #: two instances sharing a database stay distinguishable.
    agent_id: str | None = None
    #: The bearer token `/v1` requires, or `None` for an open deployment.
    #: **Per instance, never per fleet** -- see `auth.py`, and see GP-51 for what
    #: popping it out of the environment does and does not buy.
    auth_token: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        def _flag(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            return default if raw is None else raw.strip().lower() in {"1", "true", "yes"}

        root = Path(os.environ.get("AGENT_SERVICE_WORKSPACE_DIR", "./workspace")).resolve()
        return cls(
            workspace_dir=root,
            agent_home_root=Path(
                os.environ.get("AGENT_SERVICE_AGENT_HOME_ROOT", "./temp/agent-home")
            ).resolve(),
            transcript_store=Path(
                os.environ.get("AGENT_SERVICE_TRANSCRIPT_STORE", "./temp/transcripts")
            ).resolve(),
            gemini_binary=Path(os.environ.get("AGENT_SERVICE_GEMINI_BINARY", "gemini")),
            model=os.environ.get("AGENT_SERVICE_MODEL") or None,
            max_sessions=int(os.environ.get("AGENT_SERVICE_MAX_SESSIONS", "8")),
            turn_timeout_s=int(
                os.environ.get("AGENT_SERVICE_TURN_TIMEOUT_S", str(DEFAULT_TURN_TIMEOUT_S))
            ),
            session_idle_ttl_s=int(
                os.environ.get("AGENT_SERVICE_SESSION_IDLE_TTL_S", "1800")
            ),
            require_credentials=_flag("AGENT_SERVICE_REQUIRE_CREDENTIALS", True),
            require_mounts=_flag("AGENT_SERVICE_REQUIRE_MOUNTS", False),
            allow_mcp_servers=_flag("AGENT_SERVICE_ALLOW_MCP_SERVERS", True),
            # **POPPED, not read, and on this build that is not a nicety.**
            # `CliRunner.env()` hands the agent `{**os.environ, ...}` -- the
            # whole environment, by construction -- and the agent runs tools. A
            # connection string left in `os.environ` is therefore one `env` away
            # from the model's context. After this it lives only in this object.
            #
            # `GEMINI_API_KEY` cannot be hidden the same way: the agent needs it
            # to authenticate, so it is readable by construction. The honest
            # framing is that the agent is inside this process's trust boundary,
            # and the pop shrinks what a leak yields rather than closing it.
            database_url=os.environ.pop("AGENT_SERVICE_DATABASE_URL", None) or None,
            # **Popped for the same reason, and GP-51 measures exactly what that
            # is worth**: a child does NOT inherit it, and it remains readable
            # in `/proc/<pid>/environ` to anything running as the same uid --
            # which the agent does. So the pop stops the token being handed to
            # the agent; it does not put it beyond the agent's reach. The
            # difference matters when choosing a token, and the answer is the
            # same either way: per instance, never per fleet.
            auth_token=os.environ.pop("AGENT_SERVICE_AUTH_TOKEN", None) or None,
            agent_id=os.environ.get("AGENT_ID") or None,
            log_level=os.environ.get("AGENT_SERVICE_LOG_LEVEL", "INFO"),
        )


class BootRefused(RuntimeError):
    """A misconfiguration this build refuses to start with. **Always exit 3.**

    An orchestrator can tell exit 3 from a crash, and every message names the
    remedy -- including the one the gate cannot see (GP-07).
    """


class MissingCredentials(BootRefused):
    """No credential and none of the provider selectors.

    **The CLASS NAME is part of the contract**, not only the message: the
    platform's boot-gate suite reads it out of the container's log to tell one
    refusal from another, so every implementation raises the same two names. A
    single shared exception type made both gates indistinguishable in a log --
    found by that suite rather than by review.
    """


class MissingMounts(BootRefused):
    """The workspace is not on a real mount, so writes would be discarded."""


def check_boot(settings: Settings) -> None:
    """The gates, in the order a deployment trips them."""
    if settings.require_credentials and not credentials_configured():
        raise MissingCredentials(
            "This service refuses to start because no credential is set. Set one "
            f"of {', '.join(CREDENTIAL_ENV_VARS)}, or a provider selector "
            f"({', '.join(PROVIDER_SELECTOR_ENV_VARS)}).\n"
            f"{CREDENTIAL_GATE_BLIND_SPOT}\n"
            "To start anyway -- for a docs-only boot -- set "
            "AGENT_SERVICE_REQUIRE_CREDENTIALS=false."
        )
    if settings.require_mounts and not _on_a_mount(settings.workspace_dir):
        raise MissingMounts(
            "This service refuses to start because "
            f"AGENT_SERVICE_WORKSPACE_DIR={settings.workspace_dir} is "
            "not on a mounted filesystem. It exists only because this service "
            "created it, so anything the agent writes there is discarded when "
            "the container stops. Mount it: -v /host/path:/workspace\n"
            "To start anyway set AGENT_SERVICE_REQUIRE_MOUNTS=false."
        )


def _on_a_mount(path: Path) -> bool:
    """Whether `path` sits under a real mount rather than the image layer.

    **Under a mount point, not merely existing** -- existing is precisely what
    the misconfiguration produces, because the service creates the directory on
    first use.
    """
    try:
        return path.exists() and path.stat().st_dev != Path(path.anchor or "/").stat().st_dev
    except OSError:  # pragma: no cover - unreadable anchor
        return False
