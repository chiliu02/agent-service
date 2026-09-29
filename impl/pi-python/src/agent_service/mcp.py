"""What an `mcp_servers` payload may say on this build, and what it becomes.

**Whole-or-nothing, and that is a decision taken WITH the consumer rather than
for them** (`PI-45`). The adapter presents every registered server through a
single proxy tool named `mcp`; the agent never sees a server's own tool names, so
`allowed_tools` can permit or deny all MCP and nothing finer. Agent Harness was
told that and asked for it in that form anyway, because without MCP their worker
cannot commit — and because their own server already varies its listing by caller
and re-checks every call, so the per-tool grant was a third layer rather than the
boundary.

**The config is OURS and the agent is pointed at it by flag** (`PI-45`). The
adapter otherwise reads six files in precedence order, two of them inside the
caller's mounted workspace. `--mcp-config <our file>` means that chain never
runs, which is what `strict_mcp_config: true` means here — structural, not a
setting, and `false` is refused because it is not a behaviour this build has.
"""

from __future__ import annotations

import re
from typing import Any

#: **Both measured** (`PI-46`). `sse` is deliberately absent: the adapter folds
#: it into its HTTP transport as a fallback rather than offering it as a choice,
#: so publishing it would name a transport a caller cannot select.
MCP_TRANSPORTS: tuple[str, ...] = ("stdio", "http")

#: **No underscore, and it is not cosmetic** (`PI-45`). The proxy addresses a
#: tool as `<server>_<tool>`, so an underscore in a server name makes the pair
#: ambiguous — `a_b_c` could be server `a` tool `b_c` or server `a_b` tool `c`.
#: Published as `mcp.server_name_pattern` so a caller sees the rule before a
#: refusal, and this constant is what the refusal below actually applies: a
#: published pattern that disagreed with the real check is the drift AS-32
#: exists to prevent.
SERVER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]*$"

_NAME = re.compile(SERVER_NAME_PATTERN)


class McpUnsupported(ValueError):
    """One server this build cannot express. **A 400 naming that server.**

    Per SERVER rather than per field: `mcp_servers` is supported, and a
    particular entry in it is not.
    """


class McpServersNotAllowed(ValueError):
    """This deployment takes no servers at all. **A 400 with its own type.**

    Either the image carries no adapter or an operator turned it off; both are
    published as `allow_mcp_servers: false`, so a caller can see before asking.
    """


class StrictModeRequired(ValueError):
    """`strict_mcp_config: false`. **A 400**, and the field is otherwise fine."""


def validate(servers: Any) -> None:
    """Refuse what this build cannot honour, per server, before a turn starts."""
    if not servers:
        return
    if not isinstance(servers, dict):
        raise McpUnsupported("`mcp_servers` must be an object keyed by server name.")
    for name, spec in servers.items():
        if not _NAME.match(str(name)):
            raise McpUnsupported(
                f"server name {name!r} does not match {SERVER_NAME_PATTERN}. The "
                "adapter on this build addresses a tool as `<server>_<tool>`, so "
                "an underscore makes the pair ambiguous. Published as "
                "`accepts.mcp.server_name_pattern`."
            )
        body = spec if isinstance(spec, dict) else getattr(spec, "model_dump", dict)()
        kind = _transport_of(body)
        if kind not in MCP_TRANSPORTS:
            raise McpUnsupported(
                f"server {name!r} uses transport {kind!r}, which this build does "
                f"not support. Published as `accepts.mcp.transports`: "
                f"{list(MCP_TRANSPORTS)}."
            )


def _transport_of(body: dict[str, Any]) -> str:
    """The transport a server entry describes.

    **Shape rather than a declared name**, because that is what the adapter
    itself keys on: a `command` is stdio, a `url` is HTTP.
    """
    declared = str(body.get("type") or body.get("transport") or "").lower()
    if declared in {"stdio", "http", "sse", "streamable-http"}:
        return "http" if declared in {"sse", "streamable-http"} else declared
    if body.get("command"):
        return "stdio"
    if body.get("url"):
        return "http"
    return "unknown"


def adapter_config(servers: Any) -> dict[str, Any]:
    """The `mcpServers` object the adapter reads, from what the caller sent.

    **Passed through, not translated.** The adapter's own schema is
    `{command, args, env}` for stdio and `{url, headers}` for HTTP, which is the
    shape `McpServer` already carries — so anything this function invented would
    be a second dialect to keep in step with the first.
    """
    out: dict[str, Any] = {}
    for name, spec in (servers or {}).items():
        body = spec if isinstance(spec, dict) else spec.model_dump(exclude_none=True)
        out[str(name)] = {k: v for k, v in body.items()
                          if k not in {"type", "transport"} and v is not None}
    return out
