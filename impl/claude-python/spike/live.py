"""Live spike: the four checks that need a real API key.

L1  Does the bundled binary run and a trivial query() complete?
L2  What is the real message sequence for a tool-using run?
L3  Does add_dirs govern Bash, or only the file tools?
L4  Is setting_sources=[] honoured as "load nothing"?

Costs a few cents. Prompts are deliberately tiny and max_turns is capped.

    uv run python spike/live.py            # all checks
    uv run python spike/live.py L3         # one check
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)

TIMEOUT_S = 180


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            "__type__": type(obj).__name__,
            **{f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)},
        }
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return {"__unserializable__": repr(obj)[:200]}


async def run(prompt: str, options: ClaudeAgentOptions, *, dump: bool = False) -> dict[str, Any]:
    """Run one query, return a summary. Never raises."""
    seen: list[str] = []
    session_id: str | None = None
    result: ResultMessage | None = None
    text_parts: list[str] = []
    tool_calls: list[str] = []
    error: str | None = None
    seq = 0

    try:
        async with asyncio.timeout(TIMEOUT_S):
            async for msg in query(prompt=prompt, options=options):
                seq += 1
                kind = type(msg).__name__
                seen.append(kind)
                if dump:
                    print(f"\n--- [{seq}] {kind} ---")
                    print(json.dumps(to_jsonable(msg), indent=2, ensure_ascii=False)[:2600])
                if isinstance(msg, SystemMessage):
                    if not session_id:
                        session_id = (msg.data or {}).get("session_id")
                elif isinstance(msg, ResultMessage):
                    result = msg
                    session_id = session_id or msg.session_id
                else:
                    for block in getattr(msg, "content", None) or []:
                        name = type(block).__name__
                        if name == "TextBlock":
                            text_parts.append(block.text)
                        elif name in ("ToolUseBlock", "ServerToolUseBlock"):
                            tool_calls.append(f"{block.name}({json.dumps(block.input)[:90]})")
    except TimeoutError:
        error = f"TIMEOUT after {TIMEOUT_S}s"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    return {
        "message_types": seen,
        "session_id": session_id,
        "tool_calls": tool_calls,
        "text": "\n".join(text_parts).strip(),
        "result": result,
        "error": error,
    }


def summarize(label: str, out: dict[str, Any]) -> None:
    print(f"\n### {label}")
    if out["error"]:
        print(f"  ERROR       : {out['error']}")
    print(f"  msg types   : {out['message_types']}")
    print(f"  session_id  : {out['session_id']}")
    print(f"  tool calls  : {out['tool_calls'] or '(none)'}")
    r: ResultMessage | None = out["result"]
    if r:
        print(f"  subtype     : {r.subtype}   is_error={r.is_error}   turns={r.num_turns}")
        print(f"  stop_reason : {r.stop_reason}   terminal_reason={r.terminal_reason}")
        print(f"  cost_usd    : {r.total_cost_usd}   duration={r.duration_ms}ms")
        print(f"  denials     : {r.permission_denials}")
        if r.model_usage:
            for model, u in r.model_usage.items():
                print(f"  model_usage : {model} -> {json.dumps(to_jsonable(u))}")
    txt = out["text"].replace("\n", " ")
    print(f"  text        : {txt[:400]}")


# ---------------------------------------------------------------- L1 + L2
async def check_l1_l2(tmp: Path) -> None:
    rule("L1 + L2 — binary runs; full message sequence for a tool-using run")
    ws = tmp / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_text("the magic word is BANANA\n", encoding="utf-8")
    (ws / "notes.md").write_text("# notes\nnothing to see\n", encoding="utf-8")

    out = await run(
        "Read hello.txt and reply with only the magic word.",
        ClaudeAgentOptions(
            cwd=str(ws),
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=6,
        ),
        dump=True,
    )
    summarize("L1/L2 result", out)
    print(f"\n  >>> L1 VERDICT: {'PASS — binary ran' if not out['error'] else 'FAIL'}")
    print(f"  >>> L2: message types observed = {sorted(set(out['message_types']))}")


# ---------------------------------------------------------------- L3
async def check_l3(tmp: Path) -> None:
    rule("L3 — does add_dirs govern Bash, or only the file tools?")
    ws = tmp / "l3_ws"
    outside = tmp / "l3_outside"
    ws.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE-TOKEN-9931\n", encoding="utf-8")
    target = (outside / "secret.txt").as_posix()

    prompt = (
        f"Try to read the file at {target} two ways: first with the Read tool, "
        f"then by running `cat` with the Bash tool. Report for EACH method "
        f"whether it succeeded and the file contents if you got them."
    )

    print(f"\n  workspace (cwd) : {ws}")
    print(f"  outside dir     : {outside}  (contains OUTSIDE-TOKEN-9931)")

    print("\n  --- A: add_dirs=[]  (outside dir NOT granted) ---")
    a = await run(
        prompt,
        ClaudeAgentOptions(
            cwd=str(ws),
            add_dirs=[],
            allowed_tools=["Read", "Bash"],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=8,
        ),
    )
    summarize("L3-A  add_dirs=[]", a)

    print("\n  --- B: add_dirs=[outside]  (granted) ---")
    b = await run(
        prompt,
        ClaudeAgentOptions(
            cwd=str(ws),
            add_dirs=[str(outside)],
            allowed_tools=["Read", "Bash"],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=8,
        ),
    )
    summarize("L3-B  add_dirs=[outside]", b)

    tok = "OUTSIDE-TOKEN-9931"
    a_leak = tok in a["text"]
    b_leak = tok in b["text"]
    print("\n  >>> L3 VERDICT")
    print(f"      without add_dirs, token reached the model : {a_leak}")
    print(f"      with    add_dirs, token reached the model : {b_leak}")
    print(f"      denials without add_dirs: {getattr(a['result'], 'permission_denials', None)}")
    if a_leak:
        print("      => add_dirs does NOT fully confine access (Bash likely bypasses it).")
        print("         The read-only MOUNT is the real boundary, not add_dirs.")
    else:
        print("      => add_dirs appears to confine access for both tools.")


# ---------------------------------------------------------------- L4
async def check_l4(tmp: Path) -> None:
    rule("L4 — is setting_sources=[] honoured as 'load nothing'?")
    ws = tmp / "l4_ws"
    (ws / ".claude").mkdir(parents=True)
    marker = "ZEBRA-7788"
    (ws / "CLAUDE.md").write_text(
        f"# Project instructions\n\nIMPORTANT: end every reply with the token {marker}\n",
        encoding="utf-8",
    )
    prompt = "Say the word 'ready' and nothing else."

    print(f"\n  CLAUDE.md in cwd instructs the model to append {marker}")

    print("\n  --- A: setting_sources=[]  (expect marker ABSENT) ---")
    a = await run(
        prompt,
        ClaudeAgentOptions(
            cwd=str(ws), setting_sources=[], allowed_tools=[],
            permission_mode="dontAsk", max_turns=3,
        ),
    )
    summarize("L4-A  setting_sources=[]", a)

    print("\n  --- B: setting_sources=['project']  (expect marker PRESENT) ---")
    b = await run(
        prompt,
        ClaudeAgentOptions(
            cwd=str(ws), setting_sources=["project"], allowed_tools=[],
            permission_mode="dontAsk", max_turns=3,
        ),
    )
    summarize("L4-B  setting_sources=['project']", b)

    print("\n  >>> L4 VERDICT")
    print(f"      marker with setting_sources=[]          : {marker in a['text']}")
    print(f"      marker with setting_sources=['project'] : {marker in b['text']}")
    if marker not in a["text"] and marker in b["text"]:
        print("      => setting_sources=[] IS honoured as 'load nothing'. Q2 default is safe.")
    elif marker in a["text"]:
        print("      => setting_sources=[] did NOT suppress ambient config. Q2 needs rework.")
    else:
        print("      => inconclusive: neither run picked up CLAUDE.md. Check separately.")


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"API key loaded: {key[:8]}...{key[-4:]}  (len={len(key)})")

    wanted = {a.upper() for a in sys.argv[1:]} or {"L1", "L2", "L3", "L4"}
    with tempfile.TemporaryDirectory(prefix="agentspike_") as td:
        tmp = Path(td)
        print(f"scratch: {tmp}")
        if wanted & {"L1", "L2"}:
            await check_l1_l2(tmp)
        if "L3" in wanted:
            await check_l3(tmp)
        if "L4" in wanted:
            await check_l4(tmp)


if __name__ == "__main__":
    asyncio.run(main())
