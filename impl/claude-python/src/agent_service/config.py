"""Service configuration. The single source of truth for every default."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The built-in tools this service grants by default. NOT the full set the CLI
# advertises (31 tools were observed in a live init payload) -- `allowed_tools`
# governs permission, not visibility, so the model may still attempt others and
# be denied (CP-066).
DEFAULT_ALLOWED_TOOLS: list[str] = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]

# Enforced on every request and never overridable. There is no human to answer
# AskUserQuestion over HTTP; allowing it hangs the request until timeout.
ALWAYS_DISALLOWED_TOOLS: list[str] = ["AskUserQuestion"]

# --- the credential specification, published by GET /v1/capabilities -------------
#
# THE TWO LISTS ARE SEPARATE BECAUSE THEY ARE DIFFERENT THINGS, and conflating
# them is not cosmetic. `credentials_configured()` is satisfied by any of the
# five names below, so a caller told only "these five are accepted" can inject
# `CLAUDE_CODE_USE_BEDROCK=1`, pass the boot gate, and still have a container
# that cannot authenticate -- the same class of failure, one variable along,
# that publishing this is meant to end (CP-134,
# request 1, from a caller who built a whole delivery mechanism around an
# `ANTHROPIC_API_KEY_FILE` that does not exist).
#
# `credentials_configured()` below is written to CONSULT these lists rather
# than repeat them, so what is published cannot drift from what is checked.
# Pinned by tests/test_config.py::test_the_published_credential_specification_is_
# the_one_the_gate_checks.
#
# SCOPE, stated because the field's usefulness depends on it: this is what THIS
# SERVICE's boot gate accepts, which is not measured to be what the bundled CLI
# can authenticate with. The gate is a presence check on environment variables;
# a credential the CLI would accept by some other route (an OAuth token, a
# mounted credentials file) still fails this check and still refuses the boot.
CREDENTIAL_ENV_VARS: list[str] = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
]

# The variable that moves this build's model endpoint, published as
# `endpoint_source` in the document's PrebootSpec component (0.19.0).
#
# **Read by the CLI from the ambient environment, not by this service.** That is
# a real difference from the Codex build, where no variable reaches the
# app-server at all and the service translates one itself: here anything that
# can set an environment variable in this container can move the endpoint, which
# makes this build the *less* predictable of the two on exactly this point.
#
# Measured, not assumed -- turns have been run against a redirected host and
# against a black-hole listener inside the container.
#: **The agent target this build drives** (user, 2026-08-16; CP-146).
#: `claude`, not `anthropic`: this names the FAMILY, and the implementation
#: suffix is deliberately not in it. `impl.name` is `claude-python` and carries the
#: language; a second build of the same target in another language would
#: publish the same `claude` here and a different `impl.name` there, which is
#: why this is not a restatement of that field.
#:
#: **The consumer maps it to a vendor API themselves** -- `claude` -> the
#: Anthropic API. That mapping was offered to us as this field's value and
#: the user chose the family name instead; CP-146 carries the decision and what
#: was traded for it.
MODEL_API = "claude"

ENDPOINT_ENV_VAR = "ANTHROPIC_BASE_URL"

# The variable this build reads an ADDITIONAL certificate authority from,
# published as `ca_bundle_source` (CP-144). Measured, and the measurement is the
# whole value of the field: nothing on this image's surface reveals it. There is
# no `node` on the PATH and no `node_modules` -- the runtime is compiled into the
# bundled executable, which carries four plausible variable names and honours
# two of them.
#
# **`replaces_default_trust` is false here and TRUE on the Codex build**, which
# is the fact a deployment cannot afford to guess: this build reaches a public
# host and a privately-signed one at once, and that one cannot.
#
# `NODE_EXTRA_CA_CERTS` is honoured identically and is not published. One name
# is what a consumer can act on; two invite a choice with no basis for making it.
CA_BUNDLE_SOURCE: dict[str, object] | None = {
    "variable": "SSL_CERT_FILE",
    "shape": "file",
    "replaces_default_trust": False,
}

# Selectors, NOT credentials. Setting one tells the CLI which provider to talk
# to; the credential itself then comes from that provider's own chain (AWS,
# GCP, Azure), which this service does not inspect and cannot report on.
PROVIDER_SELECTOR_ENV_VARS: list[str] = [
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
]

# --- the listen specification, published in the document --------------------
#
# NOT `Settings` fields, and that is the whole point of them being here as
# constants. Nothing in this process chooses the bind address or the port --
# the image's `CMD` does, and it passes them to uvicorn before any of this code
# runs. So these do not configure anything; they REPORT what the image's own
# command was written to do, for a caller that has to decide how to reach a
# container before it has started one.
#
# WHY A CONSTANT AND NOT A LOOKUP, which is exactly `db/revision.py`'s
# `EXPECTED_REVISION` problem and takes the same answer: the container does not
# ship its own Dockerfile, so there is nothing at run time to read. The value
# is therefore only as true as the test that pins it against the `CMD` in the
# source tree, which makes
# `tests/test_config.py::test_the_published_listen_specification_is_the_image_command`
# part of this feature rather than a check on it. That test parses BOTH the
# `--host`/`--port` arguments and the `EXPOSE` line, because a `CMD` and an
# `EXPOSE` that disagree is its own quiet failure.
#
# SCOPE, stated because a published value that is wrong is worse than none:
# this describes THE IMAGE'S DEFAULT COMMAND. A `docker create` that overrides
# the command, or a hand-run `uvicorn --host 127.0.0.1 --port 9000` on a
# checkout, listens where it was told and this constant is then a statement
# about a command nobody ran. That is why it is published by the module a
# caller runs AGAINST AN IMAGE (`docker run --rm <image> python -m
# agent_service.spec`) rather than served by the running app, where it
# could contradict the socket the caller had already connected to.
#
# 0.0.0.0 IS ALL IPv4 INTERFACES AND NOTHING ELSE. Measured on the running
# container: `/proc/net/tcp` carries one listening socket, `00000000:1F40`, and
# `/proc/net/tcp6` is empty. Consumers routing to this container by DNS on a
# user-defined Docker network must not enable IPv6 on it -- an `AAAA` answer
# leads to a port nothing is bound to, which presents as the container being
# down. Binding `::` instead was considered and rejected: it is dual-stack
# where IPv6 exists and an outright bind failure where it is disabled, which
# trades a failure the network's creator controls for one they do not.
LISTEN_ADDRESS = "0.0.0.0"

# Above 1024 ON PURPOSE. A privileged port would need CAP_NET_BIND_SERVICE, and
# this image is measured to run with `--cap-drop ALL` -- `compose.yaml` ships
# exactly that. The port is what keeps that true.
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



class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_SERVICE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- workspace -------------------------------------------------------
    workspace_dir: Path = Path("./workspace")
    reference_dirs: list[Path] = Field(default_factory=list)

    # Refuse to boot when the directories above are not actually mounted.
    #
    # DEFAULT TRUE (Q14, user decision 2026-07-31 -- it shipped `False` first).
    # The guard is only useful where the mounts are meant to exist, and the
    # deployment that most needs it is the one least likely to remember a flag:
    # a hand-rolled `docker run` gets no checking at all when this defaults off.
    # So the container gets it for free and the non-container run opts out.
    #
    # DELIBERATELY NOT AUTO-DETECTED. Keying this off `/.dockerenv` or
    # `/proc/1/cgroup` would spare a plain checkout the opt-out, but detection
    # that fails in a real container turns the guard silently off -- which is
    # precisely the class of failure `verify_mounts` exists to remove. An
    # explicit flag cannot fail silently.
    #
    # THE COST, stated plainly: `uv run uvicorn ...` on a checkout now refuses
    # to boot until you set `AGENT_SERVICE_REQUIRE_MOUNTS=false`, because
    # `./workspace` is an ordinary directory. `.env.example` carries it.
    # See `verify_mounts` for what "actually mounted" means.
    require_mounts: bool = True

    # --- agent defaults --------------------------------------------------
    default_model: str = "claude-sonnet-5"
    default_permission_mode: str = "dontAsk"
    default_allowed_tools: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS)
    )
    default_setting_sources: list[str] = Field(default_factory=list)

    # --- provenance (0.9.0) ----------------------------------------------
    # THE ONE SETTING WITHOUT THE `AGENT_SERVICE_` PREFIX, and deliberately.
    # `AGENT_ID` is not this service's variable: Agent Studio injects it on
    # every container it starts and has done since its D-10, so the name is
    # fixed by the party that sets it. Prefixing would mean asking a consumer
    # to inject a second variable carrying the value it already injects.
    #
    # There is precedent one line of reasoning away: `ANTHROPIC_API_KEY` is
    # read unprefixed for exactly the same reason -- it belongs to someone
    # else's namespace. `validation_alias` is what bypasses `env_prefix`;
    # `AGENT_SERVICE_AGENT_ID` is deliberately NOT also accepted, because two
    # names for one value is the ambiguity `sdk_session_id` exists to prevent.
    #
    # Opaque, and it stays opaque: no parsing, no normalisation, no format
    # assumed, and no refusal of a value this service does not recognise.
    # Absent is a NORMAL deployment -- a container run by hand is not
    # misconfigured -- so there is no boot gate and no warning that implies
    # one (CP-135).
    agent_id: str | None = Field(default=None, validation_alias="AGENT_ID")
    include_workspace_description: bool = True
    include_raw_events: bool = True

    # --- authentication (0.11.0) -------------------------------------------
    # Q6, deferred since 2026-07-31 and answered by a consumer rather than by
    # this side. CP-133 is the threat model; three things from it shape
    # what this is:
    #
    #   1. Authentication is THIRD. Network isolation and a relay in front of
    #      it remove more risk, and both are the consumer's work. This does not
    #      pretend otherwise.
    #   2. It answers "is the caller Studio", NOT "which user is calling".
    #      Studio asked for that explicitly -- it resolves the owner from the
    #      Agent, so a per-request caller claim would be a second, weaker
    #      source of truth.
    #   3. A token this service holds is READABLE BY ITS OWN AGENT (M2, and
    #      config's own note about ANTHROPIC_API_KEY). So it must be
    #      PER-INSTANCE and must grant access to nothing but this instance. A
    #      token shared across a fleet is ruled out by construction, not by
    #      policy: any user who can take one turn reads it.
    #
    # OFF BY DEFAULT, and that is not laziness. The deployment this service
    # documents -- one operator, loopback, `docker compose up` -- has no second
    # party to authenticate (CP-133).
    # Turning it on by default would break every such deployment to protect
    # against nobody. What replaces the default is VISIBILITY: when unset, boot
    # logs a warning and `/healthz` and `/v1/capabilities` both publish
    # `auth_required: false`, so a caller can tell rather than assume.
    auth_token: str | None = Field(default=None, repr=False)

    # The symmetric gate to require_credentials and require_mounts: refuse to
    # BOOT when auth is not configured. For an operator who needs "this
    # container is authenticated" to be a fact rather than a hope -- the same
    # reason those two exist. Default false, so nothing changes for anyone who
    # has not asked.
    require_auth: bool = False

    # --- MCP servers (0.8.0) ----------------------------------------------
    # TRUE by default, and that is a considered choice rather than an
    # oversight. A stdio MCP server is a subprocess spawn, which LOOKS like
    # the most dangerous thing a caller can ask for -- and grants nothing the
    # caller does not already have: `Bash` is enabled with
    # permission_enforcement="none", so "send a prompt that runs a command" is
    # always available. Defaulting this to false would block a legitimate
    # feature and reduce no capability.
    #
    # The switch exists anyway because ONE thing does change: attribution. A
    # `Bash` command is the agent's decision and lands in the transcript; a
    # stdio server starts with the session, before any prompt, and appears in
    # no turn's events. An operator who needs every process start to be
    # attributable to a turn has no other way to get it, so they get this.
    #
    # Published as `Capabilities.allow_mcp_servers` for the same reason
    # require_credentials and require_mounts are: a caller that provisions
    # containers should be able to ask, rather than discover it from a 400.
    allow_mcp_servers: bool = True
    # Not the SDK's default (false). See `RunOptions.strict_mcp_config` for
    # why: the workspace is agent-writable, so CLI-side discovery can add
    # servers the caller never sent and cannot see in its own request.
    default_strict_mcp_config: bool = True

    # --- permission enforcement -------------------------------------------
    # "none" (the default): no in-process write-confinement control is wired
    # up at all. The container and its read-only/read-write mount split
    # (CP-081) are the only boundary. This is not a weaker
    # posture than the alternatives below pretend to be -- it is the only
    # one actually measured to hold (CP-066, "Permission
    # enforcement -- measured, not guessed": five live probes
    # (spike/probe_permissions.py) found that `can_use_tool` never fires at
    # all under this service's tool configuration (a whole-tool
    # `allowed_tools` grant shadows it when the tool is allowed, and the CLI
    # denies outright without consulting it when the tool is not allowed) --
    # so it is not offered as a mode here, only "hook" is. "hook" attaches a
    # `PreToolUse` hook (policy.py's `make_permission_hook`) that was
    # confirmed live to fire despite the whole-tool grant and to genuinely
    # block a write outside the workspace, recorded in
    # `ResultMessage.permission_denials`. Both non-"none" values are opt-in:
    # we do not ship an in-process control by default that a container
    # already makes redundant when present and that (for `can_use_tool`)
    # cannot be demonstrated to run at all.
    permission_enforcement: Literal["none", "hook"] = "none"

    # --- limits: default applied when unset, cap a request may not exceed -
    default_max_turns: int = 30
    max_allowed_turns: int = 200
    default_max_budget_usd: float = 2.0
    max_allowed_budget_usd: float = 10.0
    default_request_timeout_s: int = 600
    max_allowed_timeout_s: int = 1800

    # --- logging ----------------------------------------------------------
    # The level applied to the ROOT logger by `main.configure_logging`, which
    # runs at the entrypoint and nowhere else (see main.py for why not in
    # create_app).
    #
    # INFO by default because the two most operationally useful lines this
    # service emits are both INFO -- the reaper's "closed N idle session(s)"
    # and close_all()'s shutdown summary -- and Task 6 measured BOTH being
    # discarded in the container: nothing configured logging at all, so
    # Python's last-resort handler emitted WARNING and above and dropped the
    # rest. Raising this to WARNING silences the service's own reporting again;
    # lowering it to DEBUG turns on the SDK's and anyio's debug output too,
    # which is verbose and is NOT audited for what it prints.
    log_level: str = "INFO"

    # --- startup ----------------------------------------------------------
    # Refuse to boot when no Anthropic credential is configured (follow-up
    # item 8, user decision 2026-07-27). See `verify_credentials` below for
    # what this costs and why it is still the right default.
    #
    # A `Settings` FIELD rather than an ad-hoc environment read, so it is
    # discoverable in the same place as every other default (this module's
    # docstring calls itself the single source of truth for them), overridable
    # by the same `AGENT_SERVICE_` convention, and settable directly in a test
    # fixture -- which makes "this test deliberately boots without
    # credentials" visible at the fixture rather than implied by a global
    # monkeypatch nobody can see from the test body.
    require_credentials: bool = True

    # --- sessions (Plan 2) -----------------------------------------------
    # Each session holds one ClaudeSDKClient, i.e. one CLI subprocess, so the
    # cap is a real resource bound rather than a nicety.
    max_sessions: int = 8
    session_idle_ttl_s: int = 1800
    session_reaper_interval_s: int = 60

    # --- shutdown (Plan 4 follow-up) --------------------------------------
    # THE AGGREGATE BOUND ON `SessionRegistry.close_all()`, and therefore on
    # the whole ASGI lifespan shutdown. Read this together with compose.yaml's
    # `stop_grace_period`, which is DERIVED from it:
    #
    #   stop_grace_period >= --timeout-graceful-shutdown (30s, Dockerfile CMD)
    #                        + shutdown_budget_s
    #                        + margin
    #
    # 100s = 30 + 60 + 10. `test_the_compose_grace_period_follows_the_shutdown
    # _budget` reads both files and fails if that relationship stops holding,
    # so neither number can be changed without seeing the other.
    #
    # Why 60s and not less: each close is given a FAIR SHARE of the budget, so
    # a full house of `max_sessions` (8) gets (60 - 5s kill reserve) / 8 =
    # 6.9s each -- above the 5.4-5.9s a session wedged mid-turn was measured to
    # need (CP-088). Below ~48s the eighth wedged session would be
    # killed rather than closed cleanly, which is survivable but worse.
    #
    # Why a budget at all: `AgentSession.close()` is bounded only by its own
    # `timeout_s` (600s default, 1800s cap), so a sequential unbounded sweep of
    # 8 sessions was worth up to 80 minutes of shutdown. Measured against the
    # unbounded code with the per-session cost the container showed: 47.3s at
    # 8 x 5.9s, and forever with a genuinely hung close.
    shutdown_budget_s: float = 60.0

    # --- persistence -----------------------------------------------------
    # UNSET IS A SUPPORTED CONFIGURATION, not a degraded one. With no URL the
    # service runs fully with a NullRecorder: no rows, no engine, and
    # `agent_service.db` is never imported. A database must not become a hard
    # dependency for a service whose job is running an agent -- plan-03 states
    # this as a global constraint and every task keeps the path green.
    #
    # `postgresql://` and `postgres://` are accepted and rewritten to the
    # asyncpg driver by `db.engine.normalize_url`; anything else is rejected
    # loudly rather than silently selecting a sync driver inside the loop.
    database_url: str | None = None

    # Bound on ONE `SessionStore.load()` during resume materialization. The SDK
    # defaults this to 60s; 30s is chosen because `load()` runs in the parent
    # BEFORE the subprocess is spawned, inside `registry.create()`'s own 30s
    # open timeout -- a longer bound here could never fire, because the outer
    # one would win first and report the wrong cause.
    #
    # CORRECTION (plan-03 Task 7 follow-up). An earlier version of this comment
    # said a slow load "degrades to a fresh conversation". IT DOES NOT.
    # `_internal/session_resume.py`'s `materialize_resume_session` documents
    # "Raises ``RuntimeError`` if a store call fails or times out", and
    # `_with_timeout` re-raises the `TimeoutError` as a `RuntimeError` -- so a
    # slow store fails `open()`, which fails `registry.create()`, and the caller
    # gets an error rather than a session.
    #
    # That is arguably the right behaviour: silently starting a FRESH
    # conversation for someone who asked to continue one would lose their
    # context without saying so. But the wrong claim is recorded rather than
    # quietly replaced, because it changes what this timeout is for -- it bounds
    # how long a create() can hang, not how long it tries before giving up
    # gracefully. Pinned by
    # tests/test_resume.py::test_a_slow_store_fails_the_resume_rather_than_starting_fresh
    session_store_load_timeout_ms: int = 30_000

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        """Accept `debug` as readily as `DEBUG`, and name the valid set.

        `logging` matches level names case-SENSITIVELY, so an unnormalised
        `AGENT_SERVICE_LOG_LEVEL=info` would abort the boot with
        `ValueError: Unknown level: 'info'` from inside basicConfig -- a
        confusing place for a configuration typo to surface.
        """
        name = value.strip().upper()
        if name not in logging.getLevelNamesMapping():
            valid = ", ".join(
                n for n in logging.getLevelNamesMapping() if n != "NOTSET"
            )
            raise ValueError(f"unknown log level {value!r}; expected one of: {valid}")
        return name

    @field_validator("workspace_dir")
    @classmethod
    def _resolve_and_create(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @field_validator("reference_dirs")
    @classmethod
    def _resolve_references(cls, value: list[Path]) -> list[Path]:
        return [p.expanduser().resolve() for p in value]


def credentials_configured() -> bool:
    """True when the SDK will be able to authenticate.

    ANTHROPIC_API_KEY must remain in the environment -- the agent subprocess
    uses it -- so this is a presence check, not a secret we can hide (F2).

    READS THE TWO PUBLISHED LISTS rather than naming the variables inline. It
    used to name them, and `GET /v1/capabilities` now exports them: two copies
    of the same set, one of which a caller provisions containers against, is a
    drift waiting to happen. Behaviour is unchanged -- the same five names, in
    the same order.
    """
    return any(
        os.environ.get(name)
        for name in (*CREDENTIAL_ENV_VARS, *PROVIDER_SELECTOR_ENV_VARS)
    )


class MissingCredentials(RuntimeError):
    """No Anthropic credential is configured and the service refuses to boot.

    Raised from the FastAPI lifespan's startup, which is what makes an ASGI
    server abort: uvicorn's `Server.startup()` reads the failed lifespan and
    calls `sys.exit(STARTUP_FAILURE)`, so the process exits non-zero and a
    container restarts rather than sitting there serving requests it cannot
    fulfil. Deliberately NOT classified in `errors.py`: it can only be raised
    at boot, never during a request, so a problem-document mapping would be
    dead code claiming a status this can never produce.
    """


def verify_credentials(settings: Settings) -> None:
    """Refuse to boot without credentials (follow-up item 8). Returns or raises.

    User decision, 2026-07-27. Before this, the lifespan booted cleanly with
    every credential variable cleared and `credentials_configured()` was read
    by `GET /healthz` and nowhere else -- so an operator who forgot the key got
    up to `max_sessions` (8) sessions, each spawning a CLI subprocess that
    could not authenticate and each holding its cap slot until the reaper swept
    it at `session_idle_ttl_s` (1800s). The failure surfaced on the first turn
    of the ninth request rather than at boot.

    THE ACCEPTED COST, stated plainly because it is real: a credential blip at
    the wrong moment turns a restart into a crash-loop, and the service can no
    longer be started for docs-only use (`/docs`, `/openapi.json`,
    `/v1/capabilities`) without `require_credentials=false`. That is the trade
    the decision makes -- an operator finding out immediately is worth more
    than a service that starts and cannot work.

    This gates BOOT ONLY. It is deliberately not re-checked per request:
    `/healthz` already reports `credentials_configured` live, and re-checking
    at request time would turn a transient blip into an outage on the very
    route whose job is to describe one.

    The message names what to set AND the escape hatch, and it reads no
    credential VALUE -- `credentials_configured()` is a presence check, so
    there is nothing here that could echo a secret into a log.
    """
    if not settings.require_credentials or credentials_configured():
        return
    raise MissingCredentials(
        "No Anthropic credentials are configured, so this service refuses to "
        "start: every session would spawn an agent subprocess that cannot "
        "authenticate and would hold one of the "
        f"{settings.max_sessions} session slots until the idle reaper swept "
        f"it {settings.session_idle_ttl_s}s later. "
        "Set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN), or select a cloud "
        "provider with CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX or "
        "CLAUDE_CODE_USE_FOUNDRY. NOTE: a .env file is found by walking up "
        "from main.py's own directory, NOT the process working directory, so "
        "an installed or containerised deployment must pass these as real "
        "environment variables. To start anyway -- for docs-only use, or a "
        "test harness -- set AGENT_SERVICE_REQUIRE_CREDENTIALS=false."
    )


class MissingMounts(RuntimeError):
    """A required directory is not mounted and the service refuses to boot.

    Same mechanism and the same reasoning as `MissingCredentials`: raised from
    the lifespan's startup so uvicorn calls `sys.exit(STARTUP_FAILURE)`, and
    deliberately not classified in `errors.py` because it can only be raised at
    boot.
    """


def _mounted_under(path: Path) -> bool:
    """True if `path` or an ancestor below `/` is a mount point.

    NOT `path.exists()`, and not `os.path.ismount(path)` alone.

    `exists()` cannot answer the question: the `workspace_dir` validator calls
    `mkdir(parents=True, exist_ok=True)`, so a missing `-v` leaves an empty
    directory that exists and is not the host's. Measured: with a bind mount at
    `/workspace` the path appears in `/proc/self/mountinfo`; with the directory
    merely created by this process it does not.

    Bare `ismount(path)` is too strict, because pointing `workspace_dir` at a
    SUBDIRECTORY of a mount is a legitimate layout (`-v host:/data` with
    `AGENT_SERVICE_WORKSPACE_DIR=/data/ws`). So this walks up. `/` is excluded
    deliberately: a container's root is itself a mount, which would make the
    check pass for every path and quietly do nothing.
    """
    current = path.resolve()
    root = Path(current.anchor)
    while current != root:
        if os.path.ismount(current):
            return True
        current = current.parent
    return False


def verify_auth(settings: Settings) -> None:
    """Refuse to boot when `require_auth` is set and no token is configured.

    The third boot gate, and written to behave exactly like the other two:
    raises, so the lifespan aborts and uvicorn exits 3; names what to set; and
    is OFF by default so it only ever fires for an operator who asked for it.

    Why it exists at all, given the token is optional: "authentication is on"
    should be checkable as a fact rather than inferred from an environment
    variable someone believes they set. That is the same argument that produced
    `require_credentials` and `require_mounts`, and the same failure it avoids
    -- a container that starts, looks healthy, and is not what its operator
    thinks it is.
    """
    if settings.require_auth and not settings.auth_token:
        raise RuntimeError(
            "AGENT_SERVICE_REQUIRE_AUTH is set but AGENT_SERVICE_AUTH_TOKEN is "
            "empty, so this service would serve /v1 to anyone who can reach it. "
            "Set a per-instance token, or unset AGENT_SERVICE_REQUIRE_AUTH to "
            "run without authentication deliberately."
        )


def verify_mounts(settings: Settings) -> None:
    """Refuse to boot when a configured directory is not really there.

    Returns or raises. Gates BOOT ONLY, exactly like `verify_credentials`.

    THE FAILURE THIS EXISTS FOR is silent, which is why it is worth a boot
    check rather than a log line. Two shapes, both measured:

    * **A missing `-v ...:/workspace`.** The `workspace_dir` validator creates
      the directory, so the service starts, reports healthy, and the agent sees
      an empty workspace whose writes vanish with the container.
    * **A reference mount whose target and `AGENT_SERVICE_REFERENCE_DIRS` entry
      disagree.** `reference_dirs` is only resolved, never checked, so the path
      is accepted and is then invisible to Read/Glob/Grep while `docker exec
      ls` shows the files at the real path.

    Neither Docker nor compose will catch these for you: on Docker Desktop for
    Windows `-v`, `--mount type=bind` and compose's `create_host_path: false`
    were all measured to create a missing host directory and start anyway.

    The two directories are checked differently, on purpose. `workspace_dir`
    must be under a real mount (see `_mounted_under`) because "it exists" is
    exactly the state the bug produces. A reference directory is only required
    to EXIST -- it is never created by this service, so existence already
    separates a good config from a typo, and demanding a mount point would
    reject the legitimate case of naming a subdirectory of one.
    """
    if not settings.require_mounts:
        return

    problems: list[str] = []
    if not _mounted_under(settings.workspace_dir):
        problems.append(
            f"AGENT_SERVICE_WORKSPACE_DIR={settings.workspace_dir} is not on a "
            "mounted filesystem. It exists only because this service created "
            "it, so anything the agent writes there is discarded when the "
            "container stops. Mount it: -v /host/path:/workspace"
        )
    for ref in settings.reference_dirs:
        if not ref.exists():
            problems.append(
                f"AGENT_SERVICE_REFERENCE_DIRS entry {ref} does not exist. The "
                "mount target and this value must name the same path, or the "
                "directory is invisible to the agent while `docker exec ls` "
                f"still shows the files. Mount it: -v /host/repo:{ref}:ro"
            )
    if not problems:
        return
    raise MissingMounts(
        "This service refuses to start because "
        f"{'a required directory is' if len(problems) == 1 else 'required directories are'} "
        "not mounted:\n  - " + "\n  - ".join(problems) + "\n"
        "To start anyway -- for a docs-only boot, or a test harness -- set "
        "AGENT_SERVICE_REQUIRE_MOUNTS=false."
    )


# Read once, then REMOVED from the environment. See `get_settings`.
_SECRET_ENV_VARS = ("AGENT_SERVICE_DATABASE_URL",)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, with the database credential taken out of the
    environment on the way past.

    THIS POP IS A SECURITY REQUIREMENT, not tidiness, and CP-130
    §"The credential-leak interaction" states it as a hard requirement in this
    module rather than a hardening option.

    The agent's subprocess **inherits this process's entire environment** --
    verified against the SDK source, which builds `process_env` as
    `{**inherited_env, ...}` from `os.environ`. With `Bash` enabled, `env` is
    one tool call away, so any secret left here is readable by the agent and
    therefore by anything that can influence its prompt. After this call the
    connection string lives only in the settings object, in process memory.

    `ClaudeAgentOptions.env` CANNOT substitute for this: it is merged ON TOP OF
    the inherited environment, so it adds and overrides but never removes. That
    mitigation was proposed before the spike and is withdrawn in the doc.

    WHAT THIS DOES NOT PROTECT. `ANTHROPIC_API_KEY` must stay -- the subprocess
    authenticates with it -- so it is always readable by the agent. And none of
    this is watertight while `Bash` is enabled: the honest framing is that the
    agent is inside the trust boundary of this process, so the database must be
    scoped as reachable by it. The point of the pop is that a leak yields the
    read-only agent role, not the read-write service role.

    Called once (lru_cache) at startup by `main.py`, before any session exists.
    """
    settings = Settings()
    for name in _SECRET_ENV_VARS:
        os.environ.pop(name, None)
    return settings
