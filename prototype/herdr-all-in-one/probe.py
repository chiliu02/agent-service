"""Drive the shim through what Agent Harness's relay does today, once per CLI.

usage: python probe.py <base-url> [kind ...]      (kinds default to all four)

Each step prints PASS / FAIL / GAP and one line of evidence. The sequence is
Harness's: deployment, open, session read, a turn by run_id (stream first, as
Harness does, then the blocking route), the run read back, the transcript, a
duplicate run_id, interrupt, close, and a resume in a fresh session.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1].rstrip("/")
KINDS = sys.argv[2:] or ["claude", "codex", "gemini", "pi"]
WORKTREE = {"claude": "/work/wt-a", "codex": "/work/wt-b", "gemini": "/work/wt-c", "pi": "/work/wt-d"}
RESULTS: list[tuple[str, str, str, str]] = []


def call(method, path, body=None, timeout=600):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def note(kind, step, verdict, evidence):
    RESULTS.append((kind, step, verdict, evidence))
    print(f"[{kind:6}] {verdict:4} {step:28} {evidence}", flush=True)


def probe(kind):
    cwd = WORKTREE[kind]
    st, dep = call("GET", "/v1/deployment")
    note(kind, "GET /v1/deployment", "PASS" if st == 200 and dep["behaviour"]["streaming"] is False else "FAIL",
         f"{st} streaming={dep.get('behaviour', {}).get('streaming')} unsupported={[u['field'] for u in dep['accepts']['unsupported_options']]}")

    t = time.time()
    st, s = call("POST", "/v1/sessions", {"options": {"agent_kind": kind, "working_directory": cwd,
                                                      "system_prompt": f"You are the {kind} developer."}})
    if st != 201:
        note(kind, "POST /v1/sessions", "FAIL", f"{st} {s}")
        return
    sid = s["session_id"]
    ready = s["herdr"]["agent_status"]
    note(kind, "POST /v1/sessions", "PASS" if ready in ("idle", "done") else "FAIL",
         f"{st} in {time.time() - t:.1f}s agent_status={ready} sdk_session_id={s['sdk_session_id']}")
    if ready == "blocked":
        note(kind, "  start screen", "INFO", json.dumps(s.get("start_screen", ""))[:300])

    st, _ = call("POST", "/v1/sessions", {"options": {"agent_kind": kind, "working_directory": cwd}})
    note(kind, "one agent per worktree", "PASS" if st == 409 else "FAIL", f"second session on {cwd} -> {st}")

    run = f"r-{kind}-{uuid.uuid4().hex[:8]}"
    st, body = call("POST", f"/v1/sessions/{sid}/messages/stream", {"prompt": "hi", "run_id": run, "on_disconnect": "continue"})
    note(kind, "POST .../messages/stream", "PASS" if st == 501 else "FAIL", f"{st} {body.get('type') if isinstance(body, dict) else body}")

    t = time.time()
    st, rr = call("POST", f"/v1/sessions/{sid}/messages", {"prompt": "Reply with exactly this line and nothing else: PROTO-REPLY hello", "run_id": run,
                                                            "on_disconnect": "continue"})
    ok = st == 200 and rr and rr.get("result") and "PROTO-REPLY" in rr["result"]
    src = next((e["subtype"] for e in (rr or {}).get("events", []) if e["type"] == "assistant"), None)
    note(kind, "POST .../messages", "PASS" if ok else "FAIL",
         f"{st} in {time.time() - t:.1f}s source={src} result={json.dumps((rr or {}).get('result'))[:160]}")
    if rr and not ok:
        note(kind, "  turn detail", "INFO", json.dumps(rr)[:600])

    st, sr = call("GET", f"/v1/runs/{run}")
    note(kind, "GET /v1/runs/{id}", "PASS" if st == 200 and sr["state"] == "ended" else "FAIL",
         f"{st} state={sr.get('state')} stop_kind={sr.get('stop_kind')} sdk_session_id={sr.get('sdk_session_id')}")

    st, page = call("GET", f"/v1/sessions/{sid}/transcript?limit=1000")
    note(kind, "GET .../transcript", "PASS" if st == 200 and page["events"] else "FAIL",
         f"{st} {[(e['seq'], e['type'], e['subtype']) for e in page.get('events', [])]}")

    st, body = call("POST", f"/v1/sessions/{sid}/messages", {"prompt": "again", "run_id": run})
    note(kind, "duplicate run_id", "PASS" if st == 409 and str(body.get("type", "")).endswith("/run-id-in-use") else "FAIL", f"{st}")

    st, s2 = call("GET", f"/v1/sessions/{sid}")
    note(kind, "GET /v1/sessions/{sid}", "PASS" if st == 200 else "FAIL",
         f"status={s2.get('status')} turns={s2.get('turns')} context_usage={s2.get('context_usage')}")
    cats = (s2.get("context_usage") or {}).get("categories") or []
    free = next((c["tokens"] for c in cats if c["name"].lower().startswith("free")), None)
    note(kind, "freeTokens (context_usage)", "PASS" if free is not None else "FAIL",
         f"free={free} of {(s2.get('context_usage') or {}).get('max_tokens')} model={s2.get('model')} cost={s2.get('total_cost_usd')}")
    u = (rr or {}).get("usage")
    note(kind, "usage / model_usage", "PASS" if u and u.get("output_tokens") else "FAIL",
         f"usage={u} model_usage={list(((rr or {}).get('model_usage') or {}).keys())} turn_cost={(rr or {}).get('turn_cost_usd')}")
    tu = (rr or {}).get("token_usage") or {}
    note(kind, "token_usage", "PASS" if tu.get("output_tokens") else "FAIL",
         " ".join(f"{k.replace('_tokens', '')}={v}" for k, v in tu.items()))
    note(kind, "agent_id", "PASS" if s2.get("agent_id") else "FAIL", f"SessionRecord.agent_id={s2.get('agent_id')}")
    st, at = call("GET", f"/proto/agent-transcript/{sid}".replace("/proto", "/v1/proto"))
    n = len(at.get("entries", [])) if isinstance(at, dict) else 0
    note(kind, "transcript_entries saved", "PASS" if st == 200 and n else "FAIL",
         f"{n} rows under {at.get('session_key') if isinstance(at, dict) else at}; store_error={at.get('store_error') if isinstance(at, dict) else None}")

    # interrupt: a turn under way, Esc through the socket
    run2 = f"r-{kind}-{uuid.uuid4().hex[:8]}"
    holder = {}
    th = threading.Thread(target=lambda: holder.update(r=call("POST", f"/v1/sessions/{sid}/messages",
                                                              {"prompt": "Count slowly from 1 to 200, one number per line.", "run_id": run2})))
    th.start()
    time.sleep(1.5)
    st, ir = call("POST", f"/v1/sessions/{sid}/interrupt")
    th.join(120)
    rst, rr2 = holder.get("r", (None, None))
    note(kind, "POST .../interrupt", "PASS" if st == 200 and rr2 and rr2.get("interrupted") else "FAIL",
         f"{st} {ir} -> turn {rst} interrupted={rr2 and rr2.get('interrupted')} stop_kind={rr2 and rr2.get('stop_kind')} result={json.dumps(rr2 and rr2.get('result'))[:100]}")

    sdk = call("GET", f"/v1/sessions/{sid}")[1].get("sdk_session_id")
    st, _ = call("DELETE", f"/v1/sessions/{sid}")
    note(kind, "DELETE /v1/sessions/{sid}", "PASS" if st == 204 else "FAIL", f"{st}")

    if not sdk:
        note(kind, "resume", "GAP", "no sdk_session_id was learned, so there is nothing to resume")
        return
    st, s3 = call("POST", "/v1/sessions", {"options": {"agent_kind": kind, "working_directory": cwd, "resume": sdk,
                                                       "system_prompt": f"You are the {kind} developer."}})
    if st != 201:
        note(kind, "resume", "FAIL", f"{st} {s3}")
        return
    st, rr3 = call("POST", f"/v1/sessions/{s3['session_id']}/messages", {"prompt": "Reply with exactly this line and nothing else: PROTO-REPLY resumed", "run_id": f"r-{kind}-{uuid.uuid4().hex[:8]}"})
    ok = st == 200 and rr3 and "PROTO-REPLY" in (rr3.get("result") or "")
    note(kind, "resume", "PASS" if ok else "FAIL",
         f"start={s3['herdr']['agent_status']} turn={st} sdk={rr3 and rr3.get('sdk_session_id')} result={json.dumps(rr3 and rr3.get('result'))[:100]}")
    call("DELETE", f"/v1/sessions/{s3['session_id']}")


for k in KINDS:
    try:
        probe(k)
    except Exception as e:  # noqa: BLE001
        note(k, "probe", "FAIL", repr(e))
print("\nSUMMARY")
for kind in KINDS:
    row = [r for r in RESULTS if r[0] == kind and r[2] in ("PASS", "FAIL", "GAP")]
    print(f"  {kind:6} pass={sum(r[2] == 'PASS' for r in row)} fail={sum(r[2] == 'FAIL' for r in row)} gap={sum(r[2] == 'GAP' for r in row)}")
