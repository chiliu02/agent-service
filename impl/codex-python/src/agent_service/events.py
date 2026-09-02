"""Codex `Notification` -> this service's `AgentEvent`.

**Pure, and deliberately so.** Nothing here touches the SDK client, the network
or the app-server: it takes a `Notification` and returns a dict. That is what
makes the whole event surface testable without a running Codex, a credential or
a container -- which is most of the risk in this implementation, and the Claude
build learned it the hard way (its equivalent logic sits inside `sessions.py`,
where nothing can reach it without a live subprocess).

## The shape it has to hit

`AgentEvent` is `{seq, type, subtype?, content?, raw?}`, and `type` is a CLOSED
enum the specification owns:

    system | assistant | user | result | stream_event | rate_limit | unknown

That enum was written against the Claude SDK's message kinds. **It needed no
change for Codex** -- including `rate_limit`, which turns out to be needed here
too. `subtype` is where the Codex-specific detail goes, and `raw` carries the
whole payload for anything a consumer needs that this mapping did not
anticipate.

## The one judgement in here

Codex reports the tool loop as **items** -- 18 kinds, from `CommandExecution`
and `FileChange` to `WebSearch` and `Reasoning` -- while the enum has no `tool`
member, because the Claude SDK delivers tool use *inside* assistant messages.

**So every item that is not plainly the user's is reported as `assistant`, with
`subtype` naming the item kind.** That is honest: the agent decided to do it.
The alternative -- inventing a `tool` member -- would change a closed enum in
the specification for one implementation's convenience, which is the tail
wagging the dog. A consumer that wants the distinction reads `subtype`, which is
exactly what it is for.

**`item/started` and `item/completed` both map**, and are told apart by
`subtype`'s suffix rather than by being collapsed: a caller watching a long
`CommandExecution` needs to know it began.
"""

from __future__ import annotations

from typing import Any

#: `AgentEvent.type`, as the specification closes it. Repeated here rather than
#: imported because this module must stay free of the web stack -- and because a
#: value outside this set is a specification violation this build must not emit.
EVENT_TYPES = frozenset(
    {"system", "assistant", "user", "result", "stream_event", "rate_limit", "unknown"}
)

#: Notification method -> `AgentEvent.type`, for the methods whose category does
#: not depend on a payload. Method strings are the SDK's own, read from its
#: notification registry rather than guessed.
_METHOD_TYPES: dict[str, str] = {
    # lifecycle -- the service's own bookkeeping, not the model's output
    "thread/started": "system",
    "thread/closed": "system",
    "thread/archived": "system",
    "thread/unarchived": "system",
    "thread/deleted": "system",
    "thread/compacted": "system",
    "turn/started": "system",
    # the turn's terminal event, which carries status and usage
    "turn/completed": "result",
    # environment noise a caller may want to surface but must not mistake for
    # model output
    "account/updated": "system",
    "model/rerouted": "system",
    "model/verification": "system",
    "skills/changed": "system",
    "fs/changed": "system",
    "windows/worldWritableWarning": "system",
    "windowsSandbox/setupCompleted": "system",
    "hook/started": "system",
    "hook/completed": "system",
    "process/exited": "system",
    "serverRequest/resolved": "system",
    "turn/moderationMetadata": "system",
    "fuzzyFileSearch/sessionUpdated": "system",
    "fuzzyFileSearch/sessionCompleted": "system",
    # incremental output -- the only genuinely streaming category
    "process/outputDelta": "stream_event",
}

#: Item kinds that are the USER's turn rather than the agent's. Everything else
#: is the agent acting; see the module docstring.
_USER_ITEMS = frozenset({"UserMessageThreadItem", "HookPromptThreadItem"})


def _item_kind(item: Any) -> str:
    """The concrete class name of a `ThreadItem`, unwrapping the union root.

    Pydantic `RootModel` unions expose the member on `.root`; a bare member has
    no `.root`. Both shapes occur in this SDK, and `TurnResult` collection code
    in the SDK itself does the same unwrap.
    """
    inner = getattr(item, "root", item)
    return type(inner).__name__


def event_type_for(notification: Any) -> tuple[str, str | None]:
    """`(type, subtype)` for one notification. Never raises, never invents.

    An unrecognised method is `unknown` with the method as its subtype, rather
    than a guess or an exception. That is the forward-compatible answer: this
    SDK ships an `UnknownNotification` of its own, so new methods are expected
    rather than exceptional, and a build that crashed on one would be broken by
    a dependency bump it did not ask for.
    """
    method = getattr(notification, "method", None)
    if not isinstance(method, str):
        return "unknown", None

    if method in ("item/started", "item/completed"):
        payload = getattr(notification, "payload", None)
        item = getattr(payload, "item", None)
        if item is None:
            return "unknown", method
        kind = _item_kind(item)
        phase = "started" if method.endswith("started") else "completed"
        etype = "user" if kind in _USER_ITEMS else "assistant"
        return etype, f"{kind}.{phase}"

    mapped = _METHOD_TYPES.get(method)
    if mapped is not None:
        return mapped, method

    # Rate limits are reported on the account, and the specification has a
    # member for exactly this. Matched by prefix because the SDK spells it
    # `account/rateLimitsUpdated` in some versions and folds it into
    # `account/updated` in others -- both must land on `rate_limit`.
    if "ratelimit" in method.replace("/", "").lower():
        return "rate_limit", method

    return "unknown", method


def content_for(notification: Any) -> list[dict[str, Any]] | None:
    """The event's text as normalised `content` blocks, or `None`.

    **This build reported `content: null` on every event until 2026-08-14**
    (CX-56), carrying the text only at `raw.item.text` -- so a client that read
    the field the specification tells it to read saw an empty conversation for a
    turn that had succeeded. The field is now described, and this is that build
    honouring the description.

    **Text only, and deliberately.** Codex reports the tool loop as items and
    this mapping already reports them as `assistant` with the item kind in
    `subtype`; inventing `tool_use` blocks here would guess at a block shape the
    specification does not define and that the other builds fill from their own
    SDK. What a conversation needs to render is the words, and those are what
    an item's `text` holds.

    **`None` rather than `[]` when there is nothing** -- an `init` frame and a
    rate-limit notice have no content, which is not the same as content that
    came back empty.
    """
    payload = getattr(notification, "payload", None)
    item = getattr(payload, "item", None)
    if item is None:
        return None
    inner = getattr(item, "root", item)

    # **Two shapes, because the agent's messages and the caller's are not the
    # same object.** An `agentMessage` carries its words in `.text`; a
    # `userMessage` carries a LIST of blocks in `.content`, each already
    # `{type, text}` plus SDK-specific keys. Both are part of the conversation,
    # so both fill this field -- a caller reading only `content` that saw the
    # answers and not its own prompts would still be reading half a transcript.
    text = getattr(inner, "text", None)
    if isinstance(text, str) and text.strip():
        return [{"type": "text", "text": text}]

    blocks = getattr(inner, "content", None)
    if isinstance(blocks, list):
        # Rebuilt rather than passed through: the SDK's blocks carry keys of its
        # own (`text_elements`) and this field is the normalised one. `raw` is
        # where the original stays reachable.
        out = []
        for block in blocks:
            b = getattr(block, "root", block)
            value = b.get("text") if isinstance(b, dict) else getattr(b, "text", None)
            if isinstance(value, str) and value.strip():
                out.append({"type": "text", "text": value})
        return out or None
    return None


def to_agent_event(notification: Any, seq: int, *, include_raw: bool = True) -> dict[str, Any]:
    """One `Notification` as an `AgentEvent` dict.

    `seq` is the caller's, not the SDK's: the specification numbers events
    within a turn, and only the caller knows where in the turn this is.
    """
    etype, subtype = event_type_for(notification)
    if etype not in EVENT_TYPES:  # pragma: no cover - guarded by the tests
        raise AssertionError(f"{etype!r} is not an AgentEvent type")

    event: dict[str, Any] = {"seq": seq, "type": etype}
    if subtype is not None:
        event["subtype"] = subtype
    content = content_for(notification)
    if content is not None:
        event["content"] = content
    if include_raw:
        event["raw"] = _dump(getattr(notification, "payload", None))
    return event


def _dump(payload: Any) -> dict[str, Any] | None:
    """A payload as plain JSON-able data, or `None`.

    Pydantic models get `model_dump(mode="json")` so that datetimes and enums
    survive; anything else is returned only if it is already a dict. **Never
    raises** -- an event that cannot be serialised must still be reportable,
    because the alternative is losing the turn it belongs to.
    """
    if payload is None:
        return None
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # noqa: BLE001 - see the docstring
            return None
    return payload if isinstance(payload, dict) else None
