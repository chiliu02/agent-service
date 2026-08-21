"""Driving the agent: creating a conversation, resuming one, and reading a turn.

**This is the whole runner. ACP is not used** (GP-41). The protocol was
implemented and deleted: it cannot resume (GP-38), its tool stream is no richer
than this one (GP-40), and its permission channel is a question this service
would ask itself and answer from the policy file it had just written.

**So there is ONE enforcement story and it does not change between turns.** The
generated admin policy is the boundary (GP-19), the agent's own
`Path not in workspace` guard refuses a file tool that wanders, and the container
is the outer edge. What was given up with ACP is host-performed `fs/*` -- the
ability to refuse an individual path without the agent's cooperation (GP-04) --
which was redundant with all three, but was real.

**Two mechanisms make resume durable, and both are measured:**

* **`--session-file`, never `--resume`** (GP-10, GP-11). `--resume` works exactly
  once and then deletes the transcript it just read, because cleanup removes
  every file sharing an 8-character id prefix with a record it considers empty.
  `--session-file` is repeatable and leaves the file untouched.
* **`HOME` is ours** (GP-39). The agent writes its transcript under
  `$HOME/.gemini/tmp/<workspace basename>/chats/`, so pointing `HOME` at a
  service-owned directory is what lets a copy be taken before the agent's own
  cleanup reaches it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_service.config import AGENT_ENV_OVERRIDES

#: **The agent gets its own process group, and killing it kills the group.**
#:
#: Measured: with a plain `proc.kill()` an interrupt issued six seconds into a
#: turn let the HTTP call hang for 7.7s, 30.5s and 69.5s on three consecutive
#: runs. The kill lands on the Node process every time -- what does not end is
#: the READ. `communicate()` waits for EOF on stdout and stderr, and a grandchild
#: that inherited those pipes holds them open long after its parent is gone.
#: Killing the group closes them.
#:
#: POSIX only, which is where this runs: the image is Linux. On Windows the flag
#: is not passed and the fallback is the plain kill, so the tests still work and
#: nobody is misled into thinking the guarantee holds there.
_OWN_PROCESS_GROUP = {"start_new_session": True} if os.name == "posix" else {}


def kill_process_tree(proc: Any) -> None:
    """Kill the agent and everything it spawned. **Never raises.**

    A process that has already exited, a group that is already gone and a
    platform without process groups are all "the turn is over", which is what the
    caller wanted. Raising here would turn a successful interrupt into a 500.
    """
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), 9)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass

#: What the agent's exit codes mean. **Every one measured** (GP-06); `53` is the
#: documented turn limit and is the only entry never reproduced, so it is
#: labelled rather than relied on.
EXIT_MEANINGS: dict[int, str] = {
    0: "success",
    1: "invalid flag or flag value",
    41: "no auth method",
    42: "resume target not found",
    44: "sandbox requested but no runtime",
    53: "turn limit exceeded (documented; never reproduced here)",
    55: "untrusted folder",
}


class CliError(RuntimeError):
    """A turn that did not succeed, carrying the agent's own exit code."""

    def __init__(self, exit_code: int, detail: str) -> None:
        meaning = EXIT_MEANINGS.get(exit_code, "unrecognised")
        super().__init__(f"exit {exit_code} ({meaning}): {detail}")
        self.exit_code = exit_code
        self.detail = detail


class ResumeTargetMissing(CliError):
    """Exit 42. **A 404, not a 400** -- the id named nothing (GP-06)."""


class CredentialMissing(CliError):
    """Exit 41, the code a boot gate keys on."""


class TrustRefused(CliError):
    """Exit 55. The workspace was not trusted, so ZERO turns ran (GP-08)."""


class TurnTimeout(CliError):
    """The wall clock this build must enforce, because nothing else will."""


@dataclass(frozen=True)
class TurnResult:
    """One turn, as this service needs it.

    `transcript` is the file to keep: it is what a later resume is built from,
    and it is taken before the agent's cleanup can reach it (GP-10).
    """

    exit_code: int
    sdk_session_id: str | None
    response: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    transcript: Path | None = None

    @property
    def assistant_text(self) -> str:
        """The answer, reassembled from `delta` chunks (GP-15).

        `message` events arrive in pieces and there is no terminal non-delta
        message, so a reader that waits for one waits forever.
        """
        return "".join(
            str(event.get("content", ""))
            for event in self.events
            if event.get("type") == "message" and event.get("role") == "assistant"
        )

    @property
    def models_used(self) -> dict[str, Any]:
        """Per-model usage. **Per turn, not cumulative** (GP-16)."""
        return dict(self.stats.get("models", {}))


class CliRunner:
    """Drives one agent invocation per turn."""

    def __init__(
        self,
        *,
        binary: Path | tuple[str, ...],
        workspace: Path,
        home: Path,
        model: str | None = None,
        admin_policy: Path | None = None,
        allowed_mcp_servers: tuple[str, ...] | None = None,
    ) -> None:
        self._argv0: list[str] = (
            [str(binary)] if isinstance(binary, (str, Path)) else list(binary)
        )
        self._workspace = workspace.resolve()
        #: **Ours, not the container's** (GP-39). Everything the agent writes
        #: about sessions lands under here, which is what makes the transcript
        #: ours to copy.
        self._home = home.resolve()
        self._model = model
        self._admin_policy = admin_policy
        #: **`strict_mcp_config`, and the only channel a workspace cannot reach**
        #: (GP-47). `None` omits the flag entirely, which opts into the agent's
        #: own discovery -- including a `.gemini/settings.json` sitting in the
        #: caller's mounted workspace (GP-46).
        self._allowed_mcp_servers = allowed_mcp_servers

    # --- shared by run() and StreamingTurn, so the two cannot drift ---------

    @property
    def workspace(self) -> Path:
        return self._workspace

    def argv(self, prompt: str, *, session_file: Path | None,
             sdk_session_id: str | None, approval_mode: str) -> list[str]:
        """The command line. **Never both session flags** (GP-11)."""
        argv = [*self._argv0, "-p", prompt, "-o", "stream-json",
                "--approval-mode", approval_mode]
        if self._model:
            argv += ["-m", self._model]
        if self._admin_policy:
            argv += ["--admin-policy", str(self._admin_policy)]
        if self._allowed_mcp_servers is not None:
            # **On the command line rather than in settings**, because argv wins
            # over every settings file and a settings key would be one more
            # thing the workspace could override (GP-47). Never empty: the flag
            # with no values is a parse error, so "allow nothing" is spelled
            # with a sentinel name.
            argv += ["--allowed-mcp-server-names", *self._allowed_mcp_servers]
        if session_file:
            argv += ["--session-file", str(session_file)]
        elif sdk_session_id:
            argv += ["--session-id", sdk_session_id]
        return argv

    def env(self) -> dict[str, str]:
        """The agent's environment. **HOME is ours** (GP-39, GP-08)."""
        self._home.mkdir(parents=True, exist_ok=True)
        return {
            **os.environ,
            **AGENT_ENV_OVERRIDES,
            # Both, because the agent resolves a home differently per platform
            # and a half-set home silently falls back to the container's.
            "HOME": str(self._home),
            "USERPROFILE": str(self._home),
        }

    def latest_transcript(self) -> Path | None:
        return self._latest_transcript()

    async def run(
        self,
        prompt: str,
        *,
        timeout: float,
        session_file: Path | None = None,
        sdk_session_id: str | None = None,
        approval_mode: str = "default",
        process_sink: Callable[[asyncio.subprocess.Process], None] | None = None,
    ) -> TurnResult:
        """One turn. `session_file` resumes; `sdk_session_id` names a new one.

        **They are mutually exclusive and the agent says so** (GP-11): passing
        both is `exit 1`, so it is refused here instead of being discovered at
        run time.

        `process_sink` receives the live process. **That is how interrupt
        works**: ACP registers no `session/cancel` and the CLI offers nothing
        either (GP-02), so the only way to stop a turn is to kill it, and the
        only way to kill it is to be holding it.
        """
        if session_file and sdk_session_id:
            raise CliError(
                1,
                "--session-file and --session-id are mutually exclusive; a "
                "resumed conversation cannot also be given an id (GP-11)",
            )
        argv = self.argv(prompt, session_file=session_file,
                         sdk_session_id=sdk_session_id, approval_mode=approval_mode)
        env = self.env()
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(self._workspace),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
            **_OWN_PROCESS_GROUP,
        )
        if process_sink is not None:
            process_sink(proc)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            # The GROUP, not just the child: a timed-out turn leaves the same
            # grandchildren an interrupted one does, and on this target timing
            # out is routine rather than exceptional (GP-18).
            kill_process_tree(proc)
            await proc.wait()
            raise TurnTimeout(
                -1, f"the turn did not finish within {timeout}s and was killed"
            ) from None

        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        self._raise_for_exit(proc.returncode or 0, stdout, stderr)

        events = _parse_stream(stdout)
        result_event = next(
            (e for e in reversed(events) if e.get("type") == "result"), {}
        )
        init_event = next((e for e in events if e.get("type") == "init"), {})
        return TurnResult(
            exit_code=proc.returncode or 0,
            # **Not `init.model`** -- that is the literal string "auto" (GP-15).
            sdk_session_id=init_event.get("session_id"),
            response=None,
            events=events,
            stats=result_event.get("stats", {}),
            transcript=self._latest_transcript(),
        )

    def _raise_for_exit(self, code: int, stdout: str, stderr: str) -> None:
        """**Read BOTH streams** (GP-09).

        The JSON envelope is on stdout when the run worked, on stderr when it
        failed, and on neither -- 139 bytes of plain text -- when it failed
        early, as `--sandbox` does. So the detail is whatever is there.
        """
        if code == 0:
            return
        detail = _envelope_message(stderr) or _envelope_message(stdout) or (
            stderr.strip() or stdout.strip() or "no output on either stream"
        )
        if code == 41:
            raise CredentialMissing(code, detail)
        if code == 42:
            raise ResumeTargetMissing(code, detail)
        if code == 55:
            raise TrustRefused(code, detail)
        raise CliError(code, detail[:500])

    def _latest_transcript(self) -> Path | None:
        """The transcript this turn wrote, found under OUR home (GP-39).

        Searched rather than derived: the project identifier comes from the
        workspace basename, lowercased, and a rule that reconstructs it would
        break the moment that derivation changed.
        """
        candidates = sorted(
            self._home.rglob("session-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
        return candidates[-1] if candidates else None

    @staticmethod
    def keep(transcript: Path, destination: Path) -> Path:
        """Copy a transcript somewhere the agent's cleanup cannot reach.

        **This is the whole durability mechanism** (GP-10): the agent deletes
        every file sharing an 8-character id prefix with a record it considers
        empty, and a resume is what produces such a record. A copy outside its
        storage is untouched by that.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(transcript, destination)
        return destination


def _parse_stream(stdout: str) -> list[dict[str, Any]]:
    """`stream-json` is newline-delimited; anything unparseable is skipped."""
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _envelope_message(text: str) -> str | None:
    """The `error.message` from a JSON envelope, if this stream carries one."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        return str(json.loads(text).get("error", {}).get("message") or "") or None
    except json.JSONDecodeError:
        return None


class StreamingTurn:
    """A turn read INCREMENTALLY, so events reach a consumer as they happen.

    **Separate from `CliRunner.run` rather than replacing it**, because the two
    have genuinely different failure shapes. `run` can inspect the exit code
    before deciding what to return; a stream has already committed its response
    by the time the process exits, so a late failure can only arrive in-band.

    Iterate for the agent's own `stream-json` events. When iteration finishes,
    `result` carries the turn and `failure` carries the reason it did not — one
    or the other, never both.
    """

    def __init__(self, runner: CliRunner, prompt: str, *, timeout: float,
                 session_file: Path | None = None, sdk_session_id: str | None = None,
                 approval_mode: str = "default",
                 process_sink: Callable[[asyncio.subprocess.Process], None] | None = None):
        self._runner = runner
        self._prompt = prompt
        self._timeout = timeout
        self._session_file = session_file
        self._sdk_session_id = sdk_session_id
        self._approval_mode = approval_mode
        self._process_sink = process_sink
        self.events: list[dict[str, Any]] = []
        self.result: TurnResult | None = None
        self.failure: CliError | None = None

    async def __aiter__(self):
        argv = self._runner.argv(
            self._prompt, session_file=self._session_file,
            sdk_session_id=self._sdk_session_id, approval_mode=self._approval_mode,
        )
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(self._runner.workspace),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=self._runner.env(),
            **_OWN_PROCESS_GROUP,
        )
        if self._process_sink is not None:
            self._process_sink(proc)
        assert proc.stdout is not None
        try:
            async with asyncio.timeout(self._timeout):
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.events.append(event)
                    yield event
                await proc.wait()
        except TimeoutError:
            kill_process_tree(proc)
            await proc.wait()
            # **The wall clock again** (GP-18): a stream that has committed its
            # response reports this in-band, which is why it is a failure object
            # rather than an exception here.
            self.failure = TurnTimeout(
                -1, f"the turn did not finish within {self._timeout}s and was killed"
            )
            return

        stderr = (await proc.stderr.read()).decode("utf-8", "replace") if proc.stderr else ""
        code = proc.returncode or 0
        if code != 0:
            detail = _envelope_message(stderr) or stderr.strip() or "no output"
            self.failure = _classify(code, detail)
            return
        init = next((e for e in self.events if e.get("type") == "init"), {})
        final = next((e for e in reversed(self.events) if e.get("type") == "result"), {})
        self.result = TurnResult(
            exit_code=0,
            sdk_session_id=init.get("session_id"),
            response=None,
            events=list(self.events),
            stats=final.get("stats", {}),
            transcript=self._runner.latest_transcript(),
        )


def _classify(code: int, detail: str) -> CliError:
    """One place that turns an exit code into the right error (GP-06)."""
    if code == 41:
        return CredentialMissing(code, detail)
    if code == 42:
        return ResumeTargetMissing(code, detail)
    if code == 55:
        return TrustRefused(code, detail)
    return CliError(code, detail[:500])
