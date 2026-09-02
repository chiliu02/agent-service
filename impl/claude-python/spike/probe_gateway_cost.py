"""Live probe: does an overridden ANTHROPIC_BASE_URL kill the CLI's cost
accounting, and does the wire session header match a CLI-GENERATED id?

Two questions this service owes a consumer an answer on, not a status:

G1  X4 measured `total_cost_usd: 0` through a proxy, with a PRE-ASSIGNED session
    id, cause unestablished. Is it the base-URL override itself? Is the zero
    literal or absent? Does `usage` still carry real token counts when the
    dollar figure is zero? Those three decide whether this service is ABLE to
    report `null` instead of `0` -- the consumer's request is explicitly
    withdrawn if it cannot tell.
G2  X4's wire measurement used a pre-assigned id, so `sdk_session_id ==
    x-claude-code-session-id` is measured only for that case. This runs the same
    proxy with NO pre-assignment, which is how every session works today.

Three cases, one turn each, `claude-haiku-4-5`, one-word prompts:

  C1  direct, CLI-generated id                  -- the baseline figures
  C2  proxied, CLI-generated id, headers forwarded VERBATIM
  C3  proxied, ANTHROPIC_BASE_URL set to the real API host through no proxy at
      all -- separates "the override" from "a proxy in the path"

    uv run --env-file .env python spike/probe_gateway_cost.py

Never prints the API key. C2 forwards request bodies to the real API through an
in-process proxy bound to 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)

RESULTS: list[tuple[str, str]] = []
MODEL = "claude-haiku-4-5"
UPSTREAM = "https://api.anthropic.com"


def record(case: str, finding: str) -> None:
    RESULTS.append((case, finding))
    print(f"\n>>> {case}: {finding}\n", flush=True)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def base_options(ws: Path, **extra: Any) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(ws),
        model=MODEL,
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=2,
        max_budget_usd=0.25,
        **extra,
    )


def _tokens(usage: Any) -> dict[str, Any]:
    """The token counts, whatever shape `usage` arrives in."""
    if not isinstance(usage, dict):
        return {}
    return {
        k: v
        for k, v in usage.items()
        if "token" in k.lower() and isinstance(v, (int, float))
    }


async def one_turn(options: ClaudeAgentOptions, prompt: str) -> dict[str, Any]:
    init_id: str | None = None
    result: ResultMessage | None = None
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage) and init_id is None:
                init_id = (msg.data or {}).get("session_id")
            if isinstance(msg, ResultMessage):
                result = msg
    cost = result.total_cost_usd if result else None
    usage = result.usage if result else None
    return {
        "init_id": init_id,
        # `repr` deliberately: 0 and 0.0 and None are three different answers
        # and the whole question is which one this is.
        "cost_repr": repr(cost),
        "cost_is_none": cost is None,
        "cost_is_zero": cost == 0,
        "tokens": _tokens(usage),
        "model_usage_keys": sorted(result.model_usage) if result and result.model_usage else [],
        "subtype": result.subtype if result else None,
    }


def _report(label: str, out: dict[str, Any]) -> None:
    print(f"  {label}")
    print(f"    init session id : {out['init_id']}")
    print(f"    total_cost_usd  : {out['cost_repr']}")
    print(f"    usage tokens    : {out['tokens'] or '(none)'}")
    print(f"    model_usage     : {out['model_usage_keys'] or '(empty)'}")
    print(f"    subtype         : {out['subtype']}")


# ---------------------------------------------------------------- proxy
class WireLog:
    def __init__(self) -> None:
        self.session_headers: list[str | None] = []
        self.calls = 0
        self.errors: list[str] = []


def _make_proxy(log: WireLog):  # noqa: ANN202
    """Forwards VERBATIM. The previous probe injected `x-api-key` when absent
    and that is exactly the kind of difference that could explain the zero, so
    this one changes nothing except the `host` header."""
    import httpx

    async def app(scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
        }
        path = scope["path"]
        if scope.get("query_string"):
            path += "?" + scope["query_string"].decode("latin-1")
        if scope["method"] == "POST":
            log.calls += 1
            log.session_headers.append(headers.get("x-claude-code-session-id"))

        forward = {k: v for k, v in headers.items() if k not in ("host", "content-length")}
        try:
            async with httpx.AsyncClient(timeout=120.0) as up:
                async with up.stream(
                    scope["method"], UPSTREAM + path, content=body, headers=forward
                ) as resp:
                    out = [
                        (k.encode("latin-1"), v.encode("latin-1"))
                        for k, v in resp.headers.items()
                        if k.lower()
                        not in ("content-length", "content-encoding", "transfer-encoding")
                    ]
                    await send(
                        {"type": "http.response.start", "status": resp.status_code, "headers": out}
                    )
                    async for chunk in resp.aiter_raw():
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception as exc:  # noqa: BLE001
            log.errors.append(f"{type(exc).__name__}: {exc}")
            await send({"type": "http.response.start", "status": 502, "headers": []})
            await send({"type": "http.response.body", "body": b"proxy failure"})

    return app


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"API key loaded: {key[:8]}...{key[-4:]}   model={MODEL}")

    import uvicorn

    with tempfile.TemporaryDirectory(prefix="gwcost_") as td:
        root = Path(td)

        # ---- C1: direct -------------------------------------------------
        rule("C1 -- direct to the API, CLI-generated id (the baseline)")
        ws1 = root / "c1"
        ws1.mkdir()
        try:
            c1 = await one_turn(base_options(ws1), "Reply with only: ONE")
            _report("direct", c1)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            record("C1", f"RAISED {type(exc).__name__}: {exc}")
            return

        # ---- C2: through the proxy --------------------------------------
        rule("C2 -- through a verbatim-forwarding proxy, CLI-generated id")
        log = WireLog()
        config = uvicorn.Config(_make_proxy(log), host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        c2: dict[str, Any] | None = None
        try:
            async with asyncio.timeout(20):
                while not server.started:
                    await asyncio.sleep(0.05)
            port = server.servers[0].sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            print(f"  proxy on {base} -> {UPSTREAM}")
            ws2 = root / "c2"
            ws2.mkdir()
            c2 = await one_turn(
                base_options(ws2, env={"ANTHROPIC_BASE_URL": base}), "Reply with only: TWO"
            )
            _report("proxied", c2)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            record("C2", f"RAISED {type(exc).__name__}: {exc}")
        finally:
            server.should_exit = True
            with contextlib.suppress(Exception):
                async with asyncio.timeout(10):
                    await task

        seen = [h for h in log.session_headers if h]
        print(f"    POSTs seen by proxy : {log.calls}")
        print(f"    wire session ids    : {sorted(set(seen)) or '(header absent)'}")
        if log.errors:
            print(f"    proxy errors        : {log.errors[:3]}")

        # ---- C3: base URL set, no proxy in the path ----------------------
        rule("C3 -- ANTHROPIC_BASE_URL set explicitly to the real API host")
        ws3 = root / "c3"
        ws3.mkdir()
        try:
            c3 = await one_turn(
                base_options(ws3, env={"ANTHROPIC_BASE_URL": UPSTREAM}),
                "Reply with only: THREE",
            )
            _report("base URL set, no proxy", c3)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            c3 = None
            record("C3", f"RAISED {type(exc).__name__}: {exc}")

    # ---- verdicts --------------------------------------------------------
    record(
        "C1",
        f"direct: cost={c1['cost_repr']}, tokens={bool(c1['tokens'])}, "
        f"model_usage={bool(c1['model_usage_keys'])}",
    )
    if c2:
        record(
            "C2-cost",
            f"proxied: cost={c2['cost_repr']} (is_zero={c2['cost_is_zero']}, "
            f"is_none={c2['cost_is_none']}); usage tokens still reported="
            f"{bool(c2['tokens'])} {c2['tokens']}; model_usage={c2['model_usage_keys']}",
        )
        record(
            "C2-wire",
            f"CLI-generated init id={c2['init_id']}; wire x-claude-code-session-id="
            f"{sorted(set(h for h in log.session_headers if h))}; equal="
            f"{set(h for h in log.session_headers if h) == {c2['init_id']}}",
        )
    if c3:
        record(
            "C3",
            f"base URL set to the real host, no proxy: cost={c3['cost_repr']} "
            f"(is_zero={c3['cost_is_zero']}) -- isolates the override from the proxy",
        )

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")


if __name__ == "__main__":
    asyncio.run(main())
