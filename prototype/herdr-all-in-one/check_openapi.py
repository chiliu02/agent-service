"""Drive a running container and check every answer against THIS prototype's openapi.json.

    uv run --no-project --with jsonschema --with httpx python check_openapi.py http://localhost:18480 [kind ...]

For each call: the status must be one the document declares for that operation, and the body must
validate against the schema declared for that status. Also: the served `/openapi.json` is this
directory's file byte for byte, and `/v1/schemas/run-options` is itself a valid 2020-12 schema.
It takes turns, so run it against the stub model (PROTO_STUB=1) unless spending is intended.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
DOC = json.loads((HERE / "openapi.json").read_text(encoding="utf-8"))
BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:18480"
KINDS = sys.argv[2:] or ["claude", "codex", "gemini", "pi"]
RESULTS: list[tuple[bool, str]] = []


def operation(method: str, path: str) -> tuple[str, dict] | None:
    for template, ops in DOC["paths"].items():
        rx = "^" + re.sub(r"\{[^/]+\}", "[^/]+", template) + "$"
        if re.match(rx, path.split("?")[0]) and method.lower() in ops:
            return template, ops[method.lower()]
    return None


def schema_for(ref_holder: dict) -> dict:
    """A validator root: the whole document, so `#/components/...` resolves, plus the schema."""
    return {**{k: v for k, v in DOC.items() if k != "paths"}, **ref_holder}


def check(label: str, method: str, path: str, **kw) -> httpx.Response:
    r = httpx.request(method, BASE + path, timeout=kw.pop("timeout", 300), **kw)
    found = operation(method, path)
    problems = []
    if not found:
        problems.append("route not in the document")
    else:
        template, op = found
        declared = op.get("responses", {})
        spec = declared.get(str(r.status_code))
        if spec is None:
            problems.append(f"status {r.status_code} not declared (declared: {sorted(declared)})")
        elif spec.get("content") and r.content:
            ctype = r.headers.get("content-type", "").split(";")[0]
            media = spec["content"].get(ctype) or next(iter(spec["content"].values()))
            sch = media.get("schema") if isinstance(media, dict) else None
            if sch:
                errs = sorted(Draft202012Validator(schema_for(sch)).iter_errors(r.json()), key=lambda e: e.path)
                problems += [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:160]}" for e in errs[:5]]
    ok = not problems
    RESULTS.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'} {label:<44} {method} {path.split('?')[0]} -> {r.status_code}")
    for p in problems:
        print(f"       {p}")
    return r


def must(cond: bool, label: str, detail: str = "") -> None:
    RESULTS.append((cond, label))
    print(f"{'PASS' if cond else 'FAIL'} {label}{'  ' + detail if detail and not cond else ''}")


def main() -> None:
    served = httpx.get(BASE + "/openapi.json", timeout=30).content
    must(served == (HERE / "openapi.json").read_bytes(), "served /openapi.json is this directory's file")
    check("healthz", "GET", "/healthz")
    dep = check("deployment", "GET", "/v1/deployment").json()
    must(dep["service"]["spec"]["document_version"] == DOC["info"]["version"], "document_version matches info.version")
    r = check("run-options schema", "GET", "/v1/schemas/run-options")
    try:
        Draft202012Validator.check_schema(r.json())
        must(True, "run-options is a valid 2020-12 schema")
    except Exception as e:  # noqa: BLE001
        must(False, "run-options is a valid 2020-12 schema", repr(e)[:200])
    check("list sessions", "GET", "/v1/sessions")
    check("422: options not an object", "POST", "/v1/sessions", json={"options": "x"})
    check("422: unknown option", "POST", "/v1/sessions", json={"options": {"nope": 1}})
    check("400: unsupported option", "POST", "/v1/sessions", json={"options": {"max_turns": 3}})
    check("400: unknown permission mode", "POST", "/v1/sessions", json={"options": {"permission_mode": "zzz"}})
    check("400: non-UUID sdk_session_id", "POST", "/v1/sessions", json={"sdk_session_id": "nope"})
    check("404: unknown session", "GET", f"/v1/sessions/{uuid.uuid4().hex}")
    check("404: unknown run", "GET", f"/v1/runs/{uuid.uuid4().hex}")
    check("501: query stream", "POST", "/v1/query/stream", json={"prompt": "x"})

    for i, kind in enumerate(KINDS):
        cwd = f"/work/wt-{'abcd'[i % 4]}"
        r = check(f"[{kind}] open", "POST", "/v1/sessions", json={"options": {"agent_kind": kind, "working_directory": cwd}})
        if r.status_code != 201:
            continue
        sid = r.json()["session_id"]
        check(f"[{kind}] 409: same worktree", "POST", "/v1/sessions",
              json={"options": {"agent_kind": kind, "working_directory": cwd}})
        check(f"[{kind}] get", "GET", f"/v1/sessions/{sid}")
        check(f"[{kind}] interrupt idle", "POST", f"/v1/sessions/{sid}/interrupt")
        check(f"[{kind}] 501: messages stream", "POST", f"/v1/sessions/{sid}/messages/stream", json={"prompt": "x"})
        check(f"[{kind}] 422: bad run_id", "POST", f"/v1/sessions/{sid}/messages", json={"prompt": "x", "run_id": "a b"})
        run_id = str(uuid.uuid4())
        t = check(f"[{kind}] turn", "POST", f"/v1/sessions/{sid}/messages",
                  json={"prompt": "Reply with exactly this line and nothing else: PROTO-REPLY hello", "run_id": run_id})
        if t.status_code == 200:
            body = t.json()
            must(t.headers.get("x-sdk-session-id") == body["sdk_session_id"],
                 f"[{kind}] x-sdk-session-id matches the body", f"{t.headers.get('x-sdk-session-id')} vs {body['sdk_session_id']}")
        check(f"[{kind}] 409: run_id reused", "POST", f"/v1/sessions/{sid}/messages", json={"prompt": "x", "run_id": run_id})
        check(f"[{kind}] run", "GET", f"/v1/runs/{run_id}")
        check(f"[{kind}] transcript", "GET", f"/v1/sessions/{sid}/transcript")
        model = {"claude": "claude-haiku-4-5", "codex": "gpt-5-mini", "gemini": "gemini-2.5-flash",
                 "pi": "claude-haiku-4-5"}[kind]
        p = check(f"[{kind}] patch model", "PATCH", f"/v1/sessions/{sid}", json={"model": model})
        if p.status_code == 200:
            must(p.json()["model"] == model, f"[{kind}] patched model reads back", str(p.json().get("model")))
            t2 = check(f"[{kind}] turn after patch", "POST", f"/v1/sessions/{sid}/messages",
                       json={"prompt": "Reply with exactly this line and nothing else: PROTO-REPLY patched"})
            if t2.status_code == 200:
                must(t2.json()["sdk_session_id"] == body["sdk_session_id"], f"[{kind}] patch kept the conversation",
                     f"{t2.json()['sdk_session_id']} vs {body['sdk_session_id']}")
        check(f"[{kind}] delete", "DELETE", f"/v1/sessions/{sid}")
        check(f"[{kind}] 404 after delete", "GET", f"/v1/sessions/{sid}")
    q = check("query (one-shot)", "POST", "/v1/query",
              json={"prompt": "Reply with exactly this line and nothing else: PROTO-REPLY query"})
    must(q.status_code == 200, "query answered")
    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} pass, {len(failed)} fail")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
