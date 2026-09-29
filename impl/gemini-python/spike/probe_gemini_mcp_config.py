"""Where MCP servers may be registered, and which transports survive validation.

**FREE: no credential, no turn, no tokens.** `gemini mcp list` reads the settings
files, resolves every server and prints what it found, which answers the two
questions that decide how this build wires MCP -- without spending anything.

**The question that matters is WHERE.** The earlier MCP probe registered its
server in the *workspace's* `.gemini/settings.json`, which this build cannot do:
the workspace is the caller's mounted tree, one directory shared by every
session. Writing there would be a side effect nobody asked for and two concurrent
sessions would overwrite each other. This service owns one thing per session --
its agent `HOME` (GP-39) -- so the whole design depends on the CLI reading
`$HOME/.gemini/settings.json`.

Usage:

    uv run --no-project python spike/probe_gemini_mcp_config.py node_modules
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PINNED = "0.54.4"

#: No underscore, deliberately: the tool name is `mcp_<server>_<tool>` and the
#: parser splits on the first `_` after `mcp_` (GP-28).
STDIO_SERVER = "stdioprobe"


def run(binary: Path, args: list[str], home: Path, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Windows resolves the home directory from USERPROFILE; the container from
    # HOME. Both are set so this probe answers the same question on either.
    env["USERPROFILE"] = str(home)
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    return subprocess.run([str(binary), *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=120)


def write_settings(home: Path, servers: dict) -> Path:
    settings = home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8")
    return settings


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "node_modules").resolve()
    binary = root / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")
    if not binary.exists():
        print(f"no CLI at {binary}; npm install --no-save @google/gemini-cli@{PINNED}")
        return 2

    version = run(binary, ["--version"], Path.home(), Path.cwd())
    print(f"CLI version: {version.stdout.strip().splitlines()[-1]}  (pinned {PINNED})")

    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        home, workspace = temp / "home", temp / "workspace"
        workspace.mkdir(parents=True)

        print("\n1. IS $HOME/.gemini/settings.json READ AT ALL?")
        print("   Nothing is written into the workspace. If the server is listed,")
        print("   this build can give every session its own MCP set.")
        settings = write_settings(home, {
            STDIO_SERVER: {"command": sys.executable, "args": ["-c", "pass"]},
        })
        listed = run(binary, ["mcp", "list"], home, workspace)
        print(f"   settings at: {settings}")
        print(f"   exit {listed.returncode}")
        for line in (listed.stdout + listed.stderr).strip().splitlines():
            print(f"     | {line}")

        print("\n2. ALL THREE TRANSPORTS, together.")
        print("   The bundle's schema says the `type` enum is stdio|sse|http and")
        print("   that `headers` is a free string map. This asks the binary.")
        write_settings(home, {
            STDIO_SERVER: {"command": sys.executable, "args": ["-c", "pass"]},
            "sseprobe": {"type": "sse", "url": "https://example.invalid/sse",
                         "headers": {"X-Probe": "1", "Authorization": "Bearer x"}},
            "httpprobe": {"type": "http", "url": "https://example.invalid/mcp",
                          "headers": {"X-Probe": "1"}},
        })
        listed = run(binary, ["mcp", "list"], home, workspace)
        print(f"   exit {listed.returncode}")
        for line in (listed.stdout + listed.stderr).strip().splitlines():
            print(f"     | {line}")

        print("\n3. A REJECTED SERVER: does a bad transport fail loudly or silently?")
        print("   GP-25 is the precedent -- one bad enum value discarded an entire")
        print("   policy file at exit 0. If settings.json does the same, every")
        print("   session's MCP set could vanish without a symptom.")
        write_settings(home, {
            STDIO_SERVER: {"command": sys.executable, "args": ["-c", "pass"]},
            "badprobe": {"type": "carrier-pigeon", "url": "https://example.invalid"},
        })
        listed = run(binary, ["mcp", "list"], home, workspace)
        print(f"   exit {listed.returncode}")
        for line in (listed.stdout + listed.stderr).strip().splitlines():
            print(f"     | {line}")

        print("\n4. DOES A WORKSPACE FILE OVERRIDE OR MERGE WITH THE HOME ONE?")
        print("   A caller's repo may carry its own .gemini/settings.json. If that")
        print("   REPLACES ours, a mounted workspace could silently drop the")
        print("   servers the caller asked for -- or add ones they did not.")
        write_settings(home, {
            STDIO_SERVER: {"command": sys.executable, "args": ["-c", "pass"]},
        })
        (workspace / ".gemini").mkdir(parents=True, exist_ok=True)
        (workspace / ".gemini" / "settings.json").write_text(json.dumps({
            "mcpServers": {"workspaceprobe": {"command": sys.executable,
                                              "args": ["-c", "pass"]}}
        }), encoding="utf-8")
        listed = run(binary, ["mcp", "list"], home, workspace)
        print(f"   exit {listed.returncode}")
        for line in (listed.stdout + listed.stderr).strip().splitlines():
            print(f"     | {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
