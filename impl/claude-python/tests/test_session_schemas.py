import pytest
from pydantic import ValidationError

from agent_spec.openapi.schemas import (
    ContextUsage,
    RunResponse,
    SessionCreate,
    SessionRecord,
    SessionUpdate,
    TurnRecord,
    TurnRequest,
)


def test_session_create_options_default_to_empty_run_options() -> None:
    body = SessionCreate()
    assert body.options.model is None
    assert body.title is None


def test_turn_request_requires_a_prompt() -> None:
    with pytest.raises(ValidationError):
        TurnRequest()
    assert TurnRequest(prompt="hi").prompt == "hi"


def test_turn_request_rejects_an_empty_prompt() -> None:
    with pytest.raises(ValidationError):
        TurnRequest(prompt="")


def test_session_update_no_longer_validates_the_permission_mode_ITSELF() -> None:
    """0.19.0: the model accepts any id and the BUILD refuses the ones it did
    not declare.

    The union it used to validate against was one SDK's enum, which every other
    implementation had to accept whether or not it could honour it. The refusal
    moved to the PATCH route -- see
    `test_patch_rejects_an_invalid_permission_mode`, which asserts a 400 and a
    message naming the modes this build has. Kept as a test rather than deleted
    so that an unconstrained field here reads as a decision.
    """
    SessionUpdate(permission_mode="acceptEdits")
    SessionUpdate(permission_mode="a-mode-some-future-build-declares")


def test_session_update_allows_both_fields_absent() -> None:
    assert SessionUpdate().model is None


# --- follow-up item 9: SessionUpdate is permissive ------------------------


def test_session_update_rejects_an_empty_model() -> None:
    """`{"model": ""}` used to forward an empty string to the SDK's
    `set_model`, which is not harmless -- unlike the other permissiveness in
    this model, it makes a real control request with a meaningless argument.
    Rejected at the schema, so the request never reaches the session."""
    with pytest.raises(ValidationError):
        SessionUpdate(model="")
    assert SessionUpdate(model="claude-opus-5").model == "claude-opus-5"


def test_run_options_rejects_an_empty_model() -> None:
    """Same guard on the creation path. Without it, `POST /v1/sessions` with
    `{"options": {"model": ""}}` reaches `build_options`, where
    `req.model or settings.default_model` silently swallows the empty string
    and substitutes the default -- so the caller is told nothing and gets a
    model it did not ask for."""
    from agent_spec.openapi.schemas import RunOptions

    with pytest.raises(ValidationError):
        RunOptions(model="")
    assert RunOptions(model="claude-opus-5").model == "claude-opus-5"
    assert RunOptions().model is None  # omitted is still fine


def test_session_update_still_accepts_unknown_keys_and_explicit_nulls() -> None:
    """The two OTHER complaints in item 9 are deliberately left alone.

    `{"bogus": 1}` is accepted because no model in `schemas.py` sets
    `extra="forbid"`, and `{"model": null}` is indistinguishable from omission
    because pydantic gives both the same default. Both are project-wide calls
    about how this whole schema module behaves, not properties of
    `SessionUpdate` -- changing either here alone would make one model
    inconsistent with the other eleven. Pinned so the current behaviour is a
    recorded decision rather than an accident.
    """
    assert SessionUpdate(bogus=1).model is None
    assert SessionUpdate(model=None).model is SessionUpdate().model is None


def test_session_record_status_is_constrained() -> None:
    SessionRecord(
        session_id="s1", status="idle", created_at=1.0, last_used_at=1.0,
        turns=0, total_cost_usd=0.0,
    )
    with pytest.raises(ValidationError):
        SessionRecord(
            session_id="s1", status="bogus", created_at=1.0, last_used_at=1.0,
            turns=0, total_cost_usd=0.0,
        )


def test_context_usage_carries_raw_categories() -> None:
    usage = ContextUsage(categories=[{"name": "Messages", "tokens": 42}])
    assert usage.categories[0]["tokens"] == 42


def test_run_response_interrupted_defaults_false() -> None:
    assert RunResponse().interrupted is False


# --- follow-up items 11-14 -------------------------------------------------


def _bare_record(**kw) -> SessionRecord:
    base = dict(
        session_id="s1", status="idle", created_at=1.0, last_used_at=1.0,
        turns=0, total_cost_usd=0.0,
    )
    base.update(kw)
    return SessionRecord(**base)


def test_a_session_that_has_never_taken_a_turn_reports_last_turn_null() -> None:
    """Item 11. `last_turn` must be OPTIONAL and its absence unambiguous.

    A never-used session has nothing to report, and the only honest
    representation of that is `null` -- not a TurnRecord full of falsy
    defaults, which would assert `interrupted: false, timed_out: false` about
    a turn that never happened. This is the reason the record is a nested
    model rather than flat `last_turn_*` fields on SessionRecord: flat fields
    have no way to say "there is no turn" other than by every one of them
    being null at once, which a caller cannot distinguish from a turn that
    genuinely reported nothing.
    """
    assert _bare_record().last_turn is None


def test_turn_record_flags_default_false_and_ids_default_null() -> None:
    record = TurnRecord()
    assert record.interrupted is False
    assert record.timed_out is False
    assert record.is_error is False
    assert record.outcome_recorded is False
    assert record.sdk_session_id is None
    assert record.turn_cost_usd is None


def test_turn_record_uses_sdk_session_id_not_session_id() -> None:
    """Item 7's hole must not be deepened (user decision, 2026-07-27).

    `session_id` already means two different things in this API -- the
    registry handle on `SessionRecord`, the SDK's own id on `RunResponse` --
    and the README's `jq -r .session_id` idiom walks into a 404 because of it.
    Anything NEW carrying the SDK's id says so in its name.
    """
    assert "session_id" not in TurnRecord.model_fields
    assert "sdk_session_id" in TurnRecord.model_fields


def test_session_record_echoes_the_configuration_patch_can_write() -> None:
    """Item 13. Both default to null so an unconfigured record still validates."""
    record = _bare_record()
    assert record.model is None
    assert record.permission_mode is None
    echoed = _bare_record(model="claude-opus-5", permission_mode="plan")
    assert (echoed.model, echoed.permission_mode) == ("claude-opus-5", "plan")


def test_session_record_permission_mode_is_not_constrained_to_the_literal() -> None:
    """Settings.default_permission_mode is a bare `str` read from the
    environment, and this field echoes the RESOLVED value. Constraining it to
    the PermissionMode Literal would turn an operator's config typo into a 500
    on a read endpoint -- the one endpoint whose job is to say what is wrong."""
    assert _bare_record(permission_mode="somethingNew").permission_mode == "somethingNew"


def test_session_record_last_residue_discarded_defaults_to_zero() -> None:
    """Item 12. Zero is the honest default: nothing was discarded."""
    assert _bare_record().last_residue_discarded == 0
    assert _bare_record(last_residue_discarded=3).last_residue_discarded == 3


def test_run_response_turn_cost_usd_is_separate_from_the_cumulative_total() -> None:
    """Item 14. Two distinct fields, never one derived from the other in the
    schema -- `total_cost_usd` stays exactly what it was (cumulative per
    connection on a session, measured S6)."""
    response = RunResponse(total_cost_usd=0.30, turn_cost_usd=0.05)
    assert response.total_cost_usd == 0.30
    assert response.turn_cost_usd == 0.05
    assert RunResponse().turn_cost_usd is None
