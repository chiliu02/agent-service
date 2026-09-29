from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TaskStartedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import RateLimitInfo

from agent_spec.openapi.schemas import AgentEvent
from agent_service.serialization import (
    block_to_dict,
    event_type,
    normalize,
    result_fields,
    to_jsonable,
)


def _result() -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=4967,
        duration_api_ms=7255,
        is_error=False,
        num_turns=2,
        session_id="sess-1",
        stop_reason="end_turn",
        total_cost_usd=0.157,
        usage={"input_tokens": 4},
        result="BANANA",
        terminal_reason="completed",
        permission_denials=[],
    )


def test_event_type_maps_every_known_message() -> None:
    assert event_type(SystemMessage(subtype="init", data={})) == "system"
    assert event_type(AssistantMessage(content=[], model="m")) == "assistant"
    assert event_type(UserMessage(content=[])) == "user"
    assert event_type(_result()) == "result"


def test_event_type_falls_back_for_unknown_objects() -> None:
    class Weird:
        pass

    assert event_type(Weird()) == "unknown"


def test_event_type_maps_stream_event() -> None:
    msg = StreamEvent(uuid="u1", session_id="s1", event={"type": "content_block_delta"})
    assert event_type(msg) == "stream_event"


def test_event_type_maps_rate_limit_event() -> None:
    info = RateLimitInfo(status="allowed")
    msg = RateLimitEvent(rate_limit_info=info, uuid="u1", session_id="s1")
    assert event_type(msg) == "rate_limit"


def test_thinking_block() -> None:
    block = ThinkingBlock(thinking="hmm", signature="sig")
    assert block_to_dict(block) == {
        "type": "thinking",
        "thinking": "hmm",
        "signature": "sig",
    }


def test_server_tool_use_block() -> None:
    block = ServerToolUseBlock(id="t1", name="web_search", input={"query": "cats"})
    assert block_to_dict(block) == {
        "type": "server_tool_use",
        "id": "t1",
        "name": "web_search",
        "input": {"query": "cats"},
    }


def test_server_tool_result_block() -> None:
    block = ServerToolResultBlock(tool_use_id="t1", content={"results": []})
    assert block_to_dict(block) == {
        "type": "server_tool_result",
        "tool_use_id": "t1",
        "content": {"results": []},
    }


def test_to_jsonable_unserializable_fallback_does_not_raise() -> None:
    class Thing:
        def __repr__(self) -> str:
            return "Thing(secret=42)"

    out = to_jsonable(Thing())
    assert out == {"_unserializable": "Thing(secret=42)"}


def test_event_type_resolves_system_message_subclass_via_mro() -> None:
    # TaskStartedMessage subclasses SystemMessage (0.2.128); its own docstring says
    # existing `isinstance(msg, SystemMessage)` checks continue to match, so
    # event_type must resolve it to "system" too, not "unknown" (Finding 1).
    msg = TaskStartedMessage(
        subtype="task_started",
        data={},
        task_id="task-1",
        description="do the thing",
        uuid="uuid-1",
        session_id="sess-1",
    )
    assert event_type(msg) == "system"


def test_text_block() -> None:
    assert block_to_dict(TextBlock(text="hi")) == {"type": "text", "text": "hi"}


def test_tool_use_block() -> None:
    block = ToolUseBlock(id="toolu_1", name="Read", input={"file_path": "a.txt"})
    assert block_to_dict(block) == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "Read",
        "input": {"file_path": "a.txt"},
    }


def test_tool_result_block() -> None:
    block = ToolResultBlock(tool_use_id="toolu_1", content="ok", is_error=None)
    assert block_to_dict(block) == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "ok",
        "is_error": None,
    }


def test_unknown_block_does_not_raise() -> None:
    class NewBlockType:
        pass

    out = block_to_dict(NewBlockType())
    assert out["type"] == "unknown"
    assert out["_class"] == "NewBlockType"


def test_normalize_assistant_message() -> None:
    msg = AssistantMessage(
        content=[TextBlock(text="I'll read it."), ToolUseBlock(id="t1", name="Read", input={})],
        model="claude-sonnet-5",
    )
    event = normalize(msg, seq=3, include_raw=False)
    assert event["seq"] == 3
    assert event["type"] == "assistant"
    assert [c["type"] for c in event["content"]] == ["text", "tool_use"]
    assert "raw" not in event


def test_normalize_omits_session_id_entirely() -> None:
    # session_id is not uniform across messages (F6); it is a run-level value.
    event = normalize(UserMessage(content=[]), seq=1, include_raw=False)
    assert "session_id" not in event


def test_normalize_includes_raw_when_asked() -> None:
    event = normalize(SystemMessage(subtype="init", data={"session_id": "s"}), 1, True)
    assert event["raw"]["subtype"] == "init"
    assert event["raw"]["data"]["session_id"] == "s"


def test_normalize_system_message_has_no_content_key_value() -> None:
    event = normalize(SystemMessage(subtype="init", data={}), seq=1, include_raw=False)
    assert event["subtype"] == "init"
    assert event["content"] is None


def test_result_fields_extracts_every_documented_field() -> None:
    fields = result_fields(_result())
    assert fields["session_id"] == "sess-1"
    assert fields["result"] == "BANANA"
    assert fields["is_error"] is False
    assert fields["subtype"] == "success"
    assert fields["stop_reason"] == "end_turn"
    assert fields["terminal_reason"] == "completed"
    assert fields["num_turns"] == 2
    assert fields["total_cost_usd"] == 0.157
    assert fields["duration_ms"] == 4967
    assert fields["permission_denials"] == []


def test_result_fields_includes_structured_output_deferred_tool_use_and_uuid() -> None:
    # Finding 2: these three were present on the installed ResultMessage but missing
    # from _RESULT_FIELDS. deferred_tool_use carries the paused-run payload.
    from claude_agent_sdk import DeferredToolUse

    msg = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="sess-1",
        structured_output={"answer": 42},
        deferred_tool_use=DeferredToolUse(id="t1", name="Read", input={"file_path": "a.txt"}),
        uuid="uuid-result-1",
    )
    fields = result_fields(msg)
    assert fields["structured_output"] == {"answer": 42}
    assert fields["deferred_tool_use"] == {"id": "t1", "name": "Read", "input": {"file_path": "a.txt"}}
    assert fields["uuid"] == "uuid-result-1"


def test_normalize_output_keys_stay_within_agent_event_fields() -> None:
    # normalize() is the sole producer of AgentEvent dicts, and AgentEvent(**event)
    # uses pydantic's default extra="ignore" - a key normalize() adds without a
    # matching AgentEvent field would silently vanish rather than error. This
    # catches that drift at the source instead of relying on runtime strictness
    # (Minor A of the Task 9 review: do not switch AgentEvent to extra="forbid",
    # that would turn a benign additive change into a 500).
    msg = AssistantMessage(
        content=[TextBlock(text="hi"), ToolUseBlock(id="t1", name="Read", input={})],
        model="claude-sonnet-5",
    )
    event = normalize(msg, seq=1, include_raw=True)
    assert set(event) <= set(AgentEvent.model_fields)


def test_to_jsonable_handles_paths_and_nesting() -> None:
    from pathlib import Path

    out = to_jsonable({"p": Path("/tmp/x"), "l": [TextBlock(text="t")]})
    assert out["p"] == str(Path("/tmp/x"))
    assert out["l"][0]["text"] == "t"
