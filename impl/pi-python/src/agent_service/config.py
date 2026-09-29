"""Configuration, and the constants the pre-boot specification publishes.

**Stdlib only, deliberately.** `agent_service.spec` imports this and has to be
constructible in an image whose service cannot start, so nothing here may reach
for a web stack, a settings library or the agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --- credentials -------------------------------------------------------------
#
# **This list is SHORTER than what the agent accepts, and that is deliberate**
# (`PI-02`). Pi resolves credentials for 30-plus providers, and its own
# bundled provider documentation maps each to its variable. A boot gate that checked all of
# them would be a list nobody maintains, and one that checked none would let
# every session spawn an agent that cannot authenticate.
#
# So: the three measured end to end, each having driven a real turn through this
# agent on 2026-09-07. A deployment using a fourth provider sets
# `AGENT_SERVICE_REQUIRE_CREDENTIALS=false` and the refusal message says so.

CREDENTIAL_ENV_VARS: list[str] = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
]

#: **Empty, and it is not an oversight** (`PI-03`). On the other three builds a
#: provider selector is an environment switch -- Bedrock, Vertex, Foundry. Pi
#: selects its provider with a per-request FLAG (`--provider`), so the choice
#: lives in `RunOptions.model` rather than in the container's environment, and
#: publishing a variable here would name a lever that does not exist.
PROVIDER_SELECTOR_ENV_VARS: list[str] = []

#: **A fourth auth channel no boot gate can see** (`PI-04`). Pi also reads
#: `<agent dir>/auth.json`, which OUTRANKS every environment variable and is
#: what `/login` writes. A mounted agent directory carrying an earlier login is
#: authenticated with nothing set here.
CREDENTIAL_GATE_BLIND_SPOT = (
    "Credentials in <agent dir>/auth.json satisfy the agent and are invisible "
    "to this gate -- they also OUTRANK these variables. If that is your "
    "deployment, start with AGENT_SERVICE_REQUIRE_CREDENTIALS=false."
)

# --- the agent's own environment ---------------------------------------------

#: Where Pi keeps auth, its model cache, settings and sessions. **Relocatable,
#: and measured to be complete for its own state** (`PI-05`): with this set, a
#: machine that had never run Pi still had no `~/.pi` afterwards.
AGENT_DIR_ENV_VAR = "PI_CODING_AGENT_DIR"

#: Session storage, overridden by the `--session-dir` flag this build passes.
SESSION_DIR_ENV_VAR = "PI_CODING_AGENT_SESSION_DIR"

#: What every agent invocation this service makes must carry.
#:
#: `PI_OFFLINE` and `PI_SKIP_VERSION_CHECK` stop the agent contacting pi.dev on
#: startup: a container that phones home on every turn is a dependency nobody
#: asked for, and a version check failing inside a customer's network is one
#: more thing to explain. Neither affects model traffic.
#:
#: **Everything NOT listed here passes through from the container**, which is how
#: an operator reaches settings this service has no code for -- the prompt-cache
#: expiry among them (`PI-55`).
AGENT_ENV_OVERRIDES: dict[str, str] = {
    "PI_OFFLINE": "1",
    "PI_SKIP_VERSION_CHECK": "1",
    "PI_TELEMETRY": "0",
}

#: **A wall clock is enforced here as on every build.** 600 s matches the others.
DEFAULT_TURN_TIMEOUT_S = 600

#: Where the image installs Pi's MCP adapter (`PI-43`). **A fixed path outside
#: any session's directory**, because the adapter is 42 packages and installing
#: it per session would put that cost on every `POST /v1/sessions`.
#:
#: Empty when the adapter is absent, which is what a plain checkout looks like:
#: MCP is then unavailable and `allow_mcp_servers` publishes false rather than
#: promising a route the deployment cannot take.
MCP_ADAPTER_PATH_ENV_VAR = "AGENT_SERVICE_MCP_ADAPTER_PATH"


def _gateways(raw: str | None) -> dict[str, dict[str, object]]:
    """`AGENT_SERVICE_PROVIDER_GATEWAYS`, parsed. **Empty means unfronted.**

    Shape, keyed by the provider name a caller puts before the slash in
    `RunOptions.model`:

        {"anthropic": {"base_url": "https://gw.example/anthropic",
                       "headers": {"x-tenant-token": "…"}}}

    **A malformed value is a BOOT refusal rather than a silent empty map**
    (`PI-44`). An operator who mistypes this expects their gateway to be in
    front of every turn; falling back to "no gateway" would send the container's
    own credentials straight to the vendor, which is the failure this setting
    exists to prevent.
    """
    import json

    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BootRefused(
            f"AGENT_SERVICE_PROVIDER_GATEWAYS is not valid JSON: {exc}. It maps a "
            'provider name to its gateway, e.g. {"anthropic": {"base_url": '
            '"https://gw/anthropic"}}. Refusing to start rather than running '
            "unfronted: an operator who set this expects every turn to go "
            "through their gateway."
        ) from exc
    if not isinstance(parsed, dict):
        raise BootRefused(
            "AGENT_SERVICE_PROVIDER_GATEWAYS must be a JSON object keyed by "
            f"provider name, not {type(parsed).__name__}."
        )
    out: dict[str, dict[str, object]] = {}
    for provider, entry in parsed.items():
        if not isinstance(entry, dict) or not entry.get("base_url"):
            raise BootRefused(
                f"AGENT_SERVICE_PROVIDER_GATEWAYS[{provider!r}] needs a "
                '`base_url`. Do NOT include the API suffix: the agent appends '
                "its own, and a base_url ending `/v1` produces `/v1/v1/…`."
            )
        out[str(provider)] = {
            "base_url": str(entry["base_url"]).rstrip("/"),
            "headers": dict(entry.get("headers") or {}),
        }
    return out

# --- the listen specification, published in the document ----------------------
#
# AS-28: all IPv4 interfaces, never loopback -- a consumer reaches this across a
# container boundary, and a service bound to 127.0.0.1 inside a container is
# reachable from nothing.

LISTEN_ADDRESS = "0.0.0.0"  # noqa: S104 - see above
LISTEN_PORT = 8000

#: The numeric uid and gid the container runs as, published as
#: `PrebootSpec.runs_as`. **Numbers, because a host directory needs numbers**: a
#: consumer bind-mounting a directory must chown it before the container exists,
#: and `Config.User` on the image answers a name.
#:
#: A hand-written copy of the Dockerfile's user, and it moves in the same commit
#: as the Dockerfile or not at all.
RUNS_AS_UID = 1000
RUNS_AS_GID = 1000

#: **The agent family this build drives, and it is the first one that does NOT
#: name a vendor** (`PI-06`). `claude` is the Anthropic API, `codex` the OpenAI
#: API, `gemini` the Gemini API -- one mapping each, which is what the field was
#: built for. Pi is a single agent in front of 30-plus providers chosen per
#: request, so no vendor mapping exists to publish and inventing one would be
#: false for every request that chose differently.
#:
#: A consumer keys on `pi` and reads the request's own `model` for the vendor.
MODEL_API = "pi"

#: **`HTTPS_PROXY`, and not a base URL, because there is no single base URL to
#: name** (`PI-07`). The pre-boot contract wants *the one environment variable
#: that redirects this image's model traffic*, singular, "because a consumer
#: choosing from a list is a consumer guessing". Every other build has one:
#: `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `GOOGLE_GEMINI_BASE_URL`.
#:
#: Pi has one per PROVIDER (`AZURE_OPENAI_BASE_URL` and so on), which is exactly
#: the list a consumer would have to guess from. The proxy is the lever that
#: redirects all of it regardless of provider -- Pi documents `HTTP_PROXY` and
#: `HTTPS_PROXY` on its environment page and applies its `httpProxy` setting as
#: both -- so it is the only honest singular answer on a multi-provider target.
ENDPOINT_ENV_VAR: str | None = "HTTPS_PROXY"

#: **The variable a GATEWAY is delivered under, which the proxy above cannot be**
#: (`PI-56`). `endpoint_source` stays `HTTPS_PROXY` and stays true: it is still
#: the one variable that moves every turn, including a provider this map has no
#: entry for. What it is not is frontable -- behind `CONNECT` an intermediary
#: reads a host name and ciphertext, so it can neither swap the credential nor
#: count the call, and both are load-bearing for the consumer who asked.
#:
#: The four facts here are the four a deployment gets wrong: the name, the KEYS
#: (`PI-57`), the `/v1` that must not be on the base URL (`PI-42`), and what
#: happens to a provider with no entry (`PI-44`).
GATEWAY_MAP_SOURCE: dict[str, object] | None = {
    "variable": "AGENT_SERVICE_PROVIDER_GATEWAYS",
    # **The agent's own ids, measured rather than named after our credentials**
    # (`PI-57`). `google` is the one that surprises: the variable is
    # `GEMINI_API_KEY` and the id is not `gemini`.
    "provider_ids": ["anthropic", "google", "openai"],
    "agent_appends_api_suffix": True,
    "unconfigured_provider": "refused",
}

#: **The provider ids this build will PIN on the command line** (`PI-62`), which
#: is the published set above and nothing else. A qualified `model` whose prefix
#: is in here is passed to the agent as `--provider <prefix> --model <whole>`,
#: which stops the agent re-matching the whole string across every provider it
#: knows and sending the turn somewhere nobody configured.
#:
#: **A prefix outside this set is left alone on purpose.** Not every slash in a
#: model id is a provider -- the agent's own catalogue carries 42 vendor
#: prefixes that are not provider ids (`zai-org/GLM-5.2`, `meta-llama/…`), and
#: pinning one of those turns a request that resolves today into
#: `Unknown provider`. The set is the three we vouch for, so it moves with
#: `provider_ids` and never ahead of it.
PINNABLE_PROVIDER_IDS: frozenset[str] = frozenset(
    GATEWAY_MAP_SOURCE["provider_ids"]  # type: ignore[index,arg-type]
    if GATEWAY_MAP_SOURCE
    else ()
)

#: **Node's own variable, and the claim is about the RUNTIME rather than about
#: Pi** (`PI-08`). Pi's package does not read it; Node does, process-wide, before
#: any application code runs, which is why it works here and why the entry says
#: what was and was not measured. It ADDS to the root store rather than replacing
#: it, so a container can reach a public host and a privately-signed one at once.
#:
#: `SSL_CERT_FILE` does nothing here -- it is what two of the other three builds
#: read, so one variable set fleet-wide covers those two and silently fails here.
#: Where the agent keeps its own state, published as `PrebootSpec.agent_home`
#: (`PI-58`).
#:
#: **`scope: "per_session_root"`, and that value is why this field is an object
#: rather than a name.** The directory named here is not a home: it holds one
#: per session, minted empty when the session opens and removed when it closes,
#: so a consumer that relocated it onto a mount to deliver a user's own
#: configuration would deliver nothing and no turn would report it.
#: `seed_source` is the lever that reaches those homes.
#:
#: **Conversations are elsewhere and have a variable of their own.** Unlike the
#: Gemini build this service keeps no rescued copy -- `--session-dir` points the
#: agent straight at the store (`PI-09`) -- but the consequence for a consumer
#: is the same: moving the home does not move the conversations.
AGENT_HOME_SOURCE: dict[str, object] = {
    "variable": "AGENT_SERVICE_AGENT_HOME",
    "default_path": "/var/lib/agent-service/agent-dirs",
    "scope": "per_session_root",
    "holds_credentials": False,
    "conversations": {
        "in_home": False,
        "variable": "AGENT_SERVICE_SESSION_STORE",
        "default_path": "/var/lib/agent-service/sessions",
    },
    "seed_source": "AGENT_SERVICE_AGENT_HOME_SEED",
    # **What `pi.py` writes AFTER the seed, so a seeded copy of either is
    # overwritten wholesale** (`PI-58`). Both are written only when the
    # corresponding feature is configured, and both are listed anyway: a
    # consumer composing a seed cannot know which deployment it will land in,
    # and a path that is reserved on some containers and not others is reserved.
    "seed_reserved_paths": ["models.json", "mcp.json"],
    # A resumed turn opens a session like any other -- a fresh agent directory,
    # seeded the same way -- so there is no divergence to publish.
    "read_on_resume": "always",
}

CA_BUNDLE_SOURCE: dict[str, object] | None = {
    "variable": "NODE_EXTRA_CA_CERTS",
    "shape": "file",
    "replaces_default_trust": False,
}


def credentials_configured() -> bool:
    """Whether any credential this gate knows about is set.

    **The same list the pre-boot specification publishes**, so what is advertised
    cannot drift from what is checked.
    """
    return any(os.environ.get(name) for name in CREDENTIAL_ENV_VARS)


# --- settings -----------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Everything this build reads from its environment, resolved once.

    **A frozen dataclass and not a settings library**, for the reason `spec.py`
    imports this module: it must be constructible in an image whose service
    cannot start, and a validation framework is a dependency that gate does not
    need.
    """

    workspace_dir: Path
    #: Where the AGENT's own state goes -- ours, not the container's (`PI-05`).
    #: One directory per session lives under here.
    agent_dir_root: Path
    #: Where session transcripts are kept. **Pi does not destroy its own**
    #: (`PI-09`), unlike the Gemini target, so this is a plain location rather
    #: than a rescue: `--session-dir` points the agent straight at it.
    session_store: Path
    #: A path, or a command vector. **The agent is a Node program** and the test
    #: double is a Python one, so a field that can hold only one executable shape
    #: cannot be exercised without the real thing.
    pi_binary: Path | tuple[str, ...]
    #: A directory whose contents are copied into every minted agent directory
    #: before the agent starts, or `None` for none (`PI-58`).
    #:
    #: **The only way to put anything into an agent directory on this build.**
    #: `agent_dir_root` above is a PARENT of them, each created empty per session
    #: and removed with it, so a file placed at the root is one level above every
    #: directory the agent ever reads.
    agent_home_seed: Path | None = None
    #: The provider passed as `--provider`. **Separate from the model, because Pi
    #: addresses a model as provider PLUS id** (`PI-10`).
    provider: str | None = None
    model: str | None = None
    max_sessions: int = 8
    turn_timeout_s: int = DEFAULT_TURN_TIMEOUT_S
    #: How long an idle session is kept. Published in `limits`, so it is a
    #: promise: a consumer sizes a reconciliation window from it.
    session_idle_ttl_s: int = 1800
    require_credentials: bool = True
    require_mounts: bool = False
    #: Where runs and transcripts are recorded. `None` disables persistence
    #: entirely, and that is a supported configuration rather than a degraded
    #: one.
    database_url: str | None = None
    #: The container's `AGENT_ID`, stamped on every row this instance writes so
    #: two instances sharing a database stay distinguishable.
    agent_id: str | None = None
    #: The bearer token `/v1` requires, or `None` for an open deployment.
    #: **Per instance, never per fleet.**
    auth_token: str | None = None
    #: Provider name to `{base_url, headers}` (`PI-44`). **Empty means this
    #: deployment is not fronted** and every provider reaches its vendor
    #: directly. Non-empty means the map IS the allow-list: a provider with no
    #: entry is refused with a 400 rather than leaking past the gateway.
    provider_gateways: dict[str, dict[str, object]] = field(default_factory=dict)
    #: Where the image put Pi's MCP adapter, or `None` (`PI-43`). `None`
    #: publishes `allow_mcp_servers: false` and refuses `mcp_servers`.
    mcp_adapter_path: Path | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        def _flag(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            return default if raw is None else raw.strip().lower() in {"1", "true", "yes"}

        root = Path(os.environ.get("AGENT_SERVICE_WORKSPACE_DIR", "./workspace")).resolve()
        return cls(
            workspace_dir=root,
            # **The uniform name wins over this build's own** (`PI-58`), and it
            # has to: the image sets `AGENT_SERVICE_AGENT_DIR_ROOT`, so that one
            # is never absent inside a container and reading it first would make
            # the published name unusable on exactly the deployments it is for.
            agent_dir_root=Path(
                os.environ.get("AGENT_SERVICE_AGENT_HOME")
                or os.environ.get("AGENT_SERVICE_AGENT_DIR_ROOT")
                or "./temp/agent-dirs"
            ).resolve(),
            agent_home_seed=(
                Path(seed).resolve()
                if (seed := os.environ.get("AGENT_SERVICE_AGENT_HOME_SEED"))
                else None
            ),
            session_store=Path(
                os.environ.get("AGENT_SERVICE_SESSION_STORE", "./temp/sessions")
            ).resolve(),
            pi_binary=Path(os.environ.get("AGENT_SERVICE_PI_BINARY", "pi")),
            provider=os.environ.get("AGENT_SERVICE_PROVIDER") or None,
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
            # **POPPED, not read.** The agent is handed this process's
            # environment and the agent runs shell tools, so a connection string
            # left in `os.environ` is one `env` away from the model's context.
            # After this it lives only in this object.
            database_url=os.environ.pop("AGENT_SERVICE_DATABASE_URL", None) or None,
            # Popped for the same reason. It stops the token being handed to the
            # agent; it does not put it beyond the agent's reach, since
            # `/proc/<pid>/environ` is readable to the same uid. Hence: per
            # instance, never per fleet.
            auth_token=os.environ.pop("AGENT_SERVICE_AUTH_TOKEN", None) or None,
            # **Popped for the same reason as the two above**: the gateway map
            # can carry a per-tenant token in `headers`, and the agent is handed
            # this process's environment.
            provider_gateways=_gateways(
                os.environ.pop("AGENT_SERVICE_PROVIDER_GATEWAYS", None)
            ),
            mcp_adapter_path=(
                Path(raw).resolve()
                if (raw := os.environ.get(MCP_ADAPTER_PATH_ENV_VAR))
                else None
            ),
            agent_id=os.environ.get("AGENT_ID") or None,
            log_level=os.environ.get("AGENT_SERVICE_LOG_LEVEL", "INFO"),
        )


class BootRefused(RuntimeError):
    """A misconfiguration this build refuses to start with. **Always exit 3.**

    An orchestrator can tell exit 3 from a crash, and every message names the
    remedy -- including the one the gate cannot see (`PI-04`).
    """


class MissingCredentials(BootRefused):
    """No credential this gate recognises.

    **The CLASS NAME is part of the contract**, not only the message: the
    platform's boot-gate suite reads it out of the container's log to tell one
    refusal from another, so every implementation raises the same two names.
    """


class MissingMounts(BootRefused):
    """The workspace is not on a real mount, so writes would be discarded."""


class UnusableAgentHomeSeed(BootRefused):
    """`AGENT_SERVICE_AGENT_HOME_SEED` names something that is not a directory.

    **A refusal rather than a warning** (`PI-58`). A seed that silently copies
    nothing leaves every session with an empty agent directory, which is
    indistinguishable from the variable never having been set -- and the
    deployment that set it believes a user's configuration is being delivered.
    """


def check_boot(settings: Settings) -> None:
    """The gates, in the order a deployment trips them."""
    if settings.require_credentials and not credentials_configured():
        raise MissingCredentials(
            "This service refuses to start because no credential is set. Set one "
            f"of {', '.join(CREDENTIAL_ENV_VARS)}.\n"
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
    # **Not gated by `require_mounts`** (`PI-58`): this is a variable that was
    # set and cannot do the one thing it was set for, which no configuration
    # makes acceptable to start past.
    if settings.agent_home_seed is not None and not settings.agent_home_seed.is_dir():
        raise UnusableAgentHomeSeed(
            "This service refuses to start because "
            f"AGENT_SERVICE_AGENT_HOME_SEED={settings.agent_home_seed} is not a "
            "directory. Its contents are copied into every session's agent "
            "directory, so every session would start with an empty one and no "
            "turn would report anything wrong. Mount the directory, or unset "
            "the variable."
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
