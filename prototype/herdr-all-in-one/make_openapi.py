"""Write this prototype's own OpenAPI document: agent-service's core document, plus what Herdr needs.

    python make_openapi.py            # writes ./openapi.json beside this file
    python make_openapi.py --check    # exit 1 if ./openapi.json is not what this would write

The base is `spec/openapi/core-<version>-snapshot.json`, which is READ, never written. This
prototype is not an agent-service build and its document is not in `spec/`: it keeps the core's
paths, schemas and payload shapes so that a client written against agent-service needs as little
change as possible, and every difference is one entry in CHANGES below. The list is also put into
the document itself as `info.x-changes-from-core`, so a reader of the JSON alone sees the delta.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE_VERSION = "0.34.0-snapshot"
CORE = HERE.parents[1] / "spec" / "openapi" / f"core-{CORE_VERSION}.json"
OUT = HERE / "openapi.json"
DOCUMENT_VERSION = "0.34.0-herdr.1"  # core version it derives from, plus this prototype's revision
KINDS = ["claude", "codex", "gemini", "pi"]

P = "https://agent-service.invalid/problems/"
PROBLEM = {"$ref": "#/components/schemas/Problem"}


def problem(description: str) -> dict:
    return {"description": description, "content": {"application/problem+json": {"schema": PROBLEM}}}


CHANGES: list[str] = []


def change(text: str) -> None:
    CHANGES.append(text)


def build() -> dict:
    doc = copy.deepcopy(json.loads(CORE.read_text(encoding="utf-8")))
    paths, schemas = doc["paths"], doc["components"]["schemas"]

    doc["info"] = {
        "title": "herdr-all-in-one",
        "version": DOCUMENT_VERSION,
        "description": (
            "PROTOTYPE. One container, four agent CLIs (Claude Code, Codex, Gemini CLI, Pi) run as "
            "interactive TUIs under Herdr, behind agent-service's core API. Derived from agent-service's "
            f"core document {CORE_VERSION}; `x-changes-from-core` lists every difference. Not an "
            "agent-service build, never released, and free to change."),
        "x-derived-from": f"agent-service core {CORE_VERSION}",
    }

    # -- streaming --------------------------------------------------------------------------
    for route in ("/v1/sessions/{sid}/messages/stream", "/v1/query/stream"):
        op = paths[route]["post"]
        op["description"] = ("Not supported: always 501 with type `streaming-not-supported`. Use the "
                             "non-streaming route; watch live output with a Herdr client over SSH "
                             "(`behaviour.live_output`).")
        op["responses"] = {"501": problem(f"type `{P}streaming-not-supported`")}
    change("`POST /v1/sessions/{sid}/messages/stream` and `POST /v1/query/stream` answer only 501, "
           f"type `{P}streaming-not-supported`. The paths stay so a generated client still compiles.")

    # -- behaviour: what a client must branch on --------------------------------------------
    schemas["LiveOutput"] = {
        "type": "object",
        "description": "Where live output is watched instead of a stream: Herdr's TUI over SSH.",
        "properties": {
            "kind": {"type": "string", "const": "herdr-over-ssh"},
            "ssh_port": {"type": "integer", "description": "Port inside the container."},
            "ssh_user": {"type": "string"},
            "herdr_version": {"type": "string"},
            "herdr_protocol": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
        "required": ["kind", "ssh_port", "ssh_user", "herdr_version", "herdr_protocol"],
    }
    b = schemas["Behaviour"]
    b["properties"].update({
        "streaming": {"type": "boolean", "const": False,
                      "description": "Always false: the two `/stream` routes answer 501."},
        "live_output": {"$ref": "#/components/schemas/LiveOutput"},
        "agent_kinds": {"type": "array", "items": {"type": "string", "enum": KINDS},
                        "description": "The CLIs this container can run; `options.agent_kind` picks one."},
        "default_agent_kind": {"type": "string", "enum": KINDS,
                               "description": "The CLI a session gets without `options.agent_kind`. "
                                              "`accepts` and `behaviour` describe THIS CLI."},
        "token_usage_input_includes_cache": {
            "type": "boolean", "const": False,
            "description": "`token_usage.input_tokens` excludes the cache counts, for every CLI, so "
                           "input + cache_read + cache_write is the prompt total."},
        "result_source": {"type": "string", "enum": ["transcript-then-screen", "screen"],
                          "description": "Where a turn's `result` text comes from."},
    })
    b["required"] = sorted(set(b["required"]) | {"streaming", "live_output", "agent_kinds", "default_agent_kind",
                                                  "token_usage_input_includes_cache", "result_source"})
    change("`Behaviour` gains `streaming` (always false), `live_output` (new schema `LiveOutput`: SSH port, "
           "user and Herdr version), `agent_kinds`, `default_agent_kind`, "
           "`token_usage_input_includes_cache` (always false) and `result_source`. All required.")

    # -- which CLI a session gets -----------------------------------------------------------
    ro = schemas["RunOptions"]
    ro["properties"]["agent_kind"] = {
        "anyOf": [{"type": "string", "enum": KINDS}, {"type": "null"}],
        "description": "Which CLI runs this session. Omitted: `behaviour.default_agent_kind`. Fixed for the "
                       "session's life; resume with the same kind."}
    change("`RunOptions` gains `agent_kind` (one of " + ", ".join(KINDS) + ", or null).")

    # -- the session record says where to look over SSH -------------------------------------
    schemas["HerdrPane"] = {
        "type": "object",
        "description": "Where this session's agent is in Herdr, for a client attached over SSH.",
        "properties": {
            "agent": {"type": "string", "description": "Herdr's agent name, for `herdr agent attach`."},
            "pane_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "workspace_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "kind": {"type": "string", "enum": KINDS},
            "agent_status": {"anyOf": [{"type": "string"}, {"type": "null"}],
                             "description": "Herdr's last reading: idle, working, blocked, done, unknown."},
            "transcript_path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "transcript_key": {"anyOf": [{"type": "string"}, {"type": "null"}],
                               "description": "`transcript_entries.session_key` of the agent's own record."},
            "transcript_rows_saved": {"type": "integer"},
        },
        "required": ["agent", "pane_id", "workspace_id", "kind", "agent_status"],
    }
    schemas["SessionRecord"]["properties"]["herdr"] = {"$ref": "#/components/schemas/HerdrPane"}
    change("`SessionRecord` gains optional `herdr` (new schema `HerdrPane`).")

    # -- statuses the core does not declare on these routes ---------------------------------
    create = paths["/v1/sessions"]["post"]["responses"]
    create["409"] = problem(f"type `{P}worktree-in-use`: another open session holds the working directory.")
    create["502"] = problem(f"type `{P}herdr`: Herdr refused to start the agent.")
    q = paths["/v1/query"]["post"]["responses"]
    q["409"] = problem(f"type `{P}worktree-in-use`.")
    q["429"] = problem("The one-shot opens a real session, so it competes for `max_sessions`.")
    patch = paths["/v1/sessions/{sid}"]["patch"]
    patch["description"] = ("Restarts the agent's TUI with the new options, resuming its conversation. "
                            "Takes as long as opening a session.")
    patch["responses"]["409"] = problem(f"type `{P}session-busy`: a turn is under way.")
    patch["responses"]["502"] = problem(f"type `{P}herdr`: Herdr refused to restart the agent.")
    change("`POST /v1/sessions` adds 409 (`worktree-in-use`: one agent per working directory) and 502 "
           "(`herdr`). `POST /v1/query` adds 409 and 429 (it uses a session slot). `PATCH "
           "/v1/sessions/{sid}` adds 409 (`session-busy`) and 502, and restarts the TUI to apply.")

    # -- the core's normaliser drops every `title` key, including the PROPERTY called title --
    for name in ("Problem", "ValidationProblem"):
        schemas[name].setdefault("properties", {})["title"] = {"type": "string"}
    change("`Problem` and `ValidationProblem` declare the `title` property they already require. The core "
           "document's normaliser removes every `title` key, which removed this property too.")

    # -- prototype-only routes --------------------------------------------------------------
    paths["/v1/proto/agent-transcript/{sid}"] = {"get": {
        "tags": ["prototype"], "operationId": "proto_agent_transcript",
        "description": "The agent's OWN transcript lines, as saved in `transcript_entries`.",
        "parameters": [{"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}},
                       {"name": "after", "in": "query", "schema": {"type": "integer", "default": 0}},
                       {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 1000}}],
        "responses": {"200": {"content": {"application/json": {"schema": {
            "type": "object", "required": ["session_key", "entries", "persisted", "store_error"],
            "properties": {"session_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                           "entries": {"type": "array", "items": {"type": "object"}},
                           "persisted": {"type": "boolean"},
                           "store_error": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}}}},
                      "404": problem("No such session.")}}}
    paths["/v1/proto/socket-log"] = {"get": {
        "tags": ["prototype"], "operationId": "proto_socket_log",
        "description": "The last Herdr socket calls the shim made, for evaluation.",
        "responses": {"200": {"content": {"application/json": {"schema": {
            "type": "object", "required": ["calls"],
            "properties": {"calls": {"type": "array", "items": {"type": "object"}}}}}}}}}}
    change("Two prototype-only routes, tagged `prototype`: `GET /v1/proto/agent-transcript/{sid}` and "
           "`GET /v1/proto/socket-log`.")

    doc["info"]["x-changes-from-core"] = CHANGES
    return doc


def render() -> str:
    CHANGES.clear()
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            sys.exit(f"{OUT.name} is stale: run python make_openapi.py")
        print(f"{OUT.name} is current ({len(CHANGES)} changes from core {CORE_VERSION})")
    else:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT.name}: {len(CHANGES)} changes from core {CORE_VERSION}")
