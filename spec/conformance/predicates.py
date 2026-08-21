"""Specification clauses checkable from an OpenAPI document alone.

Three of the suite's tiers share these functions, and that sharing is the point:

1. **The document tier** (`test_spec_document.py`) runs them over the spec
   this repo publishes for the current version. No service, no Docker, no
   tokens -- it runs on every `uv run pytest`.
2. **The negative control** (`test_spec_negative_control.py`) runs the same
   functions over `spec/conformance/fixtures/openapi-0.2.0.json` and asserts the ones that must
   fail on it *do* fail. Adopted from Agent Studio's suite at specification
   sign-off, which had it when this side did not.
3. **AS-24** (`test_spec_meta.py`) proves a running service serves exactly
   the published document. That is what carries the document tier's results
   across to the live service: published ⊨ AS-7, and served == published,
   therefore served ⊨ AS-7 -- without a container in the loop.

Each predicate raises `AssertionError` naming its clause. They are deliberately
plain functions rather than tests, because the negative control needs to *call*
them and catch the failure; a predicate that only exists as a test body cannot
be run in the failing direction.

Nothing here imports `agent_service` -- the package rule, unchanged. A
predicate reads a JSON document and nothing else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Spec = dict[str, Any]

TURN_ENDPOINTS = (
    "/v1/sessions/{sid}/messages",
    "/v1/sessions/{sid}/messages/stream",
)
ONE_SHOT_ENDPOINTS = ("/v1/query", "/v1/query/stream")

# Every path Studio calls, per the specification's own route table. A published
# document that dropped one would be an AS-23 breach the moment it shipped.
REQUIRED_PATHS = (
    "/healthz",
    "/v1/capabilities",
    "/v1/query",
    "/v1/query/stream",
    "/v1/sessions",
    "/v1/sessions/{sid}",
    "/v1/sessions/{sid}/interrupt",
    "/v1/sessions/{sid}/messages",
    "/v1/sessions/{sid}/messages/stream",
)


def _schema(spec: Spec, name: str) -> dict[str, Any]:
    schemas = spec["components"]["schemas"]
    assert name in schemas, f"component schema {name} is absent from the document"
    return schemas[name]


def _properties(spec: Spec, name: str) -> dict[str, Any]:
    return _schema(spec, name).get("properties", {})


def _is_nullable(field: dict[str, Any]) -> bool:
    """Pydantic v2 emits `anyOf: [{...}, {type: null}]`, not `nullable: true`."""
    if "anyOf" in field:
        return any(member.get("type") == "null" for member in field["anyOf"])
    return field.get("type") == "null"


def _response_headers(spec: Spec, path: str) -> dict[str, Any]:
    return spec["paths"][path]["post"]["responses"]["200"].get("headers", {})


# --------------------------------------------------------------------------
# The predicates. One per clause; the docstring is the clause, near enough.
# --------------------------------------------------------------------------


def as1_capabilities_publishes_two_separate_arrays(spec: Spec) -> None:
    """AS-1: `credential_sources` and `provider_selectors`, as separate arrays."""
    props = _properties(spec, "Capabilities")
    for field in ("credential_sources", "provider_selectors"):
        assert field in props, f"AS-1: Capabilities does not publish {field}"
        assert props[field].get("type") == "array", (
            f"AS-1: Capabilities.{field} is not an array"
        )
    required = _schema(spec, "Capabilities").get("required", [])
    for field in ("credential_sources", "provider_selectors"):
        assert field in required, (
            f"AS-1: Capabilities.{field} is optional, so a response may omit it"
        )


def as5_capabilities_publishes_the_cap_and_the_boot_gates(spec: Spec) -> None:
    """AS-5: `max_sessions`, `require_credentials`, `require_mounts`."""
    props = _properties(spec, "Capabilities")
    for field in ("max_sessions", "require_credentials", "require_mounts"):
        assert field in props, f"AS-5: Capabilities does not publish {field}"


def as7_the_header_is_declared_on_both_turn_endpoints(spec: Spec) -> None:
    """AS-7: `x-sdk-session-id` on the 200 of both session-turn endpoints."""
    for path in TURN_ENDPOINTS:
        headers = _response_headers(spec, path)
        assert "x-sdk-session-id" in headers, (
            f"AS-7: {path} does not declare x-sdk-session-id on its 200"
        )


def as8_the_header_declaration_states_the_first_turn_case(spec: Spec) -> None:
    """AS-8: the declaration says the header is present on the FIRST turn.

    A documentation clause, checked as documentation -- deliberately, and the
    reason is on the record: Studio reached the opposite conclusion from the
    same surface and wrote an SSE scanner to live without a header that was
    always there. The words are the deliverable, so the words are the check.
    """
    for path in TURN_ENDPOINTS:
        header = _response_headers(spec, path).get("x-sdk-session-id")
        # Not a redundant AS-7: a document with no header at all must fail HERE
        # too, and say so as AS-8. Without this the predicate raised KeyError,
        # which `pytest.raises(AssertionError)` would not have caught -- found
        # by the negative control on its first run.
        assert header is not None, (
            f"AS-8: {path} declares no x-sdk-session-id header, so nothing states "
            "the first-turn case"
        )
        description = header.get("description", "")
        assert "first turn" in description.lower(), (
            f"AS-8: {path}'s header declaration does not state the first-turn case"
        )


def as11_the_one_shot_routes_carry_the_id_in_the_body(spec: Spec) -> None:
    """AS-11: `RunResponse.sdk_session_id` carries the id on the one-shot routes.

    **The prohibition this predicate used to make is gone, and it was the tenth
    suite defect of one shape** (2026-08-09). It asserted that `/v1/query*` must
    **not** declare `x-sdk-session-id` -- a rule generalised out of one SDK's
    timing: the Claude build commits that 200 before the conversation id exists,
    so it *cannot* send the header there. The Codex build assigns the id at
    `thread_start()` and can. The clause therefore forbade a build from giving a
    consumer strictly more than the specification promises, which is not
    something a specification should forbid.

    **What replaces it is a capability, not a relaxation.** The header's presence
    on that route is governed by `Capabilities.query_reports_sdk_session_id`
    (AS-32), so a client branches on a value it reads at runtime instead of on
    which image it believes it is talking to. Exactly what 0.18.0 did to AS-13
    with `allow_supplied_sdk_session_id`: a clause two builds cannot both
    satisfy becomes conditional on a published capability rather than forked.

    **A document tier cannot check the condition itself** -- the capability's
    value is a runtime answer, not a schema -- so this asserts the field EXISTS,
    which is what makes the clause checkable at all, and
    `test_spec_capabilities.py` asserts the document and the published value agree
    against a running service.

    The body half is unchanged and was always implementation-neutral: whatever a
    build does about the header, the id is in `RunResponse`.
    """
    props = _properties(spec, "RunResponse")
    assert "sdk_session_id" in props, (
        "AS-11: RunResponse does not carry sdk_session_id in the body"
    )
    capabilities = _properties(spec, "Capabilities")
    assert "query_reports_sdk_session_id" in capabilities, (
        "AS-11/AS-32: Capabilities does not publish query_reports_sdk_session_id, "
        "so nothing tells a client whether the one-shot route sends the header"
    )


def as13_create_accepts_the_id_and_deprecates_the_old_spelling(spec: Spec) -> None:
    """AS-13: `sdk_session_id` on create; `session_id` kept, marked deprecated."""
    props = _properties(spec, "SessionCreate")
    assert "sdk_session_id" in props, "AS-13: SessionCreate does not accept sdk_session_id"
    assert "session_id" in props, (
        "AS-13: the deprecated 0.4.0 spelling session_id was removed rather than kept"
    )
    assert props["session_id"].get("deprecated") is True, (
        "AS-13: SessionCreate.session_id is not marked deprecated, so nothing tells "
        "a client to move off it"
    )


def as17_the_turn_cost_fields_are_nullable(spec: Spec) -> None:
    """AS-17: the per-turn cost fields can report `null`, never only `0`."""
    for owner, field in (
        ("RunResponse", "total_cost_usd"),
        ("RunResponse", "turn_cost_usd"),
        ("TurnRecord", "turn_cost_usd"),
    ):
        prop = _properties(spec, owner).get(field)
        assert prop is not None, f"AS-17: {owner}.{field} is absent"
        assert _is_nullable(prop), (
            f"AS-17: {owner}.{field} is not nullable, so an unpriced turn must "
            "report a number it does not have"
        )


def as17a_the_session_floor_is_required(spec: Spec) -> None:
    """AS-17a: `SessionRecord.total_cost_usd` is REQUIRED, and nullable from 0.16.0.

    **This predicate was `..._is_not_nullable` and asserted the opposite.** The
    clause was restated in 0.16.0 because it had encoded a property of the
    Claude build as a requirement on everyone: Gemini CLI and the OpenAI Agents
    SDK report token usage and no monetary figure, so an implementation on
    either could only ever have reported `0.0` -- a number that reads as *free*
    rather than as *unknown*.

    **What did NOT change is `required`**, and that is now the whole assertion.
    The field is always present, so `null` means "this build cannot price a
    turn" and can never mean "not told" -- the same rule `Health.database_usable`
    and `SessionRecord.agent_id` follow. A floor is still a floor for any
    implementation that reports a number.

    `sdk_session_id` below is still asserted nullable, and still in the other
    direction, so this predicate continues to check both ways: a document that
    made everything nullable would still fail on `required`.
    """
    props = _properties(spec, "SessionRecord")
    total = props.get("total_cost_usd")
    assert total is not None, "AS-17a: SessionRecord.total_cost_usd is absent"
    assert "total_cost_usd" in _schema(spec, "SessionRecord").get("required", []), (
        "AS-17a: SessionRecord.total_cost_usd is not required; it must always be "
        "present so that `null` cannot be confused with 'not told'"
    )

    sdk_id = props.get("sdk_session_id")
    assert sdk_id is not None, "AS-17a: SessionRecord.sdk_session_id is absent"
    assert _is_nullable(sdk_id), (
        "AS-17a: SessionRecord.sdk_session_id is not nullable, but a session that "
        "has taken no turn has no SDK id to report"
    )


def as23_every_route_the_contract_names_is_present(spec: Spec) -> None:
    """AS-23: additive only. A route disappearing is the breach this catches."""
    for path in REQUIRED_PATHS:
        assert path in spec["paths"], f"AS-23: {path} is absent from the document"


PREDICATES: dict[str, Callable[[Spec], None]] = {
    "AS-1": as1_capabilities_publishes_two_separate_arrays,
    "AS-5": as5_capabilities_publishes_the_cap_and_the_boot_gates,
    "AS-7": as7_the_header_is_declared_on_both_turn_endpoints,
    "AS-8": as8_the_header_declaration_states_the_first_turn_case,
    "AS-11": as11_the_one_shot_routes_carry_the_id_in_the_body,
    "AS-13": as13_create_accepts_the_id_and_deprecates_the_old_spelling,
    "AS-17": as17_the_turn_cost_fields_are_nullable,
    "AS-17a": as17a_the_session_floor_is_required,
    "AS-23": as23_every_route_the_contract_names_is_present,
}


# --------------------------------------------------------------------------
# AS-31: containment against the core document.
#
# **Deliberately a SECOND implementation of this walk.** `agent_spec.openapi.core`
# has one, and it is the one that GENERATES `openapi-<version>-core.json`. A conformance
# suite that imported it would be checking a generated artifact with the
# generator's own code, so a bug in the intersection would be invisible from both
# sides -- the same reason the negative control runs against a real 0.2.0 document
# rather than a mutated copy of the current one.
#
# It also keeps this package's one hard rule: pytest, httpx, and nothing else.
# Twenty-five lines of dict walking is a smaller price than a dependency on the
# thing under test.
# --------------------------------------------------------------------------

#: Keys whose values a client never executes, so two implementations may differ.
PROSE_KEYS = frozenset({"summary", "description", "title", "example", "examples"})


def _strip_prose(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_prose(v) for k, v in node.items() if k not in PROSE_KEYS}
    if isinstance(node, list):
        return [_strip_prose(v) for v in node]
    return node


def document_leaves(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every scalar in a document, as `(dotted.path, value)`."""
    if isinstance(node, dict):
        out: list[tuple[str, Any]] = []
        for key, value in node.items():
            out.extend(document_leaves(value, f"{path}.{key}"))
        return out
    if isinstance(node, list):
        out = []
        for index, value in enumerate(node):
            out.extend(document_leaves(value, f"{path}[{index}]"))
        return out
    return [(path, node)]


def core_failures(document: Spec, core: Spec) -> list[str]:
    """Where `document` fails to contain `core` (AS-31). Empty means conforming.

    **One-directional.** An implementation may add a status code or a header and
    AS-31 permits it; extras are AS-32's business. What it may not do is lack or
    contradict anything the core states.
    """
    present = dict(document_leaves(_strip_prose(document)))
    failures: list[str] = []
    for path, expected in document_leaves(core):
        if path not in present:
            failures.append(f"missing {path} (core says {expected!r})")
        elif present[path] != expected:
            failures.append(f"{path} is {present[path]!r}, core says {expected!r}")
    return failures
