"""`agent_spec.runs`: the run-id ledger and the derived run state."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from agent_spec.runs import BOOTED_AT, RunIdInUse, RunIdLedger, run_state


def test_an_id_is_claimed_once() -> None:
    ledger = RunIdLedger()
    ledger.claim("a")
    with pytest.raises(RunIdInUse) as raised:
        ledger.claim("a")
    assert raised.value.run_id == "a"
    assert "a" in ledger


def test_a_released_id_can_be_claimed_again() -> None:
    ledger = RunIdLedger()
    ledger.claim("a")
    ledger.release("a")
    ledger.claim("a")


def test_releasing_an_unclaimed_id_is_harmless() -> None:
    RunIdLedger().release("never")


def test_a_finished_run_has_ended_whenever_it_started() -> None:
    assert run_state(BOOTED_AT - 3600, BOOTED_AT - 3000) == "ended"
    assert run_state(time.time(), time.time()) == "ended"


def test_an_unfinished_run_from_before_the_boot_is_lost() -> None:
    assert run_state(BOOTED_AT - 1, None) == "lost"


def test_an_unfinished_run_from_after_the_boot_is_running() -> None:
    assert run_state(BOOTED_AT + 1, None) == "running"


def test_a_stored_timestamp_is_read_as_the_instant_it_names() -> None:
    """The column is timezone-aware; the comparison must not shift by an offset."""
    before = datetime.fromtimestamp(BOOTED_AT - 1, tz=UTC)
    after = datetime.fromtimestamp(BOOTED_AT + 1, tz=UTC)
    assert run_state(before, None) == "lost"
    assert run_state(after, None) == "running"
