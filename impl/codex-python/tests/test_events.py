"""The Codex event mapper, tested against the SDK's REAL types.

No network, no app-server, no credential, no container. The notifications are
constructed from the installed SDK's own model classes, so a type this build
mishandles fails here rather than in a live turn -- which is the point of
`events.py` being pure.

**The registry is read from the SDK rather than restated.** A hand-written list
of method strings would pass forever while the SDK added methods underneath it,
which is the drift this suite exists to catch.
"""

from __future__ import annotations

import re

import pytest

from agent_service.events import EVENT_TYPES, event_type_for, to_agent_event


def _sdk_methods() -> set[str]:
    """Every notification method the installed SDK knows about."""
    import inspect

    from openai_codex.generated import notification_registry as registry

    return set(re.findall(r'"([a-zA-Z]+/[a-zA-Z]+)"', inspect.getsource(registry)))


class _Note:
    """A notification, structurally. The SDK's own is a slotted dataclass."""

    def __init__(self, method: str, payload: object = None) -> None:
        self.method = method
        self.payload = payload


# --- the specification's closed enum ----------------------------------------


def test_every_sdk_method_maps_to_a_valid_event_type() -> None:
    """**The load-bearing test.** `AgentEvent.type` is a CLOSED enum in the
    published document, so emitting anything outside it is a specification
    violation, not a cosmetic bug.

    Driven from the SDK's registry, so a method added by a dependency bump is
    caught here -- as `unknown`, which is fine -- rather than by a consumer.
    """
    methods = _sdk_methods()
    assert methods, "read no methods from the SDK registry; the source shape changed"

    for method in sorted(methods):
        etype, _ = event_type_for(_Note(method))
        assert etype in EVENT_TYPES, f"{method} produced {etype!r}"


def test_an_unknown_method_is_unknown_and_keeps_its_name() -> None:
    """Forward compatibility, and it must not raise.

    The SDK ships an `UnknownNotification` of its own, so new methods are
    expected. A build that crashed on one would be broken by a dependency bump
    it did not ask for.
    """
    etype, subtype = event_type_for(_Note("something/inventedLater"))
    assert etype == "unknown"
    assert subtype == "something/inventedLater"


def test_a_malformed_notification_does_not_raise() -> None:
    """An event that cannot be understood must still be reportable -- losing it
    would lose the turn it belongs to."""
    assert event_type_for(_Note(None)) == ("unknown", None)  # type: ignore[arg-type]
    assert event_type_for(object()) == ("unknown", None)


# --- the tool loop ----------------------------------------------------------


def test_item_notifications_are_classified_by_their_item_kind() -> None:
    """Codex reports the tool loop as items; the enum has no `tool` member.

    Everything that is not plainly the user's is the agent acting, so it is
    `assistant` with the item kind in `subtype`. Uses the SDK's real item
    classes, so a rename upstream fails here.
    """
    from openai_codex.generated.v2_all import (
        AgentMessageThreadItem,
        CommandExecutionThreadItem,
        UserMessageThreadItem,
    )

    class _Payload:
        def __init__(self, item: object) -> None:
            self.item = item

    cases = [
        (UserMessageThreadItem, "user", "UserMessageThreadItem"),
        (AgentMessageThreadItem, "assistant", "AgentMessageThreadItem"),
        (CommandExecutionThreadItem, "assistant", "CommandExecutionThreadItem"),
    ]
    for cls, expected_type, expected_kind in cases:
        item = cls.model_construct()
        etype, subtype = event_type_for(_Note("item/completed", _Payload(item)))
        assert etype == expected_type, f"{expected_kind} -> {etype}"
        assert subtype == f"{expected_kind}.completed"


def test_started_and_completed_are_distinguishable() -> None:
    """A caller watching a long CommandExecution needs to know it began, so the
    two phases are not collapsed."""
    from openai_codex.generated.v2_all import CommandExecutionThreadItem

    class _Payload:
        def __init__(self, item: object) -> None:
            self.item = item

    payload = _Payload(CommandExecutionThreadItem.model_construct())
    _, started = event_type_for(_Note("item/started", payload))
    _, completed = event_type_for(_Note("item/completed", payload))
    assert started.endswith(".started")
    assert completed.endswith(".completed")
    assert started != completed


def test_an_item_notification_without_an_item_is_unknown_not_a_crash() -> None:
    etype, subtype = event_type_for(_Note("item/completed", object()))
    assert etype == "unknown"
    assert subtype == "item/completed"


# --- the categories the specification cares about ---------------------------


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("turn/completed", "result"),
        ("turn/started", "system"),
        ("thread/started", "system"),
        ("process/outputDelta", "stream_event"),
    ],
)
def test_the_load_bearing_methods_land_where_the_spec_expects(
    method: str, expected: str
) -> None:
    """`turn/completed` is the terminal event a turn's result comes from, so
    misfiling it would break every route that waits for one."""
    assert event_type_for(_Note(method))[0] == expected


def test_rate_limits_land_on_the_rate_limit_member() -> None:
    """The member exists because the Claude SDK needed it, and Codex needs it
    too -- matched by prefix so both spellings the SDK has used land here."""
    assert event_type_for(_Note("account/rateLimitsUpdated"))[0] == "rate_limit"


# --- the AgentEvent envelope ------------------------------------------------


def test_to_agent_event_produces_the_published_shape() -> None:
    event = to_agent_event(_Note("turn/started"), seq=7)
    assert event["seq"] == 7
    assert event["type"] == "system"
    assert event["subtype"] == "turn/started"
    assert set(event) <= {"seq", "type", "subtype", "content", "raw"}


def test_raw_can_be_withheld() -> None:
    """`include_raw` is a per-request option in the specification, so the mapper
    must honour it rather than the caller stripping the field afterwards."""
    assert "raw" not in to_agent_event(_Note("turn/started"), 1, include_raw=False)


def test_a_payload_that_cannot_be_serialised_yields_null_raw_not_an_error() -> None:
    class _Hostile:
        def model_dump(self, **_: object) -> dict[str, object]:
            raise RuntimeError("no")

    assert to_agent_event(_Note("turn/started", _Hostile()), 1)["raw"] is None


def test_an_agent_message_fills_content_with_a_text_block() -> None:
    """CX-56: `content` was null on every event and the text lived only in `raw`.

    A client reading the field the specification names saw an empty conversation
    for a turn that had succeeded.
    """
    from agent_service.events import to_agent_event

    class _Item:
        text = "codex works"

    class _Payload:
        item = _Item()

    class _N:
        method = "item/completed"
        payload = _Payload()

    event = to_agent_event(_N(), 0)
    assert event["content"] == [{"type": "text", "text": "codex works"}]


def test_an_event_with_no_text_reports_no_content_rather_than_empty() -> None:
    """`None`, never `[]`: nothing to say is not the same as an empty say."""
    from agent_service.events import to_agent_event

    class _N:
        method = "session/configured"
        payload = None

    assert "content" not in to_agent_event(_N(), 0)


def test_a_user_message_fills_content_from_its_blocks() -> None:
    """CX-56: the caller's own words are half the conversation.

    An `agentMessage` carries `.text`; a `userMessage` carries a list of blocks
    in `.content`. A client reading only `content` that saw the answers and not
    its own prompts would be reading half a transcript.
    """
    from agent_service.events import to_agent_event

    class _Item:
        content = [{"text": "hello", "type": "text", "text_elements": []}]

    class _Payload:
        item = _Item()

    class _N:
        method = "item/started"
        payload = _Payload()

    event = to_agent_event(_N(), 0)
    # Rebuilt, not passed through: `text_elements` is the SDK's key, not ours.
    assert event["content"] == [{"type": "text", "text": "hello"}]
