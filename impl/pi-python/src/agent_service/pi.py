"""Driving the agent: one `pi --mode json` invocation per turn.

**`--mode json`, not `--mode rpc`, and that is a decision rather than the
obvious choice** (`PI-11`). RPC is the richer interface -- a long-lived process,
correlated request and response, a real `abort`, `get_session_stats` -- and it is
what a second version of this build should use. `--mode json` is what this one
uses because a spawn-per-turn driver has no process to lose: every turn is
independent, a crash costs one turn, and there is no reconnect path to get wrong.
The RPC surface was measured and every command dispatches, so the upgrade is
available and is not being taken yet.

**`stdin` is closed on every invocation, and it is load-bearing** (`PI-12`).
With Pi's MCP adapter installed, `pi -p` and `pi --mode json` produce no output
at all on an inherited stdin -- no session header, no error -- and never exit.
Measured past five minutes and killed. `stdin=DEVNULL` makes the same command
answer instantly. **The image now ships that adapter** (`PI-43`), so the hang is
reachable from here and this flag is the only thing between a request carrying an
MCP server and a turn that never returns.

**Resume is `--session <id>` against a `--session-dir` this service owns**
(`PI-13`). Measured across two processes on all three providers: the second one
answered a question about work the first had done. Pi's own documentation says
print mode does not resume, and it is wrong.

**A session id may be SUPPLIED** (`PI-14`). `--session-id <uuid>` is echoed back
verbatim in the opening `session` event, so this build lets a caller name the
conversation rather than minting one and reporting it afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_service.config import AGENT_ENV_OVERRIDES

#: **The agent gets its own process group, and killing it kills the group.**
#:
#: The agent is a Node program that spawns tool subprocesses. A plain
#: `proc.kill()` lands on Node every time; what does not end is the READ --
#: `communicate()` waits for EOF on stdout and stderr, and a grandchild that
#: inherited those pipes holds them open long after its parent is gone.
#:
#: POSIX only, which is where the image runs. On Windows the flag is not passed
#: and the fallback is the plain kill, so the tests still work and nobody is
#: misled into thinking the guarantee holds there.
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


#: What this agent's exit codes mean. **Short, because the agent is** (`PI-15`).
#: Unlike the Gemini target's seven distinct codes, Pi answers 0 or 1 and puts
#: the distinction in the message -- so the classification below reads text, and
#: says so rather than pretending to a numeric vocabulary that does not exist.
EXIT_MEANINGS: dict[int, str] = {
    0: "success",
    1: "the agent refused or failed; the reason is in the message",
}

#: The message a run with no usable credential produces. **Matched as a prefix
#: on the agent's own wording** (`PI-15`), which is the only signal there is:
#: the exit code is 1, the same as an unknown flag.
_NO_CREDENTIAL = "no api key found"

#: What a resume against an unknown id says. Same exit code, different text.
_NO_SESSION = "no session found matching"


class PiError(RuntimeError):
    """A turn that did not succeed, carrying the agent's own exit code."""

    def __init__(self, exit_code: int, detail: str) -> None:
        meaning = EXIT_MEANINGS.get(exit_code, "unrecognised")
        super().__init__(f"exit {exit_code} ({meaning}): {detail}")
        self.exit_code = exit_code
        self.detail = detail


class ResumeTargetMissing(PiError):
    """**A 404, not a 400** -- the id named nothing."""


class CredentialMissing(PiError):
    """No usable credential for the selected model."""


class TurnTimeout(PiError):
    """The wall clock this build enforces, because nothing else will."""


@dataclass(frozen=True)
class TurnResult:
    """One turn, as this service needs it."""

    exit_code: int
    sdk_session_id: str | None
    response: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    #: The LAST `turn_end` usage. **Per turn, never cumulative** (`PI-16`).
    usage: dict[str, Any] = field(default_factory=dict)
    #: Every `turn_end` usage in the run, oldest first. One `pi` invocation
    #: runs the agent's whole loop, so a single HTTP turn can contain several
    #: model calls and the cost of the turn is their SUM.
    turn_usages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def assistant_text(self) -> str:
        """The answer: the text blocks of the final assistant message.

        **Read from `turn_end`, not reassembled from deltas.** Pi emits a
        complete message on `turn_end` as well as the `text_delta` stream, so
        there is a terminal object to read and stitching the deltas would be a
        second implementation of the same string.
        """
        for event in reversed(self.events):
            if event.get("type") != "turn_end":
                continue
            content = (event.get("message") or {}).get("content") or []
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""

    @property
    def total_cost_usd(self) -> float | None:
        """What this turn cost, in USD. **Real on every provider** (`PI-17`).

        Summed across the run's model calls rather than taken from the last one,
        for the reason `turn_usages` exists: one invocation is one HTTP turn and
        several calls.

        `None` when the agent reported no usage at all, never `0.0` -- a free
        turn and an unmeasured one must not read the same.
        """
        costs = [
            usage.get("cost", {}).get("total")
            for usage in self.turn_usages
            if isinstance(usage.get("cost"), dict)
        ]
        figures = [float(c) for c in costs if isinstance(c, (int, float))]
        return sum(figures) if figures else None

    @property
    def models_used(self) -> dict[str, Any]:
        """Per-model usage, keyed as `<provider>/<model>`.

        **Assembled here because Pi does not publish it** (`PI-18`). Each
        assistant message names its own `provider` and `model` and carries its
        own usage, so the per-model breakdown the specification wants is a
        regrouping of what is already in the stream rather than a figure the
        agent reports.
        """
        models: dict[str, Any] = {}
        for event in self.events:
            if event.get("type") != "turn_end":
                continue
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            provider, model = message.get("provider"), message.get("model")
            if not model:
                continue
            key = f"{provider}/{model}" if provider else str(model)
            entry = models.setdefault(
                key, {"input": 0, "output": 0, "totalTokens": 0, "cost_usd": 0.0}
            )
            for field_name in ("input", "output", "totalTokens"):
                value = usage.get(field_name)
                if isinstance(value, (int, float)):
                    entry[field_name] += value
            cost = (usage.get("cost") or {}).get("total")
            if isinstance(cost, (int, float)):
                entry["cost_usd"] += float(cost)
        return models


class PiRunner:
    """Drives one agent invocation per turn."""

    def __init__(
        self,
        *,
        binary: Path | tuple[str, ...],
        workspace: Path,
        agent_dir: Path,
        session_dir: Path,
        provider: str | None = None,
        model: str | None = None,
        allowed_tools: tuple[str, ...] | None = None,
        disallowed_tools: tuple[str, ...] = (),
        system_prompt: str | None = None,
        provider_gateways: dict[str, dict[str, object]] | None = None,
        mcp_adapter_path: Path | None = None,
        mcp_servers: dict[str, object] | None = None,
    ) -> None:
        self._argv0: list[str] = (
            [str(binary)] if isinstance(binary, (str, Path)) else list(binary)
        )
        self._workspace = workspace.resolve()
        #: Ours, not the container's (`PI-05`). Auth, the model cache, settings
        #: and anything the agent writes about itself land under here.
        self._agent_dir = agent_dir.resolve()
        self._session_dir = session_dir.resolve()
        self._provider = provider
        self._model = model
        self._allowed_tools = allowed_tools
        self._disallowed_tools = disallowed_tools
        self._system_prompt = system_prompt
        #: **Written as `models.json`, not passed as flags** (`PI-42`). A
        #: provider entry carrying only a `baseUrl` reroutes a BUILT-IN provider
        #: and keeps every built-in model, which is what makes this usable
        #: without maintaining a model catalogue per deployment.
        self._provider_gateways = provider_gateways or {}
        #: The adapter, installed once by the image (`PI-43`).
        self._mcp_adapter_path = mcp_adapter_path
        self._mcp_servers = mcp_servers or {}

    @property
    def workspace(self) -> Path:
        return self._workspace

    def argv(self, prompt: str, *, sdk_session_id: str | None,
             resume: str | None) -> list[str]:
        """The command line.

        **`--session` and `--session-id` are different verbs** (`PI-14`): the
        first resumes an existing conversation, the second names a new one. Both
        at once is refused here rather than discovered at run time.

        **The three suppression flags are always passed** (`PI-19`). Pi loads
        skills from `~/.agents/skills/` -- outside the relocatable agent
        directory -- and reads context files and extensions from the workspace,
        which is mounted from the host and writable by the agent. A turn whose
        prompt is the request and whose behaviour depends on what a repository
        happens to contain is not reproducible, so this build reads none of it
        and publishes `setting_sources: []` to say so.
        """
        if sdk_session_id and resume:
            raise PiError(
                1,
                "--session and --session-id are mutually exclusive: a resumed "
                "conversation cannot also be given a new id",
            )
        argv = [
            *self._argv0, "--mode", "json",
            "--session-dir", str(self._session_dir),
            "--no-skills", "--no-extensions", "--no-context-files",
        ]
        # **`--no-extensions` stays even when MCP is on** (`PI-43`). The agent's
        # own help is explicit -- *"Disable extension discovery (explicit -e
        # paths still work)"* -- so naming the adapter by path loads exactly it
        # and nothing the mounted workspace contains. Measured: with the flag
        # alone the adapter's three commands disappear; with the flag AND the
        # path they come back and nothing else does.
        if self._mcp_servers and self._mcp_adapter_path:
            argv += ["--extension", str(self._mcp_adapter_path),
                     # **Our file, so the adapter's six-file precedence chain
                     # never runs.** That is what `strict_mcp_config` means on
                     # this build, and it is structural rather than a setting.
                     "--mcp-config", str(self._agent_dir / "mcp.json")]
        # **`RunOptions.model` carries the provider inside it, and the shared
        # core needed no new field** (`PI-10`). Pi's `--model` accepts
        # `provider/id` -- measured: `--model anthropic/claude-haiku-4-5` with
        # no `--provider` flag billed anthropic and answered. So a qualified
        # model is self-contained and `--provider` would be redundant beside it;
        # the flag is only for a deployment default paired with a bare id.
        if self._model:
            argv += ["--model", self._model]
            if self._provider and "/" not in self._model:
                argv += ["--provider", self._provider]
        elif self._provider:
            argv += ["--provider", self._provider]
        if self._allowed_tools is not None:
            allowed = list(self._allowed_tools)
            # **Granting MCP means granting ONE tool by name** (`PI-48`), and
            # forgetting it is silent. The adapter presents every server through
            # a single proxy tool called `mcp`; an allowlist that does not name
            # it leaves the servers registered, the adapter loaded, and the model
            # unable to see any of it. Measured: a turn asking for a tool it had
            # not been granted answered helpfully that no such tool existed,
            # with `tool_execution` events absent and exit 0.
            #
            # This is the whole-or-nothing grant made concrete rather than
            # described: there is one name to add, and adding it admits every
            # server the request carried.
            if self._mcp_servers and self._mcp_adapter_path and "mcp" not in allowed:
                allowed.append("mcp")
            # Never empty: a flag with no value is a parse error, so "allow
            # nothing" is spelled with the flag that means it.
            argv += (["--tools", ",".join(allowed)] if allowed else ["--no-tools"])
        if self._disallowed_tools:
            argv += ["--exclude-tools", ",".join(self._disallowed_tools)]
        if self._system_prompt is not None:
            # **A flag taking the text itself, not a file and not a variable**
            # (`PI-20`). It REPLACES the agent's own framing, which is what the
            # specification says the string form does on every build.
            argv += ["--system-prompt", self._system_prompt]
        if resume:
            argv += ["--session", resume]
        elif sdk_session_id:
            argv += ["--session-id", sdk_session_id]
        argv += ["-p", prompt]
        return argv

    def write_config(self) -> None:
        """Write what the agent reads from its own directory, before a turn.

        **Two files, both ours, both per session.** `models.json` points a
        built-in provider at a gateway (`PI-42`); `mcp.json` carries the servers
        this request asked for. Neither is written when the corresponding
        feature is unconfigured, so a plain deployment has an empty agent
        directory and the agent's own defaults.
        """
        self._agent_dir.mkdir(parents=True, exist_ok=True)
        if self._provider_gateways:
            providers = {
                name: {
                    "baseUrl": entry["base_url"],
                    **({"headers": entry["headers"]} if entry.get("headers") else {}),
                }
                for name, entry in self._provider_gateways.items()
            }
            (self._agent_dir / "models.json").write_text(
                json.dumps({"providers": providers}, indent=2), encoding="utf-8"
            )
        if self._mcp_servers:
            # **Through `adapter_config`, never straight to `json.dumps`.** The
            # registry holds what the request carried, which is a pydantic
            # `McpStdioServer` rather than a dict -- and dumping it raised
            # `TypeError: Object of type McpStdioServer is not JSON
            # serializable` at the first real MCP turn, as a 500. Every unit
            # test passed, because they all built the session from plain dicts.
            from agent_service.mcp import adapter_config

            (self._agent_dir / "mcp.json").write_text(
                json.dumps({"mcpServers": adapter_config(self._mcp_servers)},
                           indent=2),
                encoding="utf-8",
            )

    def env(self) -> dict[str, str]:
        """The agent's environment. **The agent directory is ours** (`PI-05`)."""
        self.write_config()
        self._session_dir.mkdir(parents=True, exist_ok=True)
        from agent_service.config import AGENT_DIR_ENV_VAR

        return {
            **os.environ,
            **AGENT_ENV_OVERRIDES,
            AGENT_DIR_ENV_VAR: str(self._agent_dir),
        }

    async def run(
        self,
        prompt: str,
        *,
        timeout: float,
        sdk_session_id: str | None = None,
        resume: str | None = None,
        cwd: Path | None = None,
        process_sink: Callable[[asyncio.subprocess.Process], None] | None = None,
    ) -> TurnResult:
        """One turn.

        `process_sink` receives the live process. **That is how interrupt
        works**: this build spawns per turn, so the only way to stop one is to
        kill it, and the only way to kill it is to be holding it.
        """
        argv = self.argv(prompt, sdk_session_id=sdk_session_id, resume=resume)
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd or self._workspace),
            stdin=asyncio.subprocess.DEVNULL,  # PI-12
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=self.env(), **_OWN_PROCESS_GROUP,
        )
        if process_sink is not None:
            process_sink(proc)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            kill_process_tree(proc)
            await proc.wait()
            raise TurnTimeout(
                -1, f"the turn did not finish within {timeout}s and was killed"
            ) from None

        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        events = parse_stream(stdout)
        raise_for_exit(proc.returncode or 0, stderr, stdout)
        return build_result(proc.returncode or 0, events)


def build_result(exit_code: int, events: list[dict[str, Any]]) -> TurnResult:
    """A parsed event stream as a `TurnResult`. Shared by both paths."""
    header = next((e for e in events if e.get("type") == "session"), {})
    usages = [
        (e.get("message") or {}).get("usage") or {}
        for e in events if e.get("type") == "turn_end"
    ]
    return TurnResult(
        exit_code=exit_code,
        # **Present before the first model call** (`PI-21`): the opening
        # `session` event carries the id even on a run that then fails for want
        # of a credential, so a session has a durable handle from the start.
        sdk_session_id=header.get("id"),
        response=None,
        events=events,
        usage=usages[-1] if usages else {},
        turn_usages=[u for u in usages if u],
    )


def raise_for_exit(code: int, stderr: str, stdout: str) -> None:
    """**The distinction is in the TEXT, not the code** (`PI-15`).

    Pi answers 1 for an unknown flag, a missing credential and an unknown
    session alike, so a numeric table would classify nothing. This reads the
    message and says so, and anything unrecognised stays a plain `PiError`
    rather than being forced into a category.
    """
    if code == 0:
        return
    detail = (stderr.strip() or stdout.strip() or "no output on either stream")
    lowered = detail.lower()
    if _NO_CREDENTIAL in lowered:
        raise CredentialMissing(code, detail)
    if _NO_SESSION in lowered:
        raise ResumeTargetMissing(code, detail)
    raise PiError(code, detail[:500])


def parse_stream(stdout: str) -> list[dict[str, Any]]:
    """`--mode json` is newline-delimited; anything unparseable is skipped."""
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


class StreamingTurn:
    """A turn read INCREMENTALLY, so events reach a consumer as they happen.

    **Separate from `PiRunner.run` rather than replacing it**, because the two
    have genuinely different failure shapes. `run` can inspect the exit code
    before deciding what to return; a stream has already committed its response
    by the time the process exits, so a late failure can only arrive in-band.

    Iterate for the agent's own events. When iteration finishes, `result` carries
    the turn and `failure` carries the reason it did not -- one or the other,
    never both.
    """

    def __init__(self, runner: PiRunner, prompt: str, *, timeout: float,
                 sdk_session_id: str | None = None, resume: str | None = None,
                 cwd: Path | None = None,
                 process_sink: Callable[[asyncio.subprocess.Process], None] | None = None):
        self._runner = runner
        self._prompt = prompt
        self._timeout = timeout
        self._sdk_session_id = sdk_session_id
        self._resume = resume
        self._cwd = cwd
        self._process_sink = process_sink
        self.events: list[dict[str, Any]] = []
        self.result: TurnResult | None = None
        self.failure: PiError | None = None

    async def __aiter__(self):
        argv = self._runner.argv(
            self._prompt, sdk_session_id=self._sdk_session_id, resume=self._resume,
        )
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(self._cwd or self._runner.workspace),
            stdin=asyncio.subprocess.DEVNULL,  # PI-12
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=self._runner.env(), **_OWN_PROCESS_GROUP,
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
            self.failure = TurnTimeout(
                -1, f"the turn did not finish within {self._timeout}s and was killed"
            )
            return

        stderr = (await proc.stderr.read()).decode("utf-8", "replace") if proc.stderr else ""
        code = proc.returncode or 0
        if code != 0:
            try:
                raise_for_exit(code, stderr, "")
            except PiError as failure:
                self.failure = failure
            return
        self.result = build_result(0, list(self.events))
