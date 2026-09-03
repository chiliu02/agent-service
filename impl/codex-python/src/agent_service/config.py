"""Configuration constants this build publishes before it can boot.

Only what `agent_service.spec` needs lives here for now; the rest of the
settings surface arrives with the service itself.
"""

from __future__ import annotations

# --- the credential specification, published in the document ----------------
#
# **THE APP-SERVER DOES NOT READ EITHER OF THESE.** Measured 2026-08-08, and it
# is the opposite of what this file assumed until then: with `OPENAI_API_KEY`
# exported into the subprocess (`CodexConfig.env` merges into `os.environ`, it
# does not replace it), `account()` still returns `None`, `requires_openai_auth`
# stays true, and a turn reaches the API with no `Authorization` header at all --
# `401 Missing bearer or basic authentication in header`. Setting `CODEX_API_KEY`
# instead changes nothing. The names are real: they are in the bundled `codex`
# binary. They are simply not how the *app-server* authenticates.
#
# **The only route in is `login_api_key()`**, which writes the key into the
# app-server's auth store under `CODEX_HOME`. So these variables are where THIS
# SERVICE reads a key from before performing that login -- see
# `CodexSession.open()`. The boot gate stays meaningful because the login is
# implemented, not because the SDK does it.
#
# One question this closes: precedence used to be recorded as unmeasured. It is
# no longer the SDK's to decide -- this service picks, and it picks list order.
CREDENTIAL_ENV_VARS: list[str] = [
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
]

# Selectors, NOT credentials: they choose where the model is reached, and the
# credential still comes from somewhere else. EMPTY FOR NOW and deliberately so
# -- the Claude build's three (`CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`)
# have no measured equivalent here yet. An empty list is an honest answer; a
# guessed one would send a caller to inject something this image ignores, which
# is the exact failure the two-list split exists to prevent.
PROVIDER_SELECTOR_ENV_VARS: list[str] = []

# --- the listen specification, published in the document --------------------
#
# AS-28: all IPv4 interfaces, never loopback -- a consumer reaches this
# container by name on a Docker network and loopback would delete that route.
# AS-29: the port is published rather than frozen into the specification, which
# is why this build may state its own.
#
# Above 1024 so no CAP_NET_BIND_SERVICE is needed. Same value as the Claude
# build, deliberately: nothing is gained by differing.
LISTEN_ADDRESS = "0.0.0.0"
LISTEN_PORT = 8000
#: The numeric uid and gid the container runs as, published as
#: `PrebootSpec.runs_as`. **Numbers, because a host directory needs numbers**: a
#: consumer bind-mounting a directory it composes must chown it before the
#: container exists, and `Config.User` on the image answers `agent` -- a name,
#: which resolves to a number only by running the container.
#:
#: **A hand-written copy of the Dockerfile's `useradd --uid`**, like the document
#: label beside it, and it moves in the same commit or not at all. The
#: conformance suite reads it out of a running container and compares.
RUNS_AS_UID = 1000
RUNS_AS_GID = 1000



# --- settings ---------------------------------------------------------------

import os  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

#: Tools this build grants by default. **Codex governs by SANDBOX, not by tool
#: list** -- see `options.py` -- so this is what `/v1/capabilities` publishes and
#: is NOT a per-request control here. Published anyway because the specification
#: requires the field and a caller comparing implementations should see the
#: difference rather than infer it.
DEFAULT_ALLOWED_TOOLS: list[str] = []

#: Enforced on every request and never overridable. Empty for this build:
#: `AskUserQuestion` is a Claude CLI tool with no Codex equivalent, and listing
#: a tool that cannot exist would be theatre.
ALWAYS_DISALLOWED_TOOLS: list[str] = []


@dataclass(slots=True)
class Settings:
    """Resolved configuration. `AGENT_SERVICE_`-prefixed, like every build.

    **A dataclass, not pydantic-settings**, deliberately: `agent-spec` is
    pydantic-only and this module must not drag a second settings framework
    into a package that has no need of one. The Claude build's `Settings` is
    pydantic because it predates the split; nothing requires them to match.
    """

    workspace_dir: Path = Path("./workspace")
    reference_dirs: list[Path] = field(default_factory=list)
    codex_home: Path = Path("./codex-home")

    #: **A model measured to answer, which `gpt-5-codex` was not** (user,
    #: 2026-08-10). Every codex-family model returns 404 from `/v1/responses` on
    #: the key this was measured with -- twice, a day apart, with `gpt-5.1`,
    #: `gpt-5-mini` and `gpt-4.1-mini` answering 200 as the control -- so the
    #: old default failed every turn that did not override it, after 30s of the
    #: app-server retrying a 404 that cannot succeed. A default nobody here has
    #: ever seen work is a guess; this one is measured. (CX-21)
    default_model: str = "gpt-5.1"
    default_permission_mode: str = "dontAsk"

    max_sessions: int = 8
    session_idle_ttl_s: int = 1800

    #: The whole of `SessionRegistry.close_all()`, in seconds. **Arithmetic, and
    #: `compose.yaml`'s `stop_grace_period` is derived from it** -- Docker
    #: SIGKILLs at that number whether or not the sweep has finished, so the two
    #: cannot be chosen independently. `test_the_compose_grace_period_follows_
    #: the_shutdown_budget` fails if they stop agreeing.
    #:
    #: **60s is a derivation, not a guess** (CX-38): the SDK's own close is
    #: bounded -- `terminate()`, `wait(timeout=2)`, `kill()` on any exception,
    #: then two 0.5s thread joins -- so one close costs at most ~3s, and a
    #: container carries about 16 sessions (CX-19). 16 x 3 = 48s, and 60 leaves
    #: the margin. What this bounds is N of those ADDING UP, which is what had
    #: no bound at all before.
    shutdown_budget_s: float = 60.0

    #: Whether a caller may configure MCP servers. **True since 2026-08-09**,
    #: when the approval policy made an MCP tool call reachable at all -- before
    #: that this build could configure a server and never let the agent call it.
    #:
    #: An operator turns it off for ATTRIBUTION rather than capability, which is
    #: the Claude build's reasoning unchanged: a `stdio` server is a subprocess
    #: that starts with the session, before any prompt, and appears in no turn's
    #: events -- while a shell command is the agent's own decision and is
    #: recorded.
    allow_mcp_servers: bool = True

    default_max_turns: int = 30
    max_allowed_turns: int = 200
    default_max_budget_usd: float = 2.0
    max_allowed_budget_usd: float = 10.0
    default_request_timeout_s: int = 600
    max_allowed_timeout_s: int = 1800

    #: What this service's own records are filtered at. **Read by `main.py`, not
    #: by anything under `api.py`** -- process-wide logging is the entrypoint's
    #: business, and configuring it inside `create_app()` would reconfigure the
    #: root logger under pytest's capture on every one of the hundred-odd apps a
    #: test run builds.
    log_level: str = "INFO"

    require_credentials: bool = True
    require_mounts: bool = True
    auth_token: str | None = None
    database_url: str | None = None

    #: **Provenance, not authorisation.** The `AGENT_ID` of the container,
    #: reported on every `SessionRecord` so a consumer can tell which container
    #: created a session. This service neither parses it nor acts on it.
    #:
    #: Read from the BARE name, not `AGENT_SERVICE_AGENT_ID`: it is set by
    #: whatever provisions the container, not by this service's own
    #: configuration, and the consumer that sets it uses the short name.
    agent_id: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        """Read `AGENT_SERVICE_*`. Absent means the default, never an error."""

        def _get(name: str) -> str | None:
            return os.environ.get(f"AGENT_SERVICE_{name.upper()}")

        def _flag(name: str, default: bool) -> bool:
            raw = _get(name)
            return default if raw is None else raw.strip().lower() not in ("false", "0", "no")

        settings = cls(
            require_credentials=_flag("require_credentials", True),
            require_mounts=_flag("require_mounts", True),
            auth_token=_get("auth_token") or None,
            # POPPED, not read. **A security requirement, not tidiness**, and
            # the clause Studio asked for on the database-url thread: the
            # agent's subprocess inherits this process's environment and can run
            # shell commands, so a connection string left in `os.environ` is one
            # `env` away from the agent -- and therefore from anything that can
            # influence its prompt. After this it lives only in this object.
            #
            # `OPENAI_API_KEY` cannot be hidden the same way: the login needs
            # it, so it is readable by the agent by construction. The honest
            # framing is that the agent is inside this process's trust boundary,
            # and the pop shrinks what a leak yields rather than closing it.
            database_url=os.environ.pop("AGENT_SERVICE_DATABASE_URL", None) or None,
            # The bare name, deliberately -- see the field.
            agent_id=os.environ.get("AGENT_ID") or None,
        )
        if (ws := _get("workspace_dir")) is not None:
            settings.workspace_dir = Path(ws)
        if (home := _get("codex_home")) is not None:
            settings.codex_home = Path(home)
        if (model := _get("default_model")) is not None:
            settings.default_model = model
        if (cap := _get("max_sessions")) is not None:
            settings.max_sessions = int(cap)
        if (allow := _get("allow_mcp_servers")) is not None:
            settings.allow_mcp_servers = allow.strip().lower() not in {"0", "false", "no"}
        if (level := _get("log_level")) is not None:
            settings.log_level = normalise_log_level(level)
        return settings


def normalise_log_level(value: str) -> str:
    """`"info"` -> `"INFO"`, or a `ValueError` naming the valid set.

    **`logging` matches level names case-SENSITIVELY**, so an unnormalised
    `AGENT_SERVICE_LOG_LEVEL=info` aborts the boot with `Unknown level: 'info'`
    from inside `basicConfig` -- a confusing place for a configuration typo to
    surface, and a container that exits without saying which variable was wrong.
    """
    import logging

    name = value.strip().upper()
    if name not in logging.getLevelNamesMapping():
        valid = ", ".join(n for n in logging.getLevelNamesMapping() if n != "NOTSET")
        raise ValueError(f"unknown log level {value!r}; expected one of: {valid}")
    return name


def api_key() -> str | None:
    """The key to log the app-server in with, or `None` for none configured.

    **First non-empty name in `CREDENTIAL_ENV_VARS` wins**, which is this
    service's decision rather than the SDK's -- the app-server reads neither
    variable, so nothing upstream defines a precedence to defer to.

    Stripped, because a key pasted into a `.env` file arrives with a trailing
    newline often enough to be worth handling here rather than as a 401 with no
    explanation.
    """
    for name in CREDENTIAL_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def credentials_configured() -> bool:
    """True when the boot gate is satisfied.

    **A presence check on the published names, and it does not claim more.**
    Codex can also be authenticated through its app-server auth store, which
    this cannot see -- a login performed on an earlier run persists in
    `CODEX_HOME` -- so a `false` here does not prove the agent cannot
    authenticate, only that this build's gate is unsatisfied. Recorded because
    the Claude build's identical function CAN make the stronger claim, and the
    difference matters to anyone reading both.

    **Shares `api_key()`'s reading of the environment on purpose.** A gate that
    accepted a value the login step would then reject -- whitespace only, say --
    would pass boot and fail every turn, which is the worst of both.
    """
    if api_key() is not None:
        return True
    return any(os.environ.get(name) for name in PROVIDER_SELECTOR_ENV_VARS)


class MissingCredentials(RuntimeError):
    """No credential is configured and the service refuses to boot.

    Raised from the FastAPI lifespan's startup, which is what makes an ASGI
    server abort: uvicorn reads the failed lifespan and calls
    `sys.exit(STARTUP_FAILURE)`, so the process exits **3** and an orchestrator
    can tell that from a crash. AS-2, and the same exit code every
    implementation uses.
    """


def verify_credentials(settings: Settings) -> None:
    """Refuse to boot without a credential. Returns or raises.

    **The cost is real and is accepted**, as it is in every build: a credential
    blip at the wrong moment turns a restart into a crash-loop, and the service
    cannot be started for docs-only use without the escape hatch. The trade is
    that an operator finds out at boot rather than on the ninth request.

    **One thing here that the Claude build cannot say.** Codex can also be
    authenticated through its app-server auth store -- `login_api_key()` or a
    ChatGPT login -- which this gate cannot see. So a deployment authenticated
    that way must set `AGENT_SERVICE_REQUIRE_CREDENTIALS=false`, and the message
    says so. Refusing to mention it would send that operator hunting for a
    variable they deliberately did not set.
    """
    if not settings.require_credentials or credentials_configured():
        return
    raise MissingCredentials(
        "No credential is configured, so this service refuses to start: every "
        "session would reach an agent that cannot authenticate. Set "
        f"{' or '.join(CREDENTIAL_ENV_VARS)}. "
        "If this deployment authenticates through the Codex app-server's own "
        "auth store instead -- an API-key or ChatGPT login already performed -- "
        "this gate cannot see it; set "
        "AGENT_SERVICE_REQUIRE_CREDENTIALS=false to start anyway."
    )


#: The variable this build reads its model endpoint from, published as
#: `endpoint_source` in the document's PrebootSpec component (0.19.0).
#:
#: **The app-server reads NO variable for this, and that is measured.** Three
#: probes, each a fresh `CODEX_HOME`, each taking one turn and reading the URL out
#: of the failure: nothing set, `OPENAI_BASE_URL` set, and `CODEX_BASE_URL` set
#: all reached the real API; only an app-server *config* override moved it. The
#: discriminator was not subtle -- a request that reaches OpenAI fails with "no
#: credits remaining" and one that does not names the host it tried.
#:
#: So the name below is one a consumer guessed and this side made true by
#: implementation: the service reads it and translates it into the config route
#: that does work. `endpoint_overrides` is that translation.
#: **The agent target this build drives** (user, 2026-08-16; CX-57).
#: `codex`, not `openai`: this names the FAMILY, and the implementation
#: suffix is deliberately not in it. `impl.name` is `codex-python` and carries the
#: language; a second build of the same target in another language would
#: publish the same `codex` here and a different `impl.name` there, which is
#: why this is not a restatement of that field.
#:
#: **The consumer maps it to a vendor API themselves** -- `codex` -> the
#: OpenAI API. That mapping was offered to us as this field's value and
#: the user chose the family name instead; CX-57 carries the decision and what
#: was traded for it.
MODEL_API = "codex"

ENDPOINT_ENV_VAR = "OPENAI_BASE_URL"

#: The variable this build reads an ADDITIONAL certificate authority from,
#: published as `ca_bundle_source` (CX-51). Measured: `NODE_EXTRA_CA_CERTS` --
#: which the Claude build honours -- does nothing here, and the failure is not an
#: HTTP error. The connection is refused inside the container before anything is
#: sent, so a terminator's access log has no line to correlate with.
#:
#: **`replaces_default_trust` is TRUE, and it is the important half.** This
#: runtime is Rust and the variable REPLACES its root store rather than adding to
#: it: measured, a container given a private authority then fails to reach the
#: real API with *invalid peer certificate: UnknownIssuer*. A deployment that
#: needs both a privately-signed gateway and any public host cannot have both on
#: this build through this variable, and that is worth knowing before a turn
#: fails rather than after.
CA_BUNDLE_SOURCE: dict[str, object] | None = {
    "variable": "SSL_CERT_FILE",
    "shape": "file",
    "replaces_default_trust": True,
}

#: The provider id this build invents to carry a redirected endpoint. Arbitrary,
#: internal, and never seen by a caller -- it exists because the app-server
#: addresses a base URL through a *named provider* rather than directly.
_ENDPOINT_PROVIDER = "agent_service_endpoint"


def endpoint_overrides(base_url: str | None) -> tuple[str, ...]:
    """`-c key=value` overrides that point the app-server at `base_url`.

    **Empty when nothing is configured**, which matters more than it looks: an
    empty tuple means the app-server keeps its own defaults, and a build that
    always injected a provider would be overriding the endpoint even when nobody
    asked it to.

    **`wire_api` is `responses` because that is what the real API speaks** to this
    SDK -- the measured redirect landed on `<base>/responses`. A relay standing in
    for OpenAI has to accept that shape, which is a fact worth having in one place
    rather than discovered by a consumer.

    **The credential is deliberately NOT named here.** `open()` calls
    `login_api_key()`, which writes the key into the app-server's auth store under
    `CODEX_HOME`; adding an `env_key` would create a second credential path whose
    failure mode is a silent fallback to the wrong one.

    One consequence for an operator, and it is an improvement: setting
    `OPENAI_BASE_URL` inside the container by any route other than this service --
    a shell, a sidecar -- changes nothing. Only the value read at startup has an
    effect, which makes this build more predictable than one whose CLI reads the
    ambient environment.
    """
    if not base_url:
        return ()
    return (
        f"model_providers.{_ENDPOINT_PROVIDER}.name=agent-service endpoint",
        f"model_providers.{_ENDPOINT_PROVIDER}.base_url={base_url}",
        f"model_providers.{_ENDPOINT_PROVIDER}.wire_api=responses",
        f"model_provider={_ENDPOINT_PROVIDER}",
    )


def base_url() -> str | None:
    """`OPENAI_BASE_URL` from the environment, or `None`.

    Read at session creation rather than cached at import, for the same reason
    `api_key()` is: a test that sets the variable must not need a reimport.
    """
    value = os.environ.get(ENDPOINT_ENV_VAR)
    return value or None


class UnenforceableAuth(RuntimeError):
    """`AGENT_SERVICE_AUTH_TOKEN` is set and this build cannot enforce it.

    **Kept, unraised, and that is deliberate.** Bearer auth exists on this build
    now (`auth.py`), so nothing raises this today. The class stays because the
    *rule* it encodes outlives its one instance: a protection this service
    publishes and does not perform must stop the boot rather than reach a caller.
    The next capability this build advertises before it implements it should raise
    this rather than invent a second vocabulary for the same refusal.
    """


def verify_auth(settings: Settings) -> None:
    """The gate that used to refuse a token this build could not check.

    **It refuses nothing now, because `auth.py` enforces the token** — bearer on
    `/v1`, `/healthz` exempt, constant-time compare, 401 as a problem document.
    Until 2026-08-08 this build read `AGENT_SERVICE_AUTH_TOKEN`, published
    `auth_required` from it and checked no request against it, so it refused to
    start instead: an API answering every unauthenticated request while both of
    its status surfaces claim protection is worse than one that honestly reports
    none.

    **The function survives the feature it guarded**, and not out of sentiment.
    It is the one place that asserts *published and enforced are the same set* on
    this build, and it is called from the lifespan beside the credential and
    mount gates. When the next advertised-but-unbuilt protection appears — the
    obvious candidate is per-request authorisation — this is where refusing it
    costs one line rather than a new gate.

    (CX-42) records what it was and why it went.
    """
    return


class MissingMounts(RuntimeError):
    """A required directory is not mounted and the service refuses to boot.

    Same mechanism as `MissingCredentials` -- raised from the lifespan, so
    uvicorn exits 3 -- and the same class name as the Claude build's, because
    the specification's conformance suite reads it out of the container's log.
    """


def _mounted_under(path: Path) -> bool:
    """True if `path` or an ancestor below `/` is a mount point.

    **NOT `path.exists()`.** `CodexSession.__init__` calls
    `mkdir(parents=True, exist_ok=True)` on the workspace, and the image creates
    `/workspace` besides -- so a container started with no `-v` has a workspace
    that exists, is writable, and is thrown away when the container stops. That
    is precisely the state this gate is for, and `exists()` cannot see it.

    **And not bare `os.path.ismount(path)`**: pointing `workspace_dir` at a
    subdirectory of a mount is a legitimate layout, so this walks up. `/` is
    excluded on purpose -- a container's root is itself a mount, which would
    make the check pass for every path and quietly do nothing.

    Copied in substance from the Claude build, which measured it: with a bind
    mount at `/workspace` the path appears in `/proc/self/mountinfo`; with the
    directory merely created by the service it does not.
    """
    current = path.resolve()
    root = Path(current.anchor)
    while current != root:
        if os.path.ismount(current):
            return True
        current = current.parent
    return False


def verify_mounts(settings: Settings) -> None:
    """Refuse to boot when the workspace is not on a real mount.

    Neither Docker nor compose catches this: on Docker Desktop for Windows `-v`,
    `--mount type=bind` and compose's `create_host_path: false` were all
    measured (by the Claude build) to create a missing host directory and start
    anyway.

    **`CODEX_HOME` is deliberately NOT gated**, and it is the one place this
    build's gate differs from the Claude build's. An unmounted `CODEX_HOME`
    works -- the service creates it, the app-server unpacks into it, every turn
    runs -- and what is lost is only that threads and the auth store do not
    survive the container. That is a deployment choice, not a
    misconfiguration, so refusing it would refuse a supported configuration.
    (CX-34) states the consequence where an operator will read it.

    **Reference directories are not checked either, because this build has
    none.** `Settings.reference_dirs` is never populated from the environment:
    Codex threads take a `cwd` and nothing else, so a second mount would be
    invisible to the agent. `/v1/capabilities` publishes `reference_dirs: []`,
    which is the honest answer, and a gate over an empty list would be theatre.
    """
    if not settings.require_mounts:
        return
    if _mounted_under(settings.workspace_dir):
        return
    raise MissingMounts(
        "This service refuses to start because a required directory is not "
        "mounted:\n  - "
        f"AGENT_SERVICE_WORKSPACE_DIR={settings.workspace_dir} is not on a "
        "mounted filesystem. It exists only because this service created it, "
        "so anything the agent writes there is discarded when the container "
        "stops. Mount it: -v /host/path:/workspace\n"
        "To start anyway -- for a docs-only boot, or a test harness -- set "
        "AGENT_SERVICE_REQUIRE_MOUNTS=false."
    )


# --- process capacity -------------------------------------------------------
#
# **`max_sessions` is a number this service enforces; `pids_limit` is the thing
# underneath it, and the two are configured independently** -- so a deployment
# can advertise a cap the container cannot carry. Measured 2026-08-09 (CX-19):
# ~30 processes per session, and 16 sessions took the container to 485 of 512.
#
# Each session owns an app-server subprocess which owns the agent's shell
# commands, so the figure is a floor rather than a ceiling: one `make -j` or
# `npm install` inside a turn spends far more than 30 on its own.

#: Processes one idle-to-working session costs. The measured figure, unrounded.
PIDS_PER_SESSION = 30

#: What the container spends before any session exists -- uvicorn plus its
#: worker. Measured at 2 in the same table; 5 here so the estimate errs toward
#: warning rather than toward silence.
PIDS_BASELINE = 5

#: Where the kernel publishes the limit. cgroup v2 first, because that is what
#: Docker Desktop and every current engine use; v1 second for an older host.
_PIDS_MAX_PATHS = ("/sys/fs/cgroup/pids.max", "/sys/fs/cgroup/pids/pids.max")


def process_limit() -> int | None:
    """The container's process cap, or `None` when there is no number to read.

    `None` covers three different situations on purpose -- not in a container,
    a cgroup v1 host laid out differently, and a container started with no
    `pids_limit` (the file reads `max`). **All three mean the same thing here**:
    nothing can be compared, so nothing is claimed. A guessed limit would
    produce a warning about a constraint that does not exist.
    """
    for path in _PIDS_MAX_PATHS:
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw == "max":
            return None
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def process_capacity_warning(settings: Settings, limit: int | None) -> str | None:
    """The sentence to log when `max_sessions` exceeds what the container can spawn.

    **`limit` is required, not defaulted to `process_limit()`**, so that a test
    can state the container it is describing. A default would make the one case
    that matters most -- no limit to read -- the one case a host cannot be asked
    to produce.

    **A warning and never a boot gate, and that is the platform's own rule
    rather than a preference**: *report what can recover, refuse what cannot*.
    Exceeding the process cap is recoverable without a restart -- somebody
    closes a session -- and it already has a named answer: `create()` raises
    `SessionCapacityExhausted` and the caller gets a 503 that says the
    deployment is out of room. A gate here would refuse a boot that is about to
    be correct, which is the argument that settled the schema-revision gate in
    the other direction.

    **And the number it would gate on is an average.** 30 pids per session is
    one measured workload; an agent running a parallel build spends more. A
    refusal resting on that would turn a conservative estimate into a policy.

    Returns `None` when there is nothing to say -- no limit to read, or a
    `max_sessions` the container can carry.
    """
    if limit is None:
        return None
    carries = max(0, (limit - PIDS_BASELINE) // PIDS_PER_SESSION)
    if settings.max_sessions <= carries:
        return None
    return (
        f"AGENT_SERVICE_MAX_SESSIONS={settings.max_sessions} exceeds what this "
        f"container can spawn: its process limit is {limit} and a session costs "
        f"about {PIDS_PER_SESSION} processes, so roughly {carries} session(s) "
        "fit. Creating more will answer 503 "
        "'No capacity to start another session' rather than the 429 that "
        "max_sessions produces. Raise pids_limit, or lower "
        "AGENT_SERVICE_MAX_SESSIONS to match."
    )
