"""Live probe: can the SDK conversation id be known BEFORE the first turn, and
does it match what the CLI puts on the wire?

Asked by Agent Studio, request 2 (CP-134). The
relay wants to join its gateway's `x-claude-code-session-id` to a service-side
session, and today the only place that id is reachable is inside a turn's
response body. Five questions, in the order they decide the design:

X1  Is the id knowable at connect() time -- get_server_info(), or any message
    arriving before the first query()?               (no inference, ~free)
X2  Does ClaudeAgentOptions.session_id (--session-id=UUID, read from the
    installed transport source) actually pin the conversation id?
X3  Is that id STABLE across several turns of one connection, on both the
    init SystemMessage and the ResultMessage?
X4  What does the CLI send as `x-claude-code-session-id` ON THE WIRE, and is it
    the same string? Measured through a local forwarding proxy pointed at by
    ANTHROPIC_BASE_URL -- this is the join key Studio actually sees, and no
    other case here can answer it.
X5  session_id + resume: rejected, as types.py claims? And with fork_session,
    which id comes back -- the requested one or a fresh one?

Costs a few cents: every prompt is "reply with one word", max_turns=2, on
claude-haiku-4-5. The plumbing under test is model-independent.

    uv run --env-file .env python spike/probe_session_id.py
    uv run --env-file .env python spike/probe_session_id.py X4    # one case

Never prints the API key. X4 forwards request bodies to the real API through an
in-process proxy bound to 127.0.0.1 and prints only header NAMES plus the one
session header's value.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import traceback
import uuid
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
    """Minimal options, mirroring the service's own shape. No tools: this probe
    is about identifiers, and a tool call is only cost."""
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


async def take_turn(client: Any, prompt: str) -> dict[str, Any]:
    """One turn. Returns the ids seen on the init and the result."""
    init_id: str | None = None
    result_id: str | None = None
    subtype: str | None = None
    cost: float | None = None
    await client.query(prompt)
    async for msg in client.receive_response():
        if isinstance(msg, SystemMessage) and init_id is None:
            init_id = (msg.data or {}).get("session_id")
        if isinstance(msg, ResultMessage):
            result_id = msg.session_id
            subtype = msg.subtype
            cost = msg.total_cost_usd
    return {"init": init_id, "result": result_id, "subtype": subtype, "cost": cost}


# ---------------------------------------------------------------- X1
async def x1_known_before_first_turn(ws: Path) -> None:
    """Is the conversation id reachable after connect() but before any turn?

    Two ways it could be: a control request that reports it (get_server_info is
    the only candidate the SDK exposes), or the CLI volunteering its init
    message on connect rather than on first query. Costs nothing: no query() is
    ever sent.
    """
    rule("X1 -- is the id knowable at connect() time, before any turn?")
    client = ClaudeSDKClient(options=base_options(ws))
    await client.connect()
    try:
        try:
            info = await client.get_server_info()
        except Exception as exc:  # noqa: BLE001
            info = f"RAISED {type(exc).__name__}: {exc}"
        if isinstance(info, dict):
            keys = sorted(info)
            print(f"  get_server_info() keys: {keys}")
            hits = {k: v for k, v in info.items() if "session" in k.lower()}
            print(f"  session-ish entries   : {hits or '(none)'}")
            info_has_id = bool(hits)
        else:
            print(f"  get_server_info() -> {info}")
            keys, info_has_id = [], False

        # Does anything arrive on the connection without a query? Bounded, so a
        # silent connection costs 5s rather than hanging.
        early: list[str] = []
        early_id: str | None = None
        try:
            async with asyncio.timeout(5):
                async for msg in client.receive_response():
                    early.append(type(msg).__name__)
                    if isinstance(msg, SystemMessage) and early_id is None:
                        early_id = (msg.data or {}).get("session_id")
                    break
        except TimeoutError:
            pass
        print(f"  messages before query(): {early or '(none within 5s)'}")
        print(f"  session_id from them   : {early_id!r}")
    finally:
        await client.disconnect()

    record(
        "X1",
        f"get_server_info carries a session id={info_has_id}; "
        f"message before first query()={early or None}; id={early_id!r}",
    )


# ---------------------------------------------------------------- X2 + X3
async def x2_x3_preassigned_and_stable(ws: Path) -> str | None:
    """Does --session-id pin the id, and does it hold across turns?

    Run together on ONE connection: X3 is X2 plus two more turns, and opening a
    second connection would only cost more for the same answer. Returns the
    pinned id so X5 has something real to resume.
    """
    rule("X2 + X3 -- does ClaudeAgentOptions.session_id pin the id, and hold?")
    wanted = str(uuid.uuid4())
    print(f"  requested session_id: {wanted}")

    turns: list[dict[str, Any]] = []
    try:
        async with ClaudeSDKClient(options=base_options(ws, session_id=wanted)) as client:
            for i, prompt in enumerate(
                ["Reply with only: ONE", "Reply with only: TWO", "Reply with only: THREE"],
                start=1,
            ):
                t = await take_turn(client, prompt)
                turns.append(t)
                print(
                    f"  turn {i}: init={t['init']} result={t['result']} "
                    f"subtype={t['subtype']} cost={t['cost']}"
                )
    except Exception as exc:  # noqa: BLE001
        record("X2", f"RAISED {type(exc).__name__}: {exc}")
        record("X3", "not reached -- X2 raised")
        return None

    ids = {t["init"] for t in turns} | {t["result"] for t in turns}
    ids.discard(None)
    honoured = ids == {wanted}
    record(
        "X2",
        f"requested={wanted}; ids reported by the CLI={sorted(ids)}; "
        f"--session-id honoured exactly={honoured}",
    )
    record(
        "X3",
        f"{len(turns)} turns on one connection reported {len(ids)} distinct id(s) "
        f"across init AND result: stable={len(ids) == 1}",
    )
    return wanted if honoured else next(iter(ids), None)


# ---------------------------------------------------------------- X4
class _WireLog:
    """Every request the CLI made, as (method, path, session-header value)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.header_names: set[str] = set()
        self.errors: list[str] = []


def _make_proxy(log: _WireLog, api_key: str):  # noqa: ANN202
    """A raw-ASGI forwarding proxy that records headers on the way past.

    Deliberately minimal and deliberately local: it exists to observe the
    `x-claude-code-session-id` header Studio's gateway sees, so it forwards the
    body untouched and streams the response back byte for byte.
    """
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

        headers: dict[str, str] = {}
        for raw_k, raw_v in scope["headers"]:
            headers[raw_k.decode("latin-1").lower()] = raw_v.decode("latin-1")
        log.header_names.update(headers)
        path = scope["path"]
        if scope.get("query_string"):
            path += "?" + scope["query_string"].decode("latin-1")
        log.calls.append(
            (scope["method"], path, headers.get("x-claude-code-session-id"))
        )

        forward = {
            k: v for k, v in headers.items() if k not in ("host", "content-length")
        }
        # The CLI is talking to a plaintext local port, so it may or may not have
        # attached the key. Make sure upstream gets one either way.
        forward.setdefault("x-api-key", api_key)

        try:
            async with httpx.AsyncClient(timeout=120.0) as up:
                async with up.stream(
                    scope["method"], UPSTREAM + path, content=body, headers=forward
                ) as resp:
                    out = [
                        (k.encode("latin-1"), v.encode("latin-1"))
                        for k, v in resp.headers.items()
                        if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")
                    ]
                    await send(
                        {"type": "http.response.start", "status": resp.status_code, "headers": out}
                    )
                    async for chunk in resp.aiter_raw():
                        await send(
                            {"type": "http.response.body", "body": chunk, "more_body": True}
                        )
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception as exc:  # noqa: BLE001
            log.errors.append(f"{type(exc).__name__}: {exc}")
            await send({"type": "http.response.start", "status": 502, "headers": []})
            await send({"type": "http.response.body", "body": b"proxy failure"})

    return app


async def x4_wire_header(ws: Path) -> None:
    """What is `x-claude-code-session-id` on the wire, and does it equal ours?

    THE case this probe exists for. Studio joins on the header its gateway sees;
    everything else here is about what the SDK reports in-process, which is only
    useful if the two are the same string.
    """
    rule("X4 -- x-claude-code-session-id on the wire, through a local proxy")
    import uvicorn

    api_key = os.environ["ANTHROPIC_API_KEY"]
    log = _WireLog()
    config = uvicorn.Config(
        _make_proxy(log, api_key), host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        # Wait for the socket to be bound so the port is knowable.
        async with asyncio.timeout(20):
            while not server.started:
                await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        print(f"  proxy listening on {base} -> {UPSTREAM}")

        wanted = str(uuid.uuid4())
        print(f"  requested session_id: {wanted}")
        options = base_options(
            ws,
            session_id=wanted,
            # Merged ON TOP of the inherited environment by the SDK, which is
            # exactly what is wanted here: everything else stays as it is.
            env={"ANTHROPIC_BASE_URL": base},
        )
        try:
            async with ClaudeSDKClient(options=options) as client:
                turn = await take_turn(client, "Reply with only: WIRE")
            err = None
        except Exception as exc:  # noqa: BLE001
            turn, err = {"init": None, "result": None, "subtype": None, "cost": None}, (
                f"{type(exc).__name__}: {exc}"
            )
        print(f"  turn: {turn}  error={err}")
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            async with asyncio.timeout(10):
                await task

    print(f"  requests seen by the proxy : {len(log.calls)}")
    for method, path, sid in log.calls:
        print(f"    {method} {path[:60]}  x-claude-code-session-id={sid}")
    if log.errors:
        print(f"  proxy errors: {log.errors[:3]}")
    session_headers = {sid for _, _, sid in log.calls if sid}
    interesting = sorted(h for h in log.header_names if "session" in h or "claude-code" in h)
    print(f"  claude-code/session headers seen: {interesting}")

    if not log.calls:
        record("X4", "INCONCLUSIVE -- the CLI made no request through the proxy "
                     f"(ANTHROPIC_BASE_URL may not be honoured). error={err}")
        return
    record(
        "X4",
        f"{len(log.calls)} upstream request(s); x-claude-code-session-id values="
        f"{sorted(session_headers) or '(header absent)'}; equals the requested id="
        f"{session_headers == {wanted}}; SDK reported init={turn['init']}",
    )


# ---------------------------------------------------------------- X5
async def x5_session_id_with_resume(ws: Path, resumable: str | None) -> None:
    """types.py says session_id cannot be combined with resume unless
    fork_session is set. Is that enforced, and where -- and what id does a fork
    actually get? This decides whether pre-assignment can be unconditional or
    has to skip the resume path.

    MUST RUN IN THE SAME `ws` AS X2. The CLI looks a transcript up per project
    directory, so a fresh cwd fails with "No conversation found with session ID"
    -- which is a lookup failure, not a verdict on the flag combination. The
    first version of this probe made exactly that mistake and measured nothing.
    """
    rule("X5 -- session_id + resume, with and without fork_session")
    if not resumable:
        record("X5", "SKIPPED -- X2 produced no usable id to resume")
        return
    print(f"  cwd (same as X2): {ws}")

    # CONTROL: plain resume, no session_id. This is what the service does today,
    # so if it fails the workspace/transcript setup is wrong and neither arm
    # below means anything.
    try:
        async with ClaudeSDKClient(options=base_options(ws, resume=resumable)) as client:
            c = await take_turn(client, "Reply with only: C")
        c_err = None
    except Exception as exc:  # noqa: BLE001
        c, c_err = None, f"{type(exc).__name__}: {exc}"
    print(f"  CONTROL (plain resume): turn={c} error={c_err}")

    fresh = str(uuid.uuid4())
    print(f"  resuming {resumable} while requesting session_id={fresh}")

    # A: no fork -- expected to be rejected.
    try:
        async with ClaudeSDKClient(
            options=base_options(ws, session_id=fresh, resume=resumable)
        ) as client:
            a = await take_turn(client, "Reply with only: A")
        a_err = None
    except Exception as exc:  # noqa: BLE001
        a, a_err = None, f"{type(exc).__name__}: {exc}"
    print(f"  A (no fork)   : turn={a} error={a_err}")

    # B: fork_session=True -- allowed per the docstring; which id comes back?
    fresh_b = str(uuid.uuid4())
    try:
        async with ClaudeSDKClient(
            options=base_options(
                ws, session_id=fresh_b, resume=resumable, fork_session=True
            )
        ) as client:
            b = await take_turn(client, "Reply with only: B")
        b_err = None
    except Exception as exc:  # noqa: BLE001
        b, b_err = None, f"{type(exc).__name__}: {exc}"
    print(f"  B (fork)      : requested={fresh_b} turn={b} error={b_err}")

    record(
        "X5",
        f"control plain resume: {'FAILED -- ' + c_err if c_err else 'ok, id=' + str((c or {}).get('init'))}; "
        f"session_id+resume without fork: {'REJECTED -- ' + a_err if a_err else 'accepted, id=' + str((a or {}).get('init'))}; "
        f"with fork_session: {'RAISED ' + b_err if b_err else 'id=' + str((b or {}).get('init')) + ' (requested ' + fresh_b + ')'}",
    )


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not found (looked in the environment and .env)")
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"API key loaded: {key[:8]}...{key[-4:]}   model={MODEL}")

    wanted = [a.upper() for a in sys.argv[1:]] or ["X1", "X2", "X4", "X5"]
    pinned: str | None = None
    with tempfile.TemporaryDirectory(prefix="sidprobe_") as td:
        root = Path(td)
        try:
            if "X1" in wanted:
                ws = root / "x1"
                ws.mkdir()
                async with asyncio.timeout(180):
                    await x1_known_before_first_turn(ws)
            if "X2" in wanted or "X3" in wanted:
                ws = root / "x2"
                ws.mkdir()
                async with asyncio.timeout(300):
                    pinned = await x2_x3_preassigned_and_stable(ws)
            if "X4" in wanted:
                ws = root / "x4"
                ws.mkdir()
                async with asyncio.timeout(300):
                    await x4_wire_header(ws)
            if "X5" in wanted:
                # THE SAME directory X2 used, deliberately -- see the docstring.
                ws = root / "x2"
                ws.mkdir(exist_ok=True)
                async with asyncio.timeout(420):
                    await x5_session_id_with_resume(ws, pinned)
        except TimeoutError:
            record("(run)", "TIMED OUT -- see the case above")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            record("(run)", "RAISED -- see the traceback above")

    rule("SUMMARY")
    for case, finding in RESULTS:
        print(f"  {case}: {finding}")


if __name__ == "__main__":
    # NOTE: never set WindowsSelectorEventLoopPolicy -- the SDK spawns a
    # subprocess and the selector loop cannot.
    asyncio.run(main())
