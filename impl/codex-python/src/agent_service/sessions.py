"""One Codex conversation, and the turns taken on it.

This is the SDK-facing half of the implementation -- the part `impl/common/`
must never hold. Everything it decides is Codex-specific: how a thread is
started, how a turn streams, what a turn's outcome is.

## What it is NOT

**Not the session registry.** Caps, idle reaping and the service-side
`session_id` belong to the layer above; this owns one conversation and its
lifetime. Conflating the two is what made the Claude build's `sessions.py` 995
lines.

## The turn loop, and why `stream()` rather than `run()`

`AsyncTurnHandle` offers both, and `run()` is `stream()` collected -- so
`stream()` is the primitive and taking it costs nothing. It is also the only
one that can serve `/v1/sessions/{sid}/messages/stream`, where a caller wants
events as they happen rather than a final answer.

`turn/completed` is the terminating event. The SDK's own `run()` breaks on it
and so does this, rather than waiting for the stream to close: an app-server
that stays connected between turns would otherwise hang the request forever.
"""

from __future__ import annotations

from dataclasses import replace

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai_codex import AsyncCodex, CodexConfig, InvalidRequestError

from agent_service.config import api_key as config_api_key
from agent_service.config import base_url as config_base_url, endpoint_overrides
from agent_service.events import to_agent_event
from agent_service.approvals import (
    McpApprovalPolicy,
    install_approval_handler,
    start_thread_with_mcp_approvals,
)
from agent_service.options import (
    mcp_overrides,
    setting_source_overrides,
    thread_kwargs,
    turn_kwargs,
    unsupported,
)


class SessionCapacityExhausted(RuntimeError):
    """The container cannot spawn another app-server. A 503, per `errors.py`.

    **Not the same thing as `max_sessions`, and that is the whole point.** That
    cap is a number this service enforces; this is the container running out of
    process slots underneath it, and the two are set independently -- so a
    deployment can advertise a cap it cannot honour.

    Measured 2026-08-09 (CX-19): ~30
    pids and ~20 MiB per session, so `pids_limit: 512` carries about 16 while
    memory would allow far more. **Exceeding it produced a 500 titled
    "Unhandled error"** -- the unclassified case, which `errors.py` describes as
    the sign of a gap in its own table.

    **503 rather than 429.** A 429 would say the caller asked for too much,
    which is the `max_sessions` story; this says the deployment is out of room
    and the condition clears when somebody closes a session. Retryable, and not
    the caller's fault.
    """


class ResumeTargetNotFound(LookupError):
    """`options.resume` named a conversation this runtime cannot find. A 400.

    **Split out of `InvalidRequestError` on 2026-08-09** because the two mean
    different things to a caller and answered identically. The SDK raises that
    for a malformed request and for a resume target it cannot load, and
    `errors.py` mapped both to *Invalid request* with `detail:
    "InvalidRequestError"` -- so *the history is gone* was indistinguishable
    from *your body is wrong*, and only one of those is worth retrying with a
    different id.

    **A `LookupError` rather than a `ValueError`**, because that is what it is:
    the request is well formed and names something that is not there.

    Still a **400 and not a 404**: the resource being created is a session and
    the create is what failed, so a 404 would be a claim about
    `POST /v1/sessions` itself. `errors.py` gives it a named problem `type`
    instead, which is the part a client branches on.
    """


class RunTimeout(TimeoutError):
    """A turn outlived its `timeout_s` budget. A 504, per `errors.py`.

    **Defined here rather than in `errors.py`** for the reason that module's own
    `_service_problem` gives about the import cycle: this is where it is raised,
    and `errors.py` reaches for it lazily like the registry's exceptions.

    **A `TimeoutError` subclass on purpose.** `except TimeoutError` in a caller
    that does not know this service's vocabulary still catches it, and the SDK's
    own timeouts are the same base -- so nothing has to know which layer timed
    out to handle it as a timeout.

    **It carries the partial outcome, and that is not a convenience.** A turn
    abandoned on a deadline still happened: it has a duration, it consumed
    tokens, and the events collected before the deadline are the only record of
    what it did. Without them the registry has nothing to write to
    `SessionRecord.last_turn`, which would leave the *previous* turn standing
    there as the last one -- a timed-out turn reported as somebody else's
    success.
    """

    def __init__(self, message: str, outcome: TurnOutcome | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(slots=True)
class TurnOutcome:
    """What one turn produced. The shape the API layer needs, not the SDK's.

    Deliberately NOT the SDK's `TurnResult`: this build must be able to report a
    turn that ended without one -- an app-server that died mid-turn, a stream
    that stopped -- and a type that cannot express "no outcome" would force a
    lie. The Claude build calls the same idea `outcome_recorded`.
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    status: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    final_response: str | None = None

    #: **Always `None` for this build**, and that is measured rather than
    #: assumed: `grep -ri "usd|cost"` over `openai-codex` returns nothing but a
    #: false positive. 0.16.0 made `SessionRecord.total_cost_usd` nullable for
    #: exactly this, so reporting `None` is honest where `0.0` would read as
    #: free. See (CX-29).
    total_cost_usd: None = None

    #: Whether THIS SERVICE abandoned the turn on its `timeout_s` budget.
    #:
    #: **It has to live on the outcome and not only in the status code**, because
    #: a `SessionRecord` fetched later has no status code: the specification keeps
    #: `timed_out` on `TurnRecord` precisely so that a timeout stays
    #: distinguishable from every other `outcome_recorded: false` ending once the
    #: 504 is long gone.
    timed_out: bool = False


class CodexSession:
    """One thread, and the turns taken on it.

    Construction does NOT start anything -- `open()` does, because starting an
    app-server subprocess is the kind of thing a caller should be able to fail
    on explicitly rather than inside `__init__`.
    """

    def __init__(
        self,
        *,
        cwd: str | None = None,
        codex_home: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        #: The key to log in with, or `None` to read the environment at `open()`.
        #: Passing it explicitly is what tests do; production leaves it None and
        #: gets `config.api_key()`. See `open()` for why a login is needed at all.
        self._api_key = api_key
        env: dict[str, str] | None = None
        if codex_home is not None:
            # CODEX_HOME is where the app-server keeps its SQLite state, its
            # installation id and its unpacked skills -- 65 files on first
            # start. It is overridable, which is what lets a container mount it
            # and keep threads across a restart; Gemini has no equivalent.
            #
            # **IT MUST ALREADY EXIST.** The app-server does not create it: it
            # exits immediately with `CODEX_HOME points to "..." but that path
            # does not exist`, and the SDK surfaces that as a
            # `TransportClosedError` about stdout closing -- an error that says
            # nothing about the real cause. Measured 2026-08-07.
            #
            # So this service creates it. It chose the path, so it owns making
            # it usable; leaving that to a Dockerfile or a volume mount is how
            # it becomes a deployment's problem instead.
            # **ABSOLUTE, and that is the whole of this line** (CX-55). The
            # app-server is started with `cwd` set to the WORKSPACE, so it
            # resolves a relative `CODEX_HOME` against a directory that is not
            # the one this service just created -- and exits with the same
            # "path does not exist" as above. The default is `./codex-home`,
            # so every local run hit it; the container never did, because its
            # Dockerfile sets an absolute path.
            resolved = str(Path(codex_home).resolve())
            Path(resolved).mkdir(parents=True, exist_ok=True)
            env = {"CODEX_HOME": resolved}
        if cwd is not None:
            # Same reasoning: the workspace is ours to guarantee. The Claude
            # build's `workspace_dir` validator does the same thing.
            Path(cwd).mkdir(parents=True, exist_ok=True)
        self._config = CodexConfig(
            cwd=cwd, env=env, config_overrides=endpoint_overrides(base_url)
        )
        self._codex: AsyncCodex | None = None
        #: The MCP servers this session configured, and the policy that
        #: approves calls to them. Empty when the caller sent none, which
        #: is what keeps the private path unreached.
        self._mcp_servers: frozenset[str] = frozenset()
        self._approvals: McpApprovalPolicy | None = None
        self._thread: Any = None
        self._turn: Any = None

    @property
    def sdk_session_id(self) -> str | None:
        """The thread id -- a UUIDv7 -- or `None` before `open()`.

        This is the specification's `sdk_session_id`. Known at creation, unlike
        the Claude build where it arrives with the first turn's init message.
        """
        return getattr(self._thread, "id", None)

    async def open(self, options: Any, *, resume: str | None = None) -> None:
        """Start the app-server, authenticate it, and begin or resume a thread.

        **The login is not optional and not inherited from the environment.**
        Measured 2026-08-08: the app-server reads neither `OPENAI_API_KEY` nor
        `CODEX_API_KEY`, even though both are exported into its process. Without
        `login_api_key()` its account is `None` and every turn reaches the API
        with no `Authorization` header -- a `401 Missing bearer or basic
        authentication in header` that looks like a bad key and is not one.

        Logging in writes the key into the app-server's auth store under
        `CODEX_HOME`, so a container mounting that directory is already
        authenticated on the next start. Repeating it is a local write, not a
        network round trip, and is cheap enough not to be worth conditioning on.

        A key that the app-server rejects raises here rather than at the first
        turn, which is the difference between one clear failure and a session
        that exists but can never do anything.
        """
        # **MCP first, because it changes how the app-server must be STARTED.**
        # The servers are `--config` overrides on the binary and an HTTP
        # server's token is an environment variable, so both have to be in place
        # before the process exists -- see `options.mcp_overrides`.
        mcp_config, mcp_env = mcp_overrides(getattr(options, "mcp_servers", None))
        # Same channel, different subject: whether the thread reads the project
        # doc from its cwd. Measured, `spike/probe_project_doc.py`.
        mcp_config = (*setting_source_overrides(options), *mcp_config)
        self._mcp_servers = frozenset((getattr(options, "mcp_servers", None) or {}))
        if mcp_config or mcp_env:
            self._config = replace(
                self._config,
                config_overrides=(*self._config.config_overrides, *mcp_config),
                env={**(self._config.env or {}), **mcp_env},
            )

        self._codex = AsyncCodex(self._config)
        key = self._api_key if self._api_key is not None else config_api_key()
        try:
            if key is not None:
                await self._codex.login_api_key(key)
        except BlockingIOError as exc:
            # **The container ran out of process slots, not the service out of
            # session slots**, and until 2026-08-09 those were the same 500.
            #
            # Measured: each session costs ~30 pids and ~20 MiB, so against
            # `pids_limit: 512` the container carries about 16 -- while
            # `max_sessions` is a number an operator sets independently. Raise
            # it past what the container can spawn and the 16th create failed
            # with `500 "Unhandled error" / BlockingIOError`, which is
            # `UNCLASSIFIED_TITLE`: by `errors.py`'s own words, the sign that
            # the table has a gap.
            #
            # `BlockingIOError` is `EAGAIN` from the spawn. Caught HERE rather
            # than in the error table, so only a failure to start an app-server
            # is reclassified and an EAGAIN from anywhere else keeps its 500.
            raise SessionCapacityExhausted(
                "this container cannot start another agent process: it is at "
                "its pid limit. Each session costs roughly 30 processes, so a "
                "container's real capacity is `pids_limit / 30` regardless of "
                "`max_sessions`. Close a session and retry, or give the "
                "deployment a higher pids_limit."
            ) from exc

        if self._mcp_servers:
            # **The transport has to be up before the handler can be installed**,
            # and `login_api_key` above has already forced it. Doing it in the
            # other order would replace a handler on a client that has not been
            # constructed yet.
            await self._codex._ensure_initialized()
            self._approvals = McpApprovalPolicy(self._mcp_servers)
            install_approval_handler(self._codex, self._approvals)

        kwargs = thread_kwargs(options)
        if resume is not None:
            # A thread with no turns has NO ROLLOUT and cannot be resumed --
            # measured, and the same semantics as the Claude CLI's AS-27.
            # The error is never swallowed: a caller that asked to continue a
            # conversation must not silently get a fresh one.
            #
            # **It is TRANSLATED rather than propagated, though**, and the
            # difference is the whole of this branch. The SDK raises
            # `InvalidRequestError`, which `errors.py` maps to a 400 titled
            # *Invalid request* with `detail: "InvalidRequestError"` -- correct,
            # and indistinguishable from a malformed body. *No such
            # conversation* is a thing a caller acts on differently: it means
            # the history is gone, not that the request was wrong.
            #
            # Measured: destroy `CODEX_HOME` and a resume that worked a minute
            # earlier is that 400 (CX-18).
            try:
                self._thread = await self._codex.thread_resume(resume, **kwargs)
            except InvalidRequestError as exc:
                raise ResumeTargetNotFound(
                    f"no conversation {resume!r} to resume: this runtime keeps "
                    "its transcripts under CODEX_HOME, so an id is resumable "
                    "only while that volume holds the rollout -- and a "
                    "conversation that never took a turn has none. Create a new "
                    "session instead."
                ) from exc
        elif self._mcp_servers:
            # **The one place this build leaves the SDK's public API**, and only
            # when MCP is actually in play: a session without MCP servers takes
            # the ordinary path above and touches nothing private.
            #
            # `thread_start` derives `(approval_policy, approvals_reviewer)` from
            # a two-value enum that can only say "deny everything" or "let the
            # model review itself". An MCP tool call is an escalation, so the
            # first denies every one and the second is the defect
            # (CX-06) describes. `agent_service.approvals`
            # has the whole argument and the shape guard.
            self._thread = await start_thread_with_mcp_approvals(
                self._codex, kwargs
            )
        else:
            self._thread = await self._codex.thread_start(**kwargs)

    async def send(
        self, prompt: str, options: Any, *, timeout_s: float | None = None
    ) -> TurnOutcome:
        """Take one turn, collecting its events. Returns even on failure.

        **`timeout_s` is the turn's whole budget, taken as one deadline here.**
        It is enforced in this method rather than a layer up because this is
        where the turn handle lives: a deadline that expires must *stop the
        turn*, and the caller above has no handle to stop it with. Without the
        interrupt the app-server would go on spending tokens on a turn nobody
        is waiting for, and `turn_lock` would already be free for the next one --
        two turns live on one conversation, which is the state this service
        exists to prevent.

        `None` means no deadline, which is what the pre-2026-08-08 behaviour was
        for every turn (CX-11). Nothing in the service
        passes `None` today; it stays available because a probe taking one
        deliberately unbounded turn is a reasonable thing to write.
        """
        if self._thread is None:  # pragma: no cover - guarded by the API layer
            raise RuntimeError("session is not open")

        outcome = TurnOutcome()
        self._turn = await self._thread.turn(prompt, **turn_kwargs(options))
        include_raw = getattr(options, "include_raw", None) is not False

        # **The turn's result is assembled from the STREAM, not from the
        # terminal event.** `turn/completed` carries a `Turn`, and a `Turn` has
        # only id/status/error/timestamps/items -- no `final_response` and no
        # `usage` (read from the installed SDK, 2026-08-08). This code read them
        # off the terminal payload until then and therefore reported `None` for
        # both, always. The SDK's own `_collect_turn_result` does what is done
        # here: accumulate completed items, keep the last token-usage update,
        # and derive the final answer from the items.
        items: list[Any] = []
        seq = 0
        turn = self._turn
        try:
            # `asyncio.timeout(None)` is a no-op context, so the unbounded case
            # needs no second code path.
            async with asyncio.timeout(timeout_s):
                async for notification in turn.stream():
                    method = getattr(notification, "method", None)
                    payload = getattr(notification, "payload", None)
                    if method == "item/completed":
                        item = getattr(payload, "item", None)
                        if item is not None:
                            items.append(item)
                    elif method == "thread/tokenUsage/updated":
                        outcome.usage = _dump(getattr(payload, "token_usage", None))
                    outcome.events.append(
                        to_agent_event(notification, seq, include_raw=include_raw)
                    )
                    seq += 1
                    if method == "turn/completed":
                        _absorb_turn(outcome, notification)
                        break
        except TimeoutError as exc:
            # **Stop the turn before reporting the timeout.** See the docstring:
            # the alternative is an abandoned turn still spending, on a session
            # whose lock is about to be released.
            #
            # Suppressed because the interrupt is a courtesy on a path that has
            # already failed -- a runtime too wedged to accept it must still
            # produce the 504, not a 502 about the interrupt.
            with contextlib.suppress(Exception):
                await turn.interrupt()
            # The partial outcome travels with the exception. `status` stays None
            # -- no `turn/completed` arrived -- so `outcome_recorded` is false and
            # `timed_out` is what says why.
            outcome.timed_out = True
            outcome.final_response = _final_answer(items)
            raise RunTimeout(f"turn exceeded {timeout_s:g}s", outcome) from exc
        except asyncio.CancelledError:
            # **The consumer went away mid-turn** (CX-54) -- a closed browser
            # tab, a dropped relay, a client that gave up. Same consequence the
            # timeout branch above exists to prevent and it was wired for only
            # that trigger: without an interrupt the app-server goes on spending
            # tokens on a turn nobody is waiting for, and the `finally` below
            # then clears the handle, so nothing can ever stop it afterwards.
            #
            # **Shielded, because the interrupt is being sent FROM the
            # cancellation it is reacting to.** A plain `await` here is
            # cancelled again before the request leaves; the shield lets the
            # inner task run to completion while this frame gives up waiting
            # for it. Suppressed for the same reason as the timeout branch --
            # a runtime too wedged to accept the interrupt must not turn a
            # disconnect into an error nobody will read.
            stopping = asyncio.ensure_future(turn.interrupt())
            with contextlib.suppress(BaseException):
                await asyncio.shield(stopping)
            raise
        finally:
            self._turn = None
        outcome.final_response = _final_answer(items)
        return outcome

    async def interrupt(self) -> bool:
        """Ask the running turn to stop. `False` when there is nothing to stop.

        `TurnHandle.interrupt()` is the SDK's own, so this needs no polling or
        cancellation of our own -- which is the half the Claude build had to
        build by hand.
        """
        turn = self._turn
        if turn is None:
            return False
        await turn.interrupt()
        return True

    async def close(self) -> None:
        """Stop the app-server subprocess. Safe to call twice."""
        codex, self._codex, self._thread, self._turn = self._codex, None, None, None
        if codex is not None:
            await codex.close()

    async def __aenter__(self) -> CodexSession:  # pragma: no cover - convenience
        return self

    async def __aexit__(self, *_exc: object) -> None:  # pragma: no cover
        await self.close()


def _dump(model: Any) -> dict[str, Any] | None:
    """A pydantic model as a JSON-safe dict, or `None`. Never raises.

    A turn whose usage this build could not read is still a turn; losing it
    would be worse than reporting it thinly.
    """
    dump = getattr(model, "model_dump", None)
    if not callable(dump):
        return None
    try:
        return dump(mode="json")
    except Exception:  # noqa: BLE001 - see the docstring
        return None


def _final_answer(items: list[Any]) -> str | None:
    """The agent's final answer, from the turn's completed items.

    **Matched on the payload's own `type` discriminator, not on a class
    import.** `AgentMessageThreadItem` and `MessagePhase` live only in
    `openai_codex.generated.v2_all` -- the SDK's public `types` module does not
    re-export them -- and importing from a generated module is a dependency on
    something explicitly not part of the API. The discriminator strings are the
    wire format, which is the more stable thing to match on.

    The rule mirrors the SDK's `_run.py`: the LAST `final_answer` message wins;
    failing that, the last message with no phase at all. Commentary is never the
    answer, which is why "last message" alone would be wrong.
    """
    fallback: str | None = None
    for item in reversed(items):
        inner = getattr(item, "root", item)
        if getattr(inner, "type", None) != "agentMessage":
            continue
        phase = getattr(inner, "phase", None)
        phase = getattr(phase, "value", phase)
        if phase == "final_answer":
            return getattr(inner, "text", None)
        if phase is None and fallback is None:
            fallback = getattr(inner, "text", None)
    return fallback


def _absorb_turn(outcome: TurnOutcome, notification: Any) -> None:
    """Read a `turn/completed` payload into the outcome. Never raises.

    A turn that completed but whose payload this build could not read is still a
    completed turn -- losing it would be worse than reporting it thinly.
    """
    turn = getattr(getattr(notification, "payload", None), "turn", None)
    if turn is None:
        return
    status = getattr(turn, "status", None)
    outcome.status = getattr(status, "value", status)
    outcome.duration_ms = getattr(turn, "duration_ms", None)
    error = getattr(turn, "error", None)
    if error is not None:
        outcome.error = str(getattr(error, "message", error))
    # **NO usage here.** `Turn` has no such field -- id, status, error,
    # timestamps, items and nothing else. Usage arrives on
    # `thread/tokenUsage/updated` during the stream and is collected in
    # `send()`. Reading it here was a bug that reported `None` on every turn.
