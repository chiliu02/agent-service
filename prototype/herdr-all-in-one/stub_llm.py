"""Stub model endpoint: answers in each provider's own wire shape and forwards
NOTHING. It lets a turn complete in every CLI with no credential.

usage: python stub_llm.py <port>

Anthropic Messages (SSE or JSON), OpenAI Responses (SSE) and Gemini
generateContent / streamGenerateContent. Each answer is
"PROTO-REPLY-<n> <first words of the last user text>", so a reader can tell
which call produced which answer. STUB_DELAY seconds (default 3) before the
answer keeps the agent in `working` long enough to be seen.
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
DELAY = float(os.environ.get("STUB_DELAY", "3"))
LOCK, N = threading.Lock(), [0]


def _texts(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, list):
        for v in o:
            yield from _texts(v)
    elif isinstance(o, dict):
        for k in ("text", "content", "parts"):
            if k in o:
                yield from _texts(o[k])


def last_user_text(body):
    for key in ("messages", "input", "contents"):
        items = body.get(key)
        if isinstance(items, list):
            for item in reversed(items):
                if isinstance(item, dict) and item.get("role") == "user":
                    text = " ".join(t for t in _texts(item) if not t.lstrip().startswith("<"))
                    if text.strip():
                        return " ".join(text.split()[:8])
    return ""


def reply_text(body):
    with LOCK:
        N[0] += 1
        n = N[0]
    return f"PROTO-REPLY-{n} {last_user_text(body)}".strip()


def sse(events, named=True):
    return "".join((f"event: {n}\n" if named else "") + f"data: {json.dumps(d)}\n\n" for n, d in events).encode()


def anthropic(body):
    text = reply_text(body)
    msg = {"id": f"msg_{time.time_ns()}", "type": "message", "role": "assistant", "model": body.get("model", "x"),
           "content": [], "stop_reason": None, "stop_sequence": None,
           "usage": {"input_tokens": 10, "output_tokens": 5}}
    if not body.get("stream"):
        msg.update(content=[{"type": "text", "text": text}], stop_reason="end_turn")
        return "application/json", json.dumps(msg).encode()
    return "text/event-stream", sse([
        ("message_start", {"type": "message_start", "message": msg}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 5}}),
        ("message_stop", {"type": "message_stop"})])


def responses(body):
    text = reply_text(body)
    rid, iid = f"resp_{time.time_ns()}", f"msg_{time.time_ns()}"
    item = {"type": "message", "id": iid, "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}
    usage = {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 5,
             "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 15}
    resp = {"id": rid, "object": "response", "status": "completed", "model": body.get("model", "x"),
            "output": [item], "usage": usage}
    return "text/event-stream", sse([
        ("response.created", {"type": "response.created", "response": {**resp, "status": "in_progress", "output": []}}),
        ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": iid, "output_index": 0, "content_index": 0, "delta": text}),
        ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
        ("response.completed", {"type": "response.completed", "response": resp})])


def gemini(path, body):
    if ":countTokens" in path:
        return "application/json", b'{"totalTokens": 1}'
    cfg = body.get("generationConfig") or {}
    if "json" in str(cfg.get("responseMimeType", "")):  # Gemini's model router wants a JSON verdict
        text = json.dumps({"reasoning": "stub", "model_choice": "flash"})
    else:
        text = reply_text(body)
    chunk = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP", "index": 0}],
             "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
             "modelVersion": "stub"}
    if ":streamGenerateContent" in path:
        return "text/event-stream", sse([("", chunk)], named=False)
    return "application/json", json.dumps(chunk).encode()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _any(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        p = self.path
        status, ctype, out = 404, "application/json", b'{"error":"stub: no such route"}'
        if isinstance(body, dict):
            if "count_tokens" in p:
                status, out = 200, b'{"input_tokens": 1}'
            elif p.startswith("/v1/messages"):
                time.sleep(DELAY)
                status, (ctype, out) = 200, anthropic(body)
            elif "/responses" in p:
                time.sleep(DELAY)
                status, (ctype, out) = 200, responses(body)
            elif "generatecontent" in p.lower() or ":countTokens" in p:
                time.sleep(DELAY)
                status, (ctype, out) = 200, gemini(p, body)
            elif p.rstrip("/").endswith("/models"):
                status, out = 200, b'{"data":[],"models":[]}'
        sys.stderr.write(f"{self.command} {p} -> {status}\n")
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
