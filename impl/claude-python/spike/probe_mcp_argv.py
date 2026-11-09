"""M2 — does an MCP secret reach the CLI as an argv, and who can read it?

Promised to Agent Studio
§6. Studio offered to run it; this side took it because it is a fact about the
SDK's transport rather than about either design.

**The question, as agreed.** Agent Studio's ADR-0023 substitutes
`${secret:NAME}` into an MCP server's `headers` (http/sse) or `env` (stdio) on
the way to this service. Does that value reach the CLI subprocess as a
**command-line argument**, so that it is readable from `/proc/<pid>/cmdline` by
the agent it was withheld from?

Transport-independent by construction: it is about how the SDK hands its
configuration to the CLI, not about which shape carried the secret.

## Running it

Part 1 needs nothing but the installed SDK:

    uv run python spike/probe_mcp_argv.py

Part 2 needs Linux `/proc`, so it runs in the container and is written up in
CP-075 rather than automated here -- reproduced with:

    docker run -d --name argvprobe \
      -e AGENT_SERVICE_REQUIRE_CREDENTIALS=false \
      -e AGENT_SERVICE_REQUIRE_MOUNTS=false \
      -p 127.0.0.1:8123:8000 <image>
    curl -sX POST 127.0.0.1:8123/v1/sessions -H 'content-type: application/json' \
      -d '{"options":{"mcp_servers":{"remote":{"type":"http",
           "url":"https://mcp.example.invalid/mcp",
           "headers":{"Authorization":"Bearer PROBE-HEADER-SECRET-9d41f"}}}}}'
    docker exec -u agent argvprobe sh -c \
      'for p in /proc/[0-9]*/cmdline; do tr "\\0" " " < "$p" | grep -q PROBE- && echo "$p"; done'

NOTHING HERE IS EXECUTED. `_build_command()` only formats the argv; the CLI
path is set by hand so no subprocess starts and no credential is needed.
"""

from __future__ import annotations

# Stand-ins for a substituted `${secret:NAME}`. Distinct per position so the
# result cannot be read as "one of them leaked" when both did.
SECRET_IN_HEADERS = "SEKRET-HEADER-9d41f"
SECRET_IN_ENV = "SEKRET-ENV-3b7a2"


def main() -> int:
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )
    from claude_agent_sdk.types import ClaudeAgentOptions

    options = ClaudeAgentOptions(
        mcp_servers={
            "remote": {
                "type": "http",
                "url": "https://mcp.example.invalid/mcp",
                "headers": {"Authorization": f"Bearer {SECRET_IN_HEADERS}"},
            },
            "local": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@acme/mcp"],
                "env": {"ACME_TOKEN": SECRET_IN_ENV},
            },
        },
        strict_mcp_config=True,
    )

    transport = SubprocessCLITransport(prompt="unused", options=options)
    # `_build_command` refuses without a resolved path and never runs it.
    transport._cli_path = "/usr/bin/false"  # noqa: SLF001
    argv = transport._build_command()  # noqa: SLF001

    joined = " ".join(argv)
    print(f"argv entries: {len(argv)}")
    for index, arg in enumerate(argv):
        if arg.startswith(("--mcp", "--strict")) or "SEKRET" in arg:
            print(f"  [{index}] {arg[:320]}")

    in_argv_headers = SECRET_IN_HEADERS in joined
    in_argv_env = SECRET_IN_ENV in joined
    print()
    print(f"http `headers` secret in argv : {in_argv_headers}")
    print(f"stdio `env` secret in argv    : {in_argv_env}")

    # Non-zero if the answer ever changes, so this is a regression detector and
    # not only a one-off measurement.
    return 0 if (in_argv_headers and in_argv_env) else 1


if __name__ == "__main__":
    raise SystemExit(main())
