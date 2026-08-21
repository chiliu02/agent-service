"""Sessions: what this service holds, because the agent holds nothing useful.

**On this target the registry is not bookkeeping, it is the mechanism.** The
agent's own listing hides sessions that are still resumable and shows ones about
to be deleted (GP-14), and its transcript is destroyed by its first resume
(GP-10). So `GET /v1/sessions`, `DELETE`, and continuity across turns are all
answered from here.

**A session is not a live process.** Every turn is its own agent invocation
(GP-41), so what a session owns is a directory, a policy, a transcript and a
lock — never a subprocess between turns. That is why closing one is cheap and
why nothing leaks when a caller forgets to.

**Three things each session keeps, and each is a measured requirement:**

* **its own agent HOME** (GP-39), so the transcript lands where we can copy it
  and one session cannot see another's history;
* **a transcript copy taken after every turn** (GP-10), because the agent
  deletes every file sharing an 8-character id prefix with a record it considers
  empty, and a resume is what produces such a record;
* **every SDK id it has ever issued** (GP-35), because `options.resume` takes an
  SDK id and a client that lost its connection is holding a stale one.
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

from agent_service.cli import kill_process_tree
from agent_service.config import Settings
from agent_service.mcp import allowed_names, write_settings
from agent_service.policy import ToolPolicy, write_admin_policy


class RegistryFull(RuntimeError):
    """`max_sessions` reached. **A 429**, and the cap is published."""


class SessionBusy(RuntimeError):
    """A turn is already running. **A 409, never a queue.**

    Two callers on one session would otherwise receive each other's turns.
    """


class UnknownSession(KeyError):
    """No such session id. **A 404.**"""


@dataclass
class Session:
    """One conversation, and the files that make it resumable."""

    session_id: str
    workspace: Path
    agent_home: Path
    policy_file: Path
    transcript: Path
    created_at: float
    last_used_at: float
    title: str | None = None
    model: str | None = None
    permission_mode: str = "default"
    turns: int = 0
    #: **The SHARED enum, not a string of this build's choosing.** It was `str`
    #: and held `"busy"` -- which is not a member -- so every read of a session
    #: while a turn was in flight failed validation and returned 500. That is
    #: `GET /v1/sessions/{sid}`, the listing, and `POST .../interrupt`, which is
    #: only ever called during a turn and was therefore broken outright. Nothing
    #: caught it because a fake agent's turn finishes before anything can look.
    status: SessionStatus = "idle"
    #: **Every SDK id this session has issued**, oldest first (GP-35).
    #: `options.resume` accepts any of them, because the caller most likely to
    #: resume is the one that lost the connection and holds an old id.
    sdk_session_ids: list[str] = field(default_factory=list)
    last_turn: TurnRecord | None = None
    #: One turn at a time. Held for the whole turn, never across a restart.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: Set when THIS service killed the turn, which is the only way to stop one
    #: (GP-02). It is the discriminator: a killed turn fails like any other, and
    #: without this flag an interrupt is indistinguishable from a crash.
    interrupted: bool = False
    #: The live agent process, while a turn is running. Held so it can be killed.
    process: object | None = None
    #: False for a `/v1/query` session, which is never in the registry. **It is
    #: what decides whether a stored run carries a `sid`**: a one-shot turn has
    #: no session a client could ever read back, so recording one would invent a
    #: key that resolves to nothing.
    registered: bool = True
    #: **What `--allowed-mcp-server-names` will carry on every turn** (GP-47).
    #: `None` means the flag is omitted, which is `strict_mcp_config: false` and
    #: lets the agent's own discovery -- including the caller's workspace -- add
    #: servers. A one-element tuple naming the sentinel means "no servers at
    #: all", which is what a request with no `mcp_servers` gets by default.
    mcp_allowed_names: tuple[str, ...] | None = None

    def attach_process(self, proc: object) -> None:
        self.process = proc

    def kill_turn(self) -> bool:
        """Stop a running turn. Returns whether there was one to stop.

        **Abrupt by necessity.** Neither interface registers a cancel verb, so
        this kills the subprocess; there is no graceful path to offer.

        **The whole group, and that is not a refinement.** Killing only the agent
        left the turn's HTTP call hanging for up to 69 seconds after a successful
        interrupt: the read waits for EOF on pipes a grandchild still holds. The
        caller had already been told the turn was stopped.
        """
        proc = self.process
        if proc is None or getattr(proc, "returncode", 0) is not None:
            return False
        self.interrupted = True
        kill_process_tree(proc)
        return True

    def finish(self, *, interrupted: bool, timed_out: bool) -> None:
        """Close out a turn, whatever happened to it."""
        self.process = None
        self.status = "idle"
        self.last_used_at = time.time()
        self.last_turn = TurnRecord(
            sdk_session_id=self.sdk_session_id,
            outcome_recorded=not (interrupted or timed_out),
            interrupted=interrupted,
            timed_out=timed_out,
            # **The one surface on this build where `timed_out` is readable at
            # all** (GP-58). A turn that ran out of wall clock answered 504 and
            # produced no `RunResponse`, so the live path can never say
            # `stop_kind: "timed_out"` here -- this record is what is left.
            #
            # Derived in `agent_spec` rather than decided here: this passes
            # facts, and a second derivation would reintroduce the disagreement
            # the field exists to end.
            stop_kind=derive_stop_kind(
                outcome_recorded=not (interrupted or timed_out),
                is_error=interrupted or timed_out,
                interrupted=interrupted,
                timed_out=timed_out,
            ),
            # Null, never 0.0: this build cannot price a turn at all (GP-16).
            turn_cost_usd=None,
        )

    @property
    def sdk_session_id(self) -> str | None:
        """The most recent one. **Per turn, not per session** (GP-34)."""
        return self.sdk_session_ids[-1] if self.sdk_session_ids else None

    @property
    def has_transcript(self) -> bool:
        return self.transcript.exists()

    def record(self) -> SessionRecord:
        return SessionRecord(
            session_id=self.session_id,
            sdk_session_id=self.sdk_session_id,
            title=self.title,
            status=self.status,
            created_at=self.created_at,
            last_used_at=self.last_used_at,
            turns=self.turns,
            # **Never 0.0** (GP-16). The agent reports tokens and latency and no
            # monetary figure at all, and `0.0` would read as *free*.
            total_cost_usd=None,
            model=self.model,
            permission_mode=self.permission_mode,
            last_turn=self.last_turn,
        )

    def keep_transcript(self, produced: Path | None) -> None:
        """Copy the turn's transcript somewhere the agent cannot reach it.

        **The whole durability mechanism** (GP-10, GP-11). Called after every
        turn rather than only before a resume: the file that survives is the one
        copied out, and the agent's cleanup runs on its own schedule.
        """
        if produced is None or not produced.exists():
            return
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, self.transcript)


class Registry:
    """In-process, single-worker. **The session id is this service's own.**

    Running more than one uvicorn worker would route a follow-up turn to a
    process that has never heard of the session, which is true of every build
    here and worth saying once.
    """

    def __init__(self, settings: Settings, recorder: Any = None) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        #: Where session rows go. **`NULL_RECORDER` when nothing is
        #: configured**, so every call below is a no-op and no branch is needed
        #: at the call sites -- persistence is optional, not conditional logic
        #: sprayed through the registry.
        if recorder is None:
            from agent_spec.db.recorder import NULL_RECORDER

            recorder = NULL_RECORDER
        self.recorder = recorder

    def __len__(self) -> int:
        return len(self._sessions)

    def _provision(
        self,
        session: Session,
        *,
        allowed_tools: tuple[str, ...] | None,
        disallowed_tools: tuple[str, ...] = (),
        mcp_servers: Any,
    ) -> None:
        """Write everything a session needs before its first turn.

        **One place, because a `/v1/query` turn is not a turn with a smaller
        boundary.** The policy and the MCP settings are written together here so
        the registered and the ephemeral paths cannot come to differ -- which is
        the same reason `api._runner_for` exists.

        **Three coupled pieces** (GP-46, GP-47): the servers go in the session's
        own `settings.json`, the policy must ALLOW their tools or they are
        registered and refused (GP-29), and the allow-list flag is what stops the
        caller's workspace adding its own.
        """
        session.agent_home.mkdir(parents=True, exist_ok=True)
        write_settings(session.agent_home, mcp_servers)
        session.mcp_allowed_names = allowed_names(mcp_servers)
        write_admin_policy(
            ToolPolicy(
                allowed_tools=_permitted(
                    allowed_tools or _default_tools(), disallowed_tools
                ),
                # **Only what the caller sent.** Never the sentinel, and never a
                # name discovered elsewhere: a policy that allowed a server the
                # request did not name would undo the allow list it sits beside.
                allowed_mcp_servers=tuple(sorted(mcp_servers or ())),
            ),
            session.policy_file,
        )

    def create(
        self,
        *,
        title: str | None = None,
        model: str | None = None,
        permission_mode: str = "default",
        allowed_tools: tuple[str, ...] | None = None,
        disallowed_tools: tuple[str, ...] = (),
        mcp_servers: Any = None,
    ) -> Session:
        """Open a session and write its policy. **The policy is per session.**

        A caller's `allowed_tools` becomes an admin-tier file (GP-21) generated
        from a typed structure rather than a template, because the spelling trap
        in a `modes` rule voids the whole file at exit 0 (GP-25).
        """
        # Swept BEFORE the cap is tested, so an idle session cannot hold a slot
        # against a caller who waited out the TTL.
        self.sweep()
        if len(self._sessions) >= self._settings.max_sessions:
            raise RegistryFull(
                f"{self._settings.max_sessions} sessions are open, which is this "
                "deployment's cap. Close one, or read capabilities.max_sessions "
                "before opening another."
            )
        session_id = str(uuid.uuid4())
        now = time.time()
        session = Session(
            session_id=session_id,
            workspace=self._settings.workspace_dir,
            # Its own HOME (GP-39), so the agent's storage is ours and isolated.
            agent_home=self._settings.agent_home_root / session_id,
            policy_file=self._settings.agent_home_root / session_id / "admin-policy.toml",
            transcript=self._settings.transcript_store / f"{session_id}.jsonl",
            created_at=now,
            last_used_at=now,
            title=title,
            model=model or self._settings.model,
            permission_mode=permission_mode,
        )
        self._provision(session, allowed_tools=allowed_tools,
                        disallowed_tools=disallowed_tools,
                        mcp_servers=mcp_servers)
        self._sessions[session_id] = session
        self.recorder.session_opened(session_id, title=title, model=session.model,
                                     permission_mode=permission_mode, at=now)
        return session

    def ephemeral(
        self,
        *,
        model: str | None = None,
        permission_mode: str = "default",
        allowed_tools: tuple[str, ...] | None = None,
        disallowed_tools: tuple[str, ...] = (),
        mcp_servers: Any = None,
    ) -> Session:
        """A session for one turn that is never registered.

        **`/v1/query` consumes no slot**, which is published as
        `capabilities.query_consumes_a_session_slot: false`. It is not in the
        registry, does not count against `max_sessions`, and never appears in
        `GET /v1/sessions` -- a one-shot run has no continuity to offer and
        pretending otherwise would let a caller resume something that is
        already gone.

        It still gets its own HOME and its own policy: a one-shot turn is not a
        turn with a smaller boundary.
        """
        session_id = f"query-{uuid.uuid4()}"
        now = time.time()
        session = Session(
            session_id=session_id,
            workspace=self._settings.workspace_dir,
            agent_home=self._settings.agent_home_root / session_id,
            policy_file=self._settings.agent_home_root / session_id / "admin-policy.toml",
            # Under the agent home rather than the store: nothing will resume
            # from it, so keeping it would be litter with a retention policy.
            transcript=self._settings.agent_home_root / session_id / "transcript.jsonl",
            created_at=now,
            last_used_at=now,
            model=model or self._settings.model,
            permission_mode=permission_mode,
            registered=False,
        )
        self._provision(session, allowed_tools=allowed_tools,
                        disallowed_tools=disallowed_tools,
                        mcp_servers=mcp_servers)
        return session

    def discard(self, session: Session) -> None:
        """Remove an ephemeral session's directory. Safe to call twice."""
        shutil.rmtree(session.agent_home, ignore_errors=True)

    def sweep(self) -> int:
        """Close sessions idle longer than the published TTL. Returns the count.

        **Lazy, on every operation, rather than a background task.** A reaper
        task is a second place for a session to be closed from, and this service
        has no work to do between requests -- a session is a directory and a
        lock, not a live process (GP-41), so nothing accrues while it waits.

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
            # which sweeps -- so a session that was actually stale re-entered
            # sweep, found itself stale again, and recursed until the stack ran
            # out. Nothing caught it because no test had let a session age past
            # the TTL, and the TTL is 1800s.
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
        """Drop the session and its agent home. **The transcript survives.**

        A closed session's conversation is still resumable from the store, which
        is what `options.resume` is for; deleting the transcript here would make
        DELETE mean two things.
        """
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise UnknownSession(session_id) from exc
        self._close(session, status="closed")

    def _close(self, session: Session, *, status: str) -> None:
        """The removal itself. **Does not sweep**, so sweeping can use it.

        `status` distinguishes a caller's DELETE from the idle sweep, because a
        reader of a `sessions` row cannot otherwise tell a client that tidied up
        from one that walked away.
        """
        shutil.rmtree(session.agent_home, ignore_errors=True)
        del self._sessions[session.session_id]
        self.recorder.session_closed(session.session_id, status=status,
                                     at=time.time())

    def find_by_sdk_id(self, sdk_session_id: str) -> Session | None:
        """Any session that has ever issued this id (GP-35).

        Not only the most recent: the caller most likely to resume is the one
        whose connection dropped, and it is holding an older id.
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

    **Not a silent drop.** `capabilities.always_disallowed_tools` names the
    first set, so a caller can see before asking; filtering here is honouring
    that published contract rather than quietly editing a request. The shell is
    on it because an unrestricted `run_shell_command` voids every other rule in
    the policy (GP-20) -- a session that asked for it and got it would have no
    boundary at all, which is worse than not getting what it asked for.

    **`denied` is the caller's `disallowed_tools`, and subtracting it here is
    the whole implementation** (GP-57). It is applied to the EFFECTIVE allow set
    -- the caller's `allowed_tools` when they sent one, this build's default
    when they did not -- because the default is the case where ignoring it
    actually bit: it contains `write_file`, so a request denying that tool and
    naming no others kept it.

    **Subtracting from the allow set rather than writing a deny rule is
    required, not stylistic** (GP-20). A rule denying a tool by name removes it
    from the model's context and the agent reaches for the shell instead; under
    deny-`*` an absent name is simply never allowed, which is the same intent
    with none of the routing-around.
    """
    from agent_service.capabilities import ALWAYS_DISALLOWED_TOOLS

    refused = set(ALWAYS_DISALLOWED_TOOLS) | set(denied)
    return tuple(t for t in requested if t not in refused)
