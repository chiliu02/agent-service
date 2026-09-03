"""Convert claude_agent_sdk objects into JSON-safe dictionaries.

Deliberately tolerant: the message and content-block unions are both wider than
any documentation page states, so unknown types degrade to a labelled dict
rather than raising (CP-051).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

# Maps the SDK class name to the wire `type` value.
EVENT_TYPE_BY_CLASS: dict[str, str] = {
    "SystemMessage": "system",
    "AssistantMessage": "assistant",
    "UserMessage": "user",
    "ResultMessage": "result",
    "StreamEvent": "stream_event",
    "RateLimitEvent": "rate_limit",
}

_BLOCK_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "TextBlock": ("text", ("text",)),
    "ThinkingBlock": ("thinking", ("thinking", "signature")),
    "ToolUseBlock": ("tool_use", ("id", "name", "input")),
    "ToolResultBlock": ("tool_result", ("tool_use_id", "content", "is_error")),
    "ServerToolUseBlock": ("server_tool_use", ("id", "name", "input")),
    "ServerToolResultBlock": ("server_tool_result", ("tool_use_id", "content")),
}

# Fields read off ResultMessage. Every one was verified present on 0.2.128,
# but getattr keeps a renamed field from becoming a 500.
_RESULT_FIELDS: tuple[str, ...] = (
    "subtype",
    "duration_ms",
    "duration_api_ms",
    "is_error",
    "num_turns",
    "session_id",
    "stop_reason",
    "total_cost_usd",
    "usage",
    "result",
    "model_usage",
    "permission_denials",
    "errors",
    "api_error_status",
    "terminal_reason",
    "structured_output",
    "deferred_tool_use",
    "uuid",
)


def to_jsonable(obj: Any) -> Any:
    """Recursively convert anything the SDK yields into JSON-safe values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return {"_unserializable": repr(obj)[:500]}


def block_to_dict(block: Any) -> dict[str, Any]:
    """Normalize one content block. Unknown block types are labelled, not dropped."""
    name = type(block).__name__
    known = _BLOCK_FIELDS.get(name)
    if known is None:
        return {"type": "unknown", "_class": name, "_repr": repr(block)[:500]}
    wire_type, fields = known
    out: dict[str, Any] = {"type": wire_type}
    for field in fields:
        out[field] = to_jsonable(getattr(block, field, None))
    return out


def event_type(message: Any) -> str:
    """Dispatch by class name, walking the MRO so subclasses resolve to their base's wire type.

    The SDK defines SystemMessage subclasses (e.g. TaskStartedMessage, HookEventMessage)
    whose docstrings state that existing `isinstance(msg, SystemMessage)` checks continue
    to match. Exact-name-only dispatch would misclassify every one of them as "unknown"
    (Finding 1); walking type(message).__mro__ keeps the name-keyed table (no need to
    import SDK subclasses that may not exist across versions) while still resolving
    subclasses correctly.
    """
    for cls in type(message).__mro__:
        wire = EVENT_TYPE_BY_CLASS.get(cls.__name__)
        if wire is not None:
            return wire
    return "unknown"


def normalize(message: Any, seq: int, include_raw: bool) -> dict[str, Any]:
    """One SDK message -> one AgentEvent dict.

    No session_id: it is absent on UserMessage and nested inside SystemMessage.data,
    so it is tracked once per run rather than per event (F6).
    """
    raw_content = getattr(message, "content", None)
    if isinstance(raw_content, list):
        content: Any = [block_to_dict(b) for b in raw_content]
    elif isinstance(raw_content, str):
        content = [{"type": "text", "text": raw_content}]
    else:
        content = None

    event: dict[str, Any] = {
        "seq": seq,
        "type": event_type(message),
        "subtype": getattr(message, "subtype", None),
        "content": content,
    }
    if include_raw:
        event["raw"] = to_jsonable(message)
    return event


def result_fields(message: Any) -> dict[str, Any]:
    """Pull the run summary off a ResultMessage."""
    return {field: to_jsonable(getattr(message, field, None)) for field in _RESULT_FIELDS}
