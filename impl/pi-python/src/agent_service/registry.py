"""Sessions: what this service holds between turns.

**A session is not a live process.** Every turn is its own agent invocation
(`PI-11`), so what a session owns is a directory, a conversation id and a lock --
never a subprocess between turns. That is why closing one is cheap and why
nothing leaks when a caller forgets to.

**This registry is lighter than the Gemini build's, and the reason is a
measurement rather than a simplification** (`PI-09`). That target destroys its
own transcript on the first resume, so its registry has to copy one out after
every turn. Pi does not: `--session-dir` is honoured, the file it writes stays
put, and a second process resumed from it across all three providers. So the
conversation lives in the agent's own store and this registry holds the handle
rather than a rescued copy.

**Each session keeps its own agent directory** (`PI-05`), so one session's auth
cache, settings and model store cannot be seen by another, and everything the
agent writes about itself is inside a path this service chose.

**Holding the handle is not enough on its own** (`PI-52`). The handle lives on
the session, and closing one -- by `DELETE` or by the idle sweep -- takes it
while the agent's session directory stays on disk. So the id-to-directory map is
written into the store as well, by `conversations.ConversationIndex`, which is
what makes `options.resume` reach a conversation whose session is gone.
"""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_spec.openapi.schemas import SessionRecord, SessionStatus, TurnRecord
from agent_spec.openapi.stop_kind import derive_stop_kind

from agent_service.config import Settings
from agent_service.conversations import ConversationIndex
from agent_service.pi import kill_process_tree


class RegistryFull(RuntimeError):
    """`max_sessions` reached. **A 429**, and the cap is published."""


class SessionBusy(RuntimeError):
    """A turn is already running. **A 409, never a queue.**

    Two callers on one session would otherwise receive each other's turns.
    """


class UnknownSession(KeyError):
    """No such session id. **A 404.**"""


class InvalidWorkspacePath(ValueError):
    """`working_directory` does not name a directory under the root. **A 400.**"""


class ProviderNotFronted(ValueError):
    """The model names a provider this deployment has no gateway for. **A 400.**

    **Only when a gateway map is configured** (`PI-44`). An unfronted deployment
    has no opinion about providers; a fronted one has exactly the doors its
    operator opened, because a provider with no entry would otherwise reach its
    vendor directly and carry the container's own credential there.
    """


def provider_of(model: str | None, fallback: str | None) -> str | None:
    """The provider a request selects: the part before the slash, or the default.

    `RunOptions.model` carries the provider inside it on this build (`PI-10`),
    so a qualified string is self-describing and a bare id falls back to the
    deployment's configured provider.
    """
    if model and "/" in model:
        return model.split("/", 1)[0]
    return fallback


def check_provider(model: str | None, settings: Any,
                   gateways: dict[str, dict[str, object]]) -> None:
    """Refuse a provider the gateway map does not cover. **No map, no opinion.**

    **The deployment's DEFAULT MODEL is part of the fallback, and leaving it out
    refused every request that named no model.** `AGENT_SERVICE_MODEL` is
    `provider/id` on this build (`PI-10`), so the provider is inside it; reading
    only `AGENT_SERVICE_PROVIDER` -- which a qualified default leaves unset --
    made a fronted deployment answer 400 to its own default. Found by running a
    fronted container, not by a unit test, because the tests configure a model
    and a gateway together.
    """
    if not gateways:
        return
    effective = model or getattr(settings, "model", None)
    provider = provider_of(effective, getattr(settings, "provider", None))
    if provider is None:
        raise ProviderNotFronted(
            "this deployment routes every provider through a gateway, so a "
            "request must name one: send `options.model` as `provider/id`. "
            f"Configured: {sorted(gateways)}."
        )
    if provider not in gateways:
        raise ProviderNotFronted(
            f"provider {provider!r} has no gateway configured on this "
            f"deployment, and this build refuses rather than letting the turn "
            f"reach the vendor directly with the container's own credential. "
            f"Configured: {sorted(gateways)}."
        )


def resolve_workspace(root: Path, subdir: str | None) -> Path:
    """The directory the agent starts in: the root, or a subdirectory of it.

    **Here it is NOT a boundary, and that differs from the Gemini build**
    (`PI-30`). That agent's own guard refuses a file tool outside the directory
    it started in; Pi has no such guard and no sandbox, so this chooses where the
    agent begins and confines nothing. The container is the boundary.

    **Never created.** Caller-supplied per request, and creating one would litter
    the caller's mounted workspace.
    """
    root = root.resolve()
    if not subdir:
        return root
    try:
        resolved = (root / subdir).expanduser().resolve()
    except OSError as exc:
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} cannot be resolved."
        ) from exc
    if not resolved.is_relative_to(root):
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} resolves outside the workspace root. "
            "It is a path RELATIVE to `config.workspace_dir` and must stay "
            "under it."
        )
    if not resolved.is_dir():
        raise InvalidWorkspacePath(
            f"working_directory={subdir!r} does not exist under the workspace "
            "root. This service does not create it: make the directory before "
            "starting a session there."
        )
    return resolved


@dataclass
class Session:
    """One conversation, and the directory that makes it resumable."""

    session_id: str
    workspace: Path
    agent_dir: Path
    session_dir: Path
    created_at: float
    last_used_at: float
    title: str | None = None
    provider: str | None = None
    model: str | None = None
    permission_mode: str = "default"
    turns: int = 0
    #: **The SHARED enum, not a string of this build's choosing.**
    status: SessionStatus = "idle"
    #: **Every conversation id this session has used**, oldest first. On this
    #: build there is normally exactly one -- the id is stable across turns
    #: (`PI-13`) -- but a caller may supply one (`PI-14`), so the list is what
    #: makes `options.resume` accept any id the session has answered to.
    sdk_session_ids: list[str] = field(default_factory=list)
    last_turn: TurnRecord | None = None
    #: What this session has cost so far, summed over its turns (`PI-17`).
    total_cost_usd: float | None = None
    #: One turn at a time. Held for the whole turn, never across a restart.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: Set when THIS service killed the turn. It is the discriminator: a killed
    #: turn fails like any other, and without this flag an interrupt is
    #: indistinguishable from a crash.
    interrupted: bool = False
    #: The live agent process, while a turn is running. Held so it can be killed.
    process: object | None = None
    #: **Where this session's issued ids get written so a later `options.resume`
    #: can find them** (`PI-52`). `None` on a `/v1/query` session: nothing will
    #: ever resume from a one-shot run, so indexing one would promise a
    #: continuity the route does not have.
    conversations: Any = None
    #: **The id this session was opened to continue** (`PI-52`), or `None` for a
    #: fresh one. It is also what tells the first turn to RESUME rather than
    #: name: without it, a session holding an id and no turns is the
    #: caller-supplied-id case (`PI-14`), which must still name.
    resumed_from: str | None = None
    #: False for a `/v1/query` session, which is never in the registry. **It is
    #: what decides whether a stored run carries a `sid`**: a one-shot turn has
    #: no session a client could ever read back.
    registered: bool = True
    #: The caller's `system_prompt`, passed as a flag on every turn (`PI-20`).
    system_prompt: str | None = None
    #: The effective tool grant, computed once at creation.
    allowed_tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] = ()
    #: `RunOptions.include_raw`. Session-scoped like every option here, because
    #: a turn on this build carries a prompt and nothing else.
    include_raw: bool = True
    #: Where the agent starts. Defaults to the workspace root.
    cwd: Path | None = None
    #: **The servers this session's turns carry** (`PI-45`). Session-scoped like
    #: every option here, because a turn on this build carries a prompt and
    #: nothing else. Written to the session's own `mcp.json` before each turn.
    mcp_servers: dict[str, Any] | None = None

    def attach_process(self, proc: object) -> None:
        self.process = proc

    def kill_turn(self) -> bool:
        """Stop a running turn. Returns whether there was one to stop.

        **Abrupt by necessity.** This build spawns per turn and the CLI
        registers no cancel verb, so this kills the subprocess; there is no
        graceful path to offer. The RPC interface has a real `abort`, which is
        one of the reasons to move to it (`PI-11`).

        **The whole group**, because the agent is a Node program that spawns tool
        subprocesses and a grandchild holding the pipes keeps the read alive long
        after its parent is gone.
        """
        proc = self.process
        if proc is None or getattr(proc, "returncode", 0) is not None:
            return False
        self.interrupted = True
        kill_process_tree(proc)
        return True

    def finish(self, *, interrupted: bool, timed_out: bool,
               cost: float | None = None) -> None:
        """Close out a turn, whatever happened to it."""
        self.process = None
        self.status = "idle"
        self.last_used_at = time.time()
        if cost is not None:
            self.total_cost_usd = (self.total_cost_usd or 0.0) + cost
        self.last_turn = TurnRecord(
            sdk_session_id=self.sdk_session_id,
            outcome_recorded=not (interrupted or timed_out),
            interrupted=interrupted,
            timed_out=timed_out,
            # Derived in `agent_spec` rather than decided here: this passes
            # facts, and a second derivation would reintroduce the disagreement
            # the field exists to end.
            stop_kind=derive_stop_kind(
                outcome_recorded=not (interrupted or timed_out),
                is_error=interrupted or timed_out,
                interrupted=interrupted,
                timed_out=timed_out,
            ),
            # **A real figure, and null only when the turn produced none**
            # (`PI-17`). An interrupted turn is killed before any `turn_end`, so
            # there is nothing to price and `None` is the honest answer.
            turn_cost_usd=cost,
        )

    @property
    def sdk_session_id(self) -> str | None:
        """The conversation's id. **Stable across turns** (`PI-13`)."""
        return self.sdk_session_ids[-1] if self.sdk_session_ids else None

    def remember_turn(self) -> None:
        """Index this turn's id against the directory holding it (`PI-52`).

        **After the turn, not before.** The agent writes its session file as the
        turn runs, and an id indexed ahead of that points at a directory with
        nothing in it -- which resolves, resumes nothing, and is the silent
        failure this index exists to end.
        """
        if self.conversations is None:
            return
        self.conversations.remember(
            self.sdk_session_id, self.session_id, str(self.cwd or self.workspace)
        )

    def record(self) -> SessionRecord:
        return SessionRecord(
            session_id=self.session_id,
            sdk_session_id=self.sdk_session_id,
            title=self.title,
            status=self.status,
            created_at=self.created_at,
            last_used_at=self.last_used_at,
            turns=self.turns,
            total_cost_usd=self.total_cost_usd,
            model=self.model,
            permission_mode=self.permission_mode,
            last_turn=self.last_turn,
        )


class Registry:
    """In-process, single-worker. **The session id is this service's own.**

    Running more than one uvicorn worker would route a follow-up turn to a
    process that has never heard of the session, which is true of every build
    here and worth saying once.
    """

    def __init__(self, settings: Settings, recorder: Any = None) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        #: **`NULL_RECORDER` when nothing is configured**, so every call below is
        #: a no-op and no branch is needed at the call sites -- persistence is
        #: optional, not conditional logic sprayed through the registry.
        if recorder is None:
            from agent_spec.db.recorder import NULL_RECORDER

            recorder = NULL_RECORDER
        self.recorder = recorder
        #: **On disk, beside the conversations, so it outlives this process**
        #: (`PI-52`). A restart loses `_sessions` and keeps this, which is why a
        #: conversation stays resumable across one as long as the store does --
        #: the registry is memory and the store is the volume.
        self.conversations = ConversationIndex(settings.session_store)

    def __len__(self) -> int:
        return len(self._sessions)

    def _build(
        self,
        session_id: str,
        *,
        registered: bool,
        title: str | None,
        provider: str | None,
        model: str | None,
        permission_mode: str,
        allowed_tools: tuple[str, ...] | None,
        disallowed_tools: tuple[str, ...],
        system_prompt: str | None,
        include_raw: bool,
        working_directory: str | None,
        sdk_session_id: str | None,
        mcp_servers: Any = None,
    ) -> Session:
        """Everything a session needs before its first turn.

        **One place, because a `/v1/query` turn is not a turn with a smaller
        boundary.** The registered and the ephemeral paths differ in whether the
        session is kept, never in how it is provisioned.
        """
        now = time.time()
        session = Session(
            session_id=session_id,
            workspace=self._settings.workspace_dir,
            agent_dir=self._settings.agent_dir_root / session_id,
            session_dir=self._settings.session_store / session_id,
            created_at=now,
            last_used_at=now,
            title=title,
            provider=provider or self._settings.provider,
            model=model or self._settings.model,
            permission_mode=permission_mode,
            allowed_tools=_permitted(allowed_tools or _default_tools(), disallowed_tools),
            disallowed_tools=tuple(disallowed_tools),
            system_prompt=system_prompt,
            include_raw=include_raw,
            cwd=resolve_workspace(self._settings.workspace_dir, working_directory),
            registered=registered,
            mcp_servers=dict(mcp_servers or {}) or None,
            # **Registered sessions only**: a `/v1/query` turn has no session a
            # caller could ever resume, so indexing one would hand out an id
            # that resolves to a directory nothing will look in again.
            conversations=self.conversations if registered else None,
        )
        if sdk_session_id:
            # **A caller may name the conversation** (`PI-14`). Recorded up
            # front so the first turn passes `--session-id` rather than minting
            # one, and so `find_by_sdk_id` resolves it before any turn runs.
            session.sdk_session_ids.append(sdk_session_id)
        session.agent_dir.mkdir(parents=True, exist_ok=True)
        session.session_dir.mkdir(parents=True, exist_ok=True)
        return session

    def create(
        self,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        permission_mode: str = "default",
        allowed_tools: tuple[str, ...] | None = None,
        disallowed_tools: tuple[str, ...] = (),
        system_prompt: str | None = None,
        include_raw: bool = True,
        working_directory: str | None = None,
        sdk_session_id: str | None = None,
        mcp_servers: Any = None,
        resume: str | None = None,
    ) -> Session:
        """Open a session. **Swept before the cap is tested**, so an idle
        session cannot hold a slot against a caller who waited out the TTL.

        `resume` names a conversation id this build has issued (`PI-52`); the
        session opens holding a copy of that conversation, and an id that
        resolves to nothing raises rather than opening a fresh one.
        """
        self.sweep()
        if len(self._sessions) >= self._settings.max_sessions:
            raise RegistryFull(
                f"{self._settings.max_sessions} sessions are open, which is this "
                "deployment's cap. Close one, or read config.max_sessions "
                "before opening another."
            )
        found = None
        if resume is not None:
            # **Resolved BEFORE anything is built** (`PI-52`), because `_build`
            # makes this session's directories: refusing afterwards would leave
            # an agent directory and a session directory behind for a session
            # that never existed.
            #
            # **Against THIS session's cwd**, because a cross-project match is
            # the one case the agent handles by ASKING: it prints *"Session
            # found in different project"* and prompts for a fork, which a
            # non-interactive turn cannot answer -- exit 0, no turn, no
            # envelope. A `WrongWorkingDirectory` here is that turn refused
            # before a session is opened (`PI-52`).
            found = self.conversations.resolve(
                resume, str(resolve_workspace(self._settings.workspace_dir,
                                              working_directory))
            )
        session = self._build(
            str(uuid.uuid4()), registered=True, title=title, provider=provider,
            model=model, permission_mode=permission_mode,
            allowed_tools=allowed_tools, disallowed_tools=disallowed_tools,
            system_prompt=system_prompt, include_raw=include_raw,
            working_directory=working_directory, sdk_session_id=sdk_session_id,
            mcp_servers=mcp_servers,
        )
        if found is not None and resume is not None:
            # **A COPY, so the new session owns its conversation.** Two sessions
            # writing one session directory would interleave into a file each of
            # them then reads back as its own history. The conversation it came
            # from is untouched and stays resumable.
            shutil.copytree(found.directory, session.session_dir,
                            dirs_exist_ok=True)
            # The id is what `--session` will carry, so it goes on the list the
            # first turn reads -- and `resumed_from` is what makes that turn
            # resume rather than name (`PI-14`).
            #
            # **A resume KEEPS its id, deliberately** (`PI-52`). The agent's own
            # answer is `--fork`, which mints a new one so two branches never
            # share; this build does not, because the id is stable across turns
            # here and answering a resume with a different one would break the
            # property that makes keying on it correct. The cost is that two
            # sessions then answer to one id -- accepted, and the entry lists
            # every edge of it.
            session.sdk_session_ids.append(resume)
            session.resumed_from = resume
        self._sessions[session.session_id] = session
        self.recorder.session_opened(
            session.session_id, title=title, model=session.model,
            permission_mode=permission_mode, at=session.created_at,
        )
        return session

    def ephemeral(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        permission_mode: str = "default",
        allowed_tools: tuple[str, ...] | None = None,
        disallowed_tools: tuple[str, ...] = (),
        system_prompt: str | None = None,
        include_raw: bool = True,
        working_directory: str | None = None,
        sdk_session_id: str | None = None,
        mcp_servers: Any = None,
    ) -> Session:
        """A session for one turn that is never registered.

        **`/v1/query` consumes no slot**, which is published as
        `query_consumes_a_session_slot: false`. It is not in the registry, does
        not count against `max_sessions`, and never appears in `GET
        /v1/sessions` -- a one-shot run has no continuity to offer and pretending
        otherwise would let a caller resume something that is already gone.
        """
        return self._build(
            f"query-{uuid.uuid4()}", registered=False, title=None,
            provider=provider, model=model, permission_mode=permission_mode,
            allowed_tools=allowed_tools, disallowed_tools=disallowed_tools,
            system_prompt=system_prompt, include_raw=include_raw,
            working_directory=working_directory, sdk_session_id=sdk_session_id,
            mcp_servers=mcp_servers,
        )

    def discard(self, session: Session) -> None:
        """Remove an ephemeral session's directories. Safe to call twice."""
        shutil.rmtree(session.agent_dir, ignore_errors=True)
        shutil.rmtree(session.session_dir, ignore_errors=True)

    def sweep(self) -> int:
        """Close sessions idle longer than the published TTL. Returns the count.

        **Lazy, on every operation, rather than a background task.** A reaper
        task is a second place for a session to be closed from, and this service
        has no work to do between requests -- a session is a directory and a
        lock, not a live process, so nothing accrues while it waits.

        A session mid-turn is never swept: `last_used_at` moves when the turn
        ends, and the lock is held until then.
        """
        cutoff = time.time() - self._settings.session_idle_ttl_s
        stale = [
            sid for sid, session in self._sessions.items()
            if session.last_used_at < cutoff and not session.lock.locked()
        ]
        for sid in stale:
            # **`_close`, never `close`.** `close()` resolves through `get()`,
            # which sweeps -- so a stale session would re-enter sweep, find
            # itself stale again, and recurse until the stack ran out.
            self._close(self._sessions[sid], status="expired")
        return len(stale)

    def get(self, session_id: str) -> Session:
        self.sweep()
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise UnknownSession(session_id) from exc

    def list(self) -> list[Session]:
        self.sweep()
        return sorted(self._sessions.values(), key=lambda s: s.created_at)

    def close(self, session_id: str) -> None:
        """Drop the session and its agent directory.

        **The conversation survives** in the session store, which is what
        `options.resume` is for; deleting it here would make DELETE mean two
        things.
        """
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise UnknownSession(session_id) from exc
        self._close(session, status="closed")

    def _close(self, session: Session, *, status: str) -> None:
        """The removal itself. **Does not sweep**, so sweeping can use it."""
        shutil.rmtree(session.agent_dir, ignore_errors=True)
        del self._sessions[session.session_id]
        self.recorder.session_closed(session.session_id, status=status,
                                     at=time.time())

    def find_by_sdk_id(self, sdk_session_id: str) -> Session | None:
        """Any session that has ever answered to this id.

        **Live sessions only, and that is why it is not what serves
        `options.resume`** (`PI-52`). A closed or swept session is not in this
        map, and its conversation is still on disk -- so the index answers a
        resume, and this answers *which open session issued that id*.
        """
        for session in self._sessions.values():
            if sdk_session_id in session.sdk_session_ids:
                return session
        return None


def _default_tools() -> tuple[str, ...]:
    from agent_service.capabilities import DEFAULT_ALLOWED_TOOLS

    return DEFAULT_ALLOWED_TOOLS


def _permitted(
    requested: tuple[str, ...], denied: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Drop what this build always refuses and what the caller denied.

    **Not a silent drop.** `always_disallowed_tools` names the first set, so a
    caller can see before asking; filtering here is honouring that published
    contract rather than quietly editing a request (`PI-25`).

    **Subtracted from the EFFECTIVE allow set** -- the caller's `allowed_tools`
    when they sent one, this build's default when they did not. The default is
    the case that actually bites: it contains `write`, so a request denying that
    tool and naming no others must still lose it.
    """
    from agent_service.capabilities import ALWAYS_DISALLOWED_TOOLS

    refused = set(ALWAYS_DISALLOWED_TOOLS) | set(denied)
    return tuple(t for t in requested if t not in refused)
