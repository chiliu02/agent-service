"""`stop_kind` must never contradict the flags it sits beside.

**That is the whole value of the field.** It was added because *why did this
turn end* was answerable only by reading seven things — three SDK-specific
strings and four typed flags — and an eighth field that could disagree with the
other seven would be worse than none.

So these tests are mostly about PRECEDENCE, and the precedence is not arbitrary:
each ordering below exists because one build or the other reports two facts at
once for a single ending.
"""

from __future__ import annotations

import pytest

from agent_spec.openapi.schemas import StopKind
from agent_spec.openapi.stop_kind import derive_stop_kind


def test_an_interrupt_beats_the_error_flag_that_comes_with_it() -> None:
    """**The ordering that matters most.** The Claude CLI reports an interrupted
    turn with `is_error=true` and a failure-shaped subtype -- checking the error
    first would report every interrupt as a crash, which is the exact confusion
    the `interrupted` flag was added to end."""
    assert derive_stop_kind(
        outcome_recorded=True,
        is_error=True,
        interrupted=True,
        raw="error_during_execution",
    ) == "interrupted"


def test_a_timeout_beats_a_guardrail_and_an_error() -> None:
    """A deadline this service imposed is not the agent hitting a limit the
    caller asked for, and it is not a crash."""
    assert derive_stop_kind(
        outcome_recorded=False, is_error=True, timed_out=True, limit_hit="turns"
    ) == "timed_out"


def test_a_guardrail_beats_a_generic_error() -> None:
    """`limit_hit` is the one ending the caller can prevent by asking for more,
    so it must not be flattened into `error`."""
    assert derive_stop_kind(outcome_recorded=True, is_error=True, limit_hit="turns") == "max_turns"
    assert derive_stop_kind(outcome_recorded=True, is_error=True, limit_hit="budget") == "max_budget"


def test_a_plain_finish_is_end_turn() -> None:
    assert derive_stop_kind(outcome_recorded=True) == "end_turn"
    assert derive_stop_kind(outcome_recorded=True, raw="completed") == "end_turn"
    assert derive_stop_kind(outcome_recorded=True, raw="end_turn") == "end_turn"


def test_unambiguous_vendor_spellings_map() -> None:
    """Only spellings that mean the same thing in every SDK live in the shared
    table. Anything else is the owning build's job to translate."""
    assert derive_stop_kind(outcome_recorded=True, raw="max_tokens") == "max_tokens"
    assert derive_stop_kind(outcome_recorded=True, raw="MAX_OUTPUT_TOKENS") == "max_tokens"
    assert derive_stop_kind(outcome_recorded=True, raw="refusal") == "refusal"
    assert derive_stop_kind(outcome_recorded=True, raw="content_filter") == "refusal"


def test_an_unrecognised_ending_is_other_and_NOT_none() -> None:
    """**`other` and `None` are different answers and neither may stand in for
    the other.** `other` means the build knows the turn ended and has no name
    for how; `None` means it does not know it ended at all. A client retries on
    one and files a bug on the other."""
    assert derive_stop_kind(outcome_recorded=True, raw="banana") == "other"


def test_nothing_recorded_and_nothing_explaining_it_is_none() -> None:
    """The process died mid-turn. Reporting `other` here would claim knowledge
    of an ending that was never observed."""
    assert derive_stop_kind(outcome_recorded=False) is None


def test_every_value_it_can_return_is_in_the_published_type() -> None:
    """A value outside `StopKind` would validate nowhere and appear in no
    generated client. Pins the function against the schema rather than against
    a copy of the list."""
    published = set(StopKind.__args__)  # type: ignore[attr-defined]
    produced = {
        derive_stop_kind(outcome_recorded=True, interrupted=True),
        derive_stop_kind(outcome_recorded=True, timed_out=True),
        derive_stop_kind(outcome_recorded=True, limit_hit="turns"),
        derive_stop_kind(outcome_recorded=True, limit_hit="budget"),
        derive_stop_kind(outcome_recorded=True, is_error=True),
        derive_stop_kind(outcome_recorded=True),
        derive_stop_kind(outcome_recorded=True, raw="max_tokens"),
        derive_stop_kind(outcome_recorded=True, raw="refusal"),
        derive_stop_kind(outcome_recorded=True, raw="banana"),
    }
    assert produced <= published
    # ...and every published value except the two only a build can reach is
    # actually produced by something, so the list carries no dead entries.
    assert published - produced == set()


@pytest.mark.parametrize(
    ("flags", "forbidden"),
    [
        ({"interrupted": True}, {"error", "end_turn"}),
        ({"timed_out": True}, {"error", "end_turn"}),
        ({"limit_hit": "turns"}, {"error", "end_turn"}),
    ],
)
def test_it_never_contradicts_the_flag_beside_it(flags: dict, forbidden: set) -> None:
    """The property the field lives or dies by, stated once as a rule rather
    than implied by the cases above."""
    assert derive_stop_kind(outcome_recorded=True, is_error=True, **flags) not in forbidden


class _Row:
    """The six columns `stop_kind_of` reads, and nothing else."""

    def __init__(self, **kw: object) -> None:
        self.outcome_missing = kw.get("outcome_missing", False)
        self.is_error = kw.get("is_error", False)
        self.interrupted = kw.get("interrupted", False)
        self.timed_out = kw.get("timed_out", False)
        self.limit_hit = kw.get("limit_hit")
        self.stop_reason = kw.get("stop_reason")
        self.result_subtype = kw.get("result_subtype")


def test_a_stored_run_reports_the_timeout_the_504_announced() -> None:
    """The whole reason history derives this: the 504 is long gone.

    A timed-out turn returns a problem document and no run response, so this
    row is the only surviving statement that the wall clock ran out.
    """
    from agent_spec.db.queries import stop_kind_of

    assert stop_kind_of(_Row(outcome_missing=True, timed_out=True)) == "timed_out"


def test_a_stored_interrupt_is_not_reported_as_a_crash() -> None:
    """`interrupted` outranks `is_error`, on this surface as on the live one."""
    from agent_spec.db.queries import stop_kind_of

    row = _Row(outcome_missing=True, interrupted=True, is_error=True)
    assert stop_kind_of(row) == "interrupted"


def test_a_stored_guardrail_beats_the_raw_spelling() -> None:
    from agent_spec.db.queries import stop_kind_of

    row = _Row(limit_hit="budget", stop_reason="end_turn")
    assert stop_kind_of(row) == "max_budget"


def test_an_ordinary_stored_turn_ends_the_turn() -> None:
    from agent_spec.db.queries import stop_kind_of

    assert stop_kind_of(_Row(stop_reason="end_turn")) == "end_turn"
