"""MCP servers: what a caller may ask for, and how it reaches the agent.

**Two files and one flag, and each of the three is load-bearing.**

1. **`<agent home>/.gemini/settings.json`** carries the servers (GP-46). It goes
   in the session's own HOME rather than the workspace, because the workspace is
   the caller's mounted tree -- one directory shared by every session, and theirs
   rather than ours.
2. **The generated tool policy** must ALLOW the MCP tools, or they are registered
   and refused. `mcpName` needs `toolName` beside it (GP-29); `policy.py` does
   that part.
3. **`--allowed-mcp-server-names`** is `strict_mcp_config` (GP-47), and it is the
   only one of the three that a mounted workspace cannot reach.

**Point 3 exists because of a measurement, not a worry.** A `.gemini/settings.json`
inside the workspace MERGES with ours (GP-46), so a repository could otherwise
add servers -- that is, spawn subprocesses -- that this service never authorised
and the requesting caller cannot see. The allow list is passed on **every** turn,
including when the caller asked for no servers at all, which is why the sentinel
below exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_service.config import auth_selection

#: Transports this build can express, published as `Capabilities.mcp.transports`.
#: **All three**, read from the settings schema in the installed bundle and then
#: confirmed against the binary: each was registered and listed with its own type
#: (GP-46).
MCP_TRANSPORTS = ("stdio", "sse", "http")

#: What an `http` or `sse` server's `headers` may contain here. The settings
#: schema declares a free `string -> string` map with no restriction (GP-46), so
#: this build forwards any header -- unlike the Codex build, which can carry a
#: bearer token and nothing else.
MCP_HTTP_HEADERS = "any"

#: **The one name rule this build enforces, and it is PUBLISHED** as
#: `mcp.server_name_pattern` so a consumer storing a server definition can refuse
#: it where its author can still fix it, rather than at session create. Non-empty
#: and no underscore: the agent names an MCP tool `mcp_<server>_<tool>` and splits
#: on the first `_` after `mcp_` (GP-28), so a name carrying one parses into a
#: different server than it names.
#:
#: **`validate` gates on this constant rather than restating it**, which is what
#: keeps the published pattern and the actual refusal from disagreeing -- the
#: drift AS-32 exists to prevent.
SERVER_NAME_PATTERN = r"^[^_]+$"

#: **How long the agent waits for a tool call's response to BEGIN**, published as
#: `mcp.tool_call.request_timeout_s`. **Measured, and it had to be** (GP-65): this
#: was published as `null` for a day because five reads of the bundle each said
#: the build imposes nothing here, and a live call against this image gave up
#: after 60.2 s with `fetch failed`. A server that opens an SSE stream at once
#: clears it and may then take up to the total below; a server that buffers its
#: whole answer and replies with one JSON body does not.
MCP_TOOL_CALL_REQUEST_TIMEOUT_S = 60

#: **How long a tool call may run before the agent abandons it**, published as
#: `mcp.tool_call.total_timeout_s`. Ten minutes, and it is WALL CLOCK: the bundle
#: applies it to `tools/call` as the MCP request timeout and never passes the flag
#: that would let a progress notification restart it (GP-64). Nothing this service
#: writes moves it -- the settings document carries no per-server `timeout` -- so
#: it is the ceiling on every MCP tool call this build makes.
MCP_TOOL_CALL_TOTAL_TIMEOUT_S = 600

#: **Passed when the caller asked for NO servers**, because "allow nothing"
#: cannot be written on the command line: the flag with no values is a parse
#: error (GP-47). A name containing underscores can never collide with a real
#: server, since those are refused outright (GP-28) -- which is what makes this
#: safe rather than merely unlikely.
NO_SERVERS = "__no_mcp_servers__"


class McpUnsupported(ValueError):
    """A server this build cannot express. **A 400.**

    **Separate from an unsupported OPTION**, because the field is supported: it
    is this particular server that is not, and the caller fixes it by changing
    the server rather than by dropping the field. So `unsupported_options` does
    not name `mcp_servers`.
    """


class McpServersNotAllowed(ValueError):
    """Servers were sent to a deployment that forbids them. **A 400.**

    The same name and reason as the other two builds. `allow_mcp_servers` is a
    deployment setting and it is published, so a caller can check before sending.
    """


def _field(server: Any, name: str) -> Any:
    """Read from a pydantic model or a plain mapping, indifferently."""
    if isinstance(server, dict):
        return server.get(name)
    return getattr(server, name, None)


def validate(servers: Any) -> None:
    """Refuse what cannot work, before a session exists.

    **The underscore rule is the only one that fires over HTTP**, and it is
    measured: the agent names an MCP tool `mcp_<server>_<tool>` and splits on the
    first `_` after `mcp_` (GP-28), so such a name parses into a different server
    than the one it names and no policy rule can address it.

    **The transport check cannot fire from a request, and is kept anyway.** This
    build supports all three of the shared union's members (GP-46), so an
    unexpressible transport fails schema validation with a 422 before reaching
    here -- there is no valid value left to refuse, which is exactly what
    `mcp.transports` publishes. It stays because a fourth member added to the
    union upstream must fail loudly here rather than be written into a settings
    file the agent will reject.
    """
    for name, server in (servers or {}).items():
        if "_" in name:
            raise McpUnsupported(
                f"MCP server name {name!r} contains an underscore. The agent "
                "names an MCP tool `mcp_<server>_<tool>` and splits on the first "
                "'_' after 'mcp_', so this name cannot be addressed by a tool "
                "policy rule. Rename the server without underscores."
            )
        # **The published pattern IS the gate**, so what a client validates
        # against and what this refuses cannot come apart. The underscore case is
        # caught above only to keep its explanation; everything else the pattern
        # rejects -- an empty name being the reachable one -- is refused here
        # naming the pattern a caller can read from `/v1/capabilities`.
        if not re.fullmatch(SERVER_NAME_PATTERN, name):
            raise McpUnsupported(
                f"MCP server name {name!r} does not match {SERVER_NAME_PATTERN}, "
                "published as `mcp.server_name_pattern` on GET /v1/capabilities"
            )
        kind = _field(server, "type") or "stdio"
        if kind not in MCP_TRANSPORTS:
            raise McpUnsupported(
                f"this implementation cannot reach an MCP server over {kind!r}. "
                f"Read `mcp.transports` from GET /v1/capabilities: "
                f"{', '.join(MCP_TRANSPORTS)}."
            )


def settings_document(servers: Any) -> dict[str, Any]:
    """The `mcpServers` map for a `settings.json`, in the AGENT's vocabulary.

    **`url` with `type`, never `httpUrl`.** The bundle carries both and says of
    the latter: *"Using deprecated 'httpUrl'. Please migrate to 'url' with
    'type'"*. Writing the deprecated key would work today and warn, which is a
    worse trade than writing the current one.
    """
    out: dict[str, Any] = {}
    for name, server in (servers or {}).items():
        kind = _field(server, "type") or "stdio"
        if kind == "stdio":
            entry: dict[str, Any] = {"command": _field(server, "command")}
            if _field(server, "args"):
                entry["args"] = list(_field(server, "args"))
            if _field(server, "env"):
                # The SPAWNED SERVER's environment only. Credential material:
                # never logged, and it does not reach the agent's own process.
                entry["env"] = dict(_field(server, "env"))
        else:
            entry = {"type": kind, "url": _field(server, "url")}
            if _field(server, "headers"):
                entry["headers"] = dict(_field(server, "headers"))
        out[name] = entry
    return out


def write_settings(home: Path, servers: Any) -> Path:
    """Write the session's `settings.json`. **Always written, even when empty.**

    An empty `mcpServers` map is not the same as no file: writing it every time
    means the file's presence never depends on the request, so a session cannot
    inherit a stale one from a reused directory. The homes volume is scratch, but
    "cannot" is worth more than "does not today".

    **It also carries the auth method, and a redirected deployment cannot take a
    turn without it** (GP-54). This file is the only place a method can be named
    for a session whose HOME this service mints, so the MCP file and the auth
    file are the same file -- not by design, but it is where both belong.
    """
    document: dict[str, Any] = {"mcpServers": settings_document(servers)}
    method = auth_selection()
    if method is not None:
        document["security"] = {"auth": {"selectedType": method}}
    path = home / ".gemini" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


class StrictModeRequired(ValueError):
    """`strict_mcp_config: false` was asked for. **A 400.**

    **This build is always strict, and cannot be otherwise** (GP-48). Not because
    the flag is hard to omit -- omitting it is one line -- but because the tool
    policy is the second and stronger of the two layers: it denies `*` and allows
    only the servers the caller named, so a server discovered from the workspace
    has every tool removed from the model's context anyway (GP-20).

    Measured: with the flag omitted and a working server registered in the
    workspace, the agent still reported the tool "not available in this
    environment". **So accepting `false` would publish a knob that changes an
    argv and nothing else** -- the accepted-and-ignored defect this build refuses
    to commit, and the field is supported for its other value, which is why this
    is a named refusal rather than an `unsupported_options` entry.
    """


def allowed_names(servers: Any) -> tuple[str, ...]:
    """The `--allowed-mcp-server-names` values. **Never empty, never omitted.**

    The flag is passed even when the request had no servers -- that is the case
    the workspace-merge hole actually bites (GP-46), and a caller who sent no
    servers has asked for no servers, not for whatever the repository happens to
    configure.
    """
    return tuple(sorted(servers)) if servers else (NO_SERVERS,)
