"""A model call to `OPENAI_BASE_URL` carries the stored login (CX-74).

**Free, and it runs a real app-server.** The endpoint is a local server that
records each request's headers and answers 401, so no byte leaves the machine
and the key is a dummy. What is asserted is the one thing a relay standing in
for OpenAI needs: an `Authorization: Bearer <the key this service logged in
with>` header on the model call.

Codex `0.163.0` stopped sending it for a custom provider, and nothing here saw
that: the unit tests check the override strings, and the conformance suite has
no model endpoint at all. A consumer's gateway found it.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from agent_spec.openapi.schemas import RunOptions

from agent_service.sessions import CodexSession, RunTimeout

pytestmark = pytest.mark.anyio

KEY = "sk-endpoint-auth-probe-not-a-real-key"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def endpoint():  # noqa: ANN201
    """A model endpoint that records headers and refuses. Forwards nothing."""
    seen: list[dict[str, str]] = []
    arrived = threading.Event()

    class _Refuse(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            if length:
                self.rfile.read(length)
            seen.append({k.lower(): v for k, v in self.headers.items()})
            arrived.set()
            body = b'{"error":{"message":"probe","type":"invalid_request_error"}}'
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST  # noqa: N815

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Refuse)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", seen, arrived
    finally:
        server.shutdown()
        server.server_close()


async def test_the_model_call_carries_the_stored_key(tmp_path, endpoint, monkeypatch) -> None:  # noqa: ANN001
    """**The header, with the key `open()` logged in with.** The variables are
    cleared so the only route the key could take is the auth store (CX-20)."""
    url, seen, arrived = endpoint
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    s = CodexSession(
        cwd=str(tmp_path / "ws"),
        codex_home=str(tmp_path / "home"),
        api_key=KEY,
        base_url=url,
    )
    await s.open(RunOptions())
    try:
        turn = asyncio.ensure_future(s.send("say hi", RunOptions(), timeout_s=60))
        # The first call is enough; the CLI's retries are not the subject.
        await asyncio.wait_for(asyncio.to_thread(arrived.wait, 60), 65)
        if not turn.done():
            await s.interrupt()
        try:
            await turn
        except RunTimeout:
            pass
    finally:
        await s.close()

    assert seen, "no model call reached the endpoint"
    assert seen[0].get("authorization") == f"Bearer {KEY}", (
        f"the model call carried {seen[0].get('authorization')!r}, not the stored key"
    )
