"""One derivation of `stop_kind`, shared by every implementation.

**A second copy of this logic would defeat the field.** `stop_kind` exists so a
client stops having to reconstruct *why did this turn end* from seven places
that could disagree; two builds deriving it independently would reintroduce the
disagreement one layer up, where it is harder to see. So the rule is that a
build supplies FACTS -- it was interrupted, a guardrail fired, the SDK said this
-- and this module decides the word.

**It lives in the shared package rather than in either build**, which is the
same argument `agent-spec` already wins for the models: the specification owns
what a field means, and an implementation owns how to find out.

**Nothing here is SDK-coupled and nothing here may become so.** A build that
needs its own vocabulary translated passes it as `raw`; the mapping of one SDK's
spellings belongs in that build, beside its adapter, where its references file
can explain it.
"""

from __future__ import annotations

from agent_spec.openapi.schemas import StopKind

#: Vendor-neutral spellings that mean a model-side ceiling or refusal, lowercased.
#: **Deliberately small.** A spelling goes in here only when it means the same
#: thing in every SDK that uses it; anything ambiguous is mapped by the build
#: that knows what its own SDK meant.
_RAW_ENDINGS: dict[str, StopKind] = {
    "max_tokens": "max_tokens",
    "max_output_tokens": "max_tokens",
    "token_limit": "max_tokens",
    "refusal": "refusal",
    "refused": "refusal",
    "content_filter": "refusal",
    "end_turn": "end_turn",
    "stop": "end_turn",
    "completed": "end_turn",
}


def derive_stop_kind(
    *,
    outcome_recorded: bool,
    is_error: bool = False,
    interrupted: bool = False,
    timed_out: bool = False,
    limit_hit: str | None = None,
    raw: str | None = None,
) -> StopKind | None:
    """The one word for why a turn ended, or `None` when the build cannot tell.

    **The precedence is the whole of this function and it is not arbitrary.**
    Where two facts could both apply, the earlier one wins:

    1. **`interrupted`** -- before `is_error`, because the Claude CLI reports an
       interrupted turn with `is_error=true` and a failure-shaped subtype. An
       ordering that checked the error first would report every interrupt as a
       crash, which is exactly the confusion `interrupted` was added to end.
    2. **`timed_out`** -- before the guardrails, because a deadline this service
       imposed is not the agent hitting a limit the caller asked for.
    3. **`limit_hit`** -- the caller's own guardrail, and the only one of these
       the caller can prevent by asking for more.
    4. **`is_error`** -- a real failure, once the three endings that also look
       like failures have been taken off the table.
    5. **the SDK's own word**, mapped only where a spelling is unambiguous
       across SDKs.

    **`None` and `"other"` are different answers and neither may stand in for
    the other.** `None` means *this build does not know how this turn ended* --
    the process died, nothing was recorded. `"other"` means *it ended, in a way
    this build recognises as an ending and has no name for*. A client can retry
    on one and file a bug on the other.
    """
    if interrupted:
        return "interrupted"
    if timed_out:
        return "timed_out"
    if limit_hit == "turns":
        return "max_turns"
    if limit_hit == "budget":
        return "max_budget"
    if is_error:
        return "error"
    if raw and (mapped := _RAW_ENDINGS.get(raw.strip().lower())):
        return mapped
    if not outcome_recorded:
        # The turn never reached an ending of its own accord and nothing above
        # explained why. That is genuinely unknown, not "other".
        return None
    return "end_turn" if raw is None else "other"
