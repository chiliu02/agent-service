"""`RunOptions` -> Codex parameters, tested against the real `RunOptions`.

Built from `agent_spec.openapi.schemas` — the shared specification models — so a field
added or re-typed there fails here rather than being silently ignored at
runtime. That is the point of sharing them.

No app-server, no credential, no cost.
"""

from __future__ import annotations

import typing

import pytest
from agent_spec.openapi.schemas import PermissionMode, RunOptions
from openai_codex import ApprovalMode, Sandbox

from agent_service.config import Settings
from agent_service.options import (
    PermissionModeUnsupported,
    session_modes,
    NOT_SUPPORTED,
    SERVICE_ENFORCED,
    LimitExceeded,
    resolve_timeout,
    thread_kwargs,
    turn_kwargs,
    unsupported,
)


# --- the safety-critical mapping --------------------------------------------


def test_every_permission_mode_this_build_DECLARES_is_mapped() -> None:
    """**The load-bearing test, and it went vacuous for an hour in 0.19.0.**

    It used to loop over `typing.get_args(PermissionMode)`, driven from the
    specification's closed `Literal`. That type became a plain `str` when each
    build started declaring its own modes -- so `get_args` returned `()`, the
    loop body never ran, and the test went on passing while checking nothing.
    Exactly the failure this repository keeps finding elsewhere: a check whose
    subject moved out from under it.

    Driven from `session_modes()` now, which is the same list
    `/v1/deployment` publishes. **So a mode this build advertises and cannot
    apply fails here**, which is the property that actually matters -- and the
    source cannot silently empty, because an empty declaration would fail the
    assertion below it.
    """
    declared = [m.id for m in session_modes()]
    assert declared, "this build declares no permission modes at all"
    for mode in declared:
        kwargs = thread_kwargs(RunOptions(permission_mode=mode))
        assert isinstance(kwargs["sandbox"], Sandbox), mode
        assert isinstance(kwargs["approval_mode"], ApprovalMode), mode


def test_an_undeclared_permission_mode_is_refused_rather_than_a_KeyError() -> None:
    """**New in 0.19.0 and it has to be.** The field was a closed `Literal`, so
    pydantic refused an unknown value before this module ran; now it is an
    opaque string and an unmapped id would be a `KeyError` -- a 500 for a
    request that is merely wrong."""
    with pytest.raises(PermissionModeUnsupported) as excinfo:
        thread_kwargs(RunOptions(permission_mode="notAMode"))
    assert "notAMode" in str(excinfo.value)
    # The remedy, not just the refusal.
    assert "capabilities.permission_modes" in str(excinfo.value)


def test_every_declared_mode_carries_a_name_and_a_description() -> None:
    """A caller picks a mode from this list, so an id with no prose beside it is
    a mode nobody can choose deliberately."""
    for mode in session_modes():
        assert mode.name.strip(), mode.id
        assert mode.description.strip(), mode.id


def test_no_permission_mode_reaches_full_access() -> None:
    """`full_access` disables the sandbox, and **no value in our vocabulary
    means that**.

    A deployment wanting it must say so in its own configuration; a caller must
    not be able to reach it through a per-request field. This is the test that
    keeps a future edit to the table honest.
    """
    for mode in typing.get_args(PermissionMode):
        assert thread_kwargs(RunOptions(permission_mode=mode))["sandbox"] is not Sandbox.full_access


def test_plan_mode_cannot_write() -> None:
    """`plan` means read and reason, change nothing. Codex has a true read-only
    sandbox, so this one maps exactly rather than approximately."""
    assert thread_kwargs(RunOptions(permission_mode="plan"))["sandbox"] is Sandbox.read_only


def test_no_mode_asks_for_an_approval_nobody_can_give() -> None:
    """**`auto_review` is self-approval on this service, measured.**

    (CX-04) under `read_only` + `auto_review` the
    agent asked *"I need your approval to write to /workspace. Proceed?"* and
    then approved itself -- `decision_source: "agent"`, *"Auto-review returned a
    low-risk allow decision"* -- and the write landed on the host bind mount.

    There is no approval channel in `/v1`, so an approval mode has no approver
    and `plan` was read-only only until the agent decided otherwise. The sandbox
    is the only axis now, and this is the guard that keeps it that way: a future
    edit reintroducing `auto_review` fails here rather than in production.
    """
    for mode in typing.get_args(PermissionMode):
        assert (
            thread_kwargs(RunOptions(permission_mode=mode))["approval_mode"]
            is ApprovalMode.deny_all
        ), mode


def test_default_mode_is_not_more_permissive_than_accept_edits() -> None:
    """A conservative default is the whole reason the table is written out
    rather than computed."""
    default = thread_kwargs(RunOptions(permission_mode="default"))
    assert default["sandbox"] is Sandbox.read_only
    assert default["approval_mode"] is ApprovalMode.deny_all


# --- effort ------------------------------------------------------------------


def test_every_effort_level_maps_and_max_lands_on_the_highest() -> None:
    """Ours goes to `max`; Codex stops at `xhigh`. Narrowing by one step beats
    refusing a caller for asking for more effort than this SDK can express."""
    from agent_spec.openapi.schemas import EffortLevel

    for level in typing.get_args(EffortLevel):
        assert turn_kwargs(RunOptions(effort=level))["effort"]
    assert turn_kwargs(RunOptions(effort="max"))["effort"] == "xhigh"


# --- only what was asked for -------------------------------------------------


def test_unset_options_are_not_passed_at_all() -> None:
    """Passing `None` is not the same as not passing: the SDK's own defaults are
    better than any this module could invent."""
    assert thread_kwargs(RunOptions()) == {}
    assert turn_kwargs(RunOptions()) == {}


def test_cwd_is_passed_through_when_given() -> None:
    assert thread_kwargs(RunOptions(), cwd="/workspace/sub")["cwd"] == "/workspace/sub"


def test_an_empty_model_string_is_not_forwarded() -> None:
    """The spec rejects an empty model at validation; this is belt-and-braces
    against it reaching the SDK as a real value."""
    assert "model" not in thread_kwargs(RunOptions.model_construct(model=""))


# --- telling the caller the truth --------------------------------------------


def test_options_with_no_equivalent_are_reported_not_dropped() -> None:
    """**An option silently dropped is worse than one refused** -- the caller
    believes a restriction is in force that nothing will apply."""
    reported = unsupported(RunOptions(allowed_tools=["Read"], disallowed_tools=["Bash"]))
    assert "allowed_tools" in reported
    assert "disallowed_tools" in reported


def test_a_preset_system_prompt_is_reported() -> None:
    """The dict form is a Claude preset with no Codex equivalent. Ignored
    rather than stringified -- and said so."""
    opts = RunOptions(system_prompt={"type": "preset", "preset": "claude_code"})
    assert any("system_prompt" in name for name in unsupported(opts))
    assert "base_instructions" not in thread_kwargs(opts)


def test_a_string_system_prompt_is_forwarded() -> None:
    kwargs = thread_kwargs(RunOptions(system_prompt="be terse"))
    assert kwargs["base_instructions"] == "be terse"


def test_the_one_service_enforced_option_is_not_reported_as_unsupported() -> None:
    """`timeout_s` has no SDK equivalent but IS enforced, by this service, so
    reporting it would tell the caller a limit is absent when it is not.

    **This test used to make the same claim about `max_turns` and
    `max_budget_usd` and the claim was false** -- nothing applied either, and
    `unsupported()` hid both on the strength of it. See
    (CX-10) and the module docstring in `options.py`.
    """
    assert unsupported(RunOptions(timeout_s=30)) == []


def test_the_two_unenforceable_limits_are_reported_to_the_caller() -> None:
    """The rule this module opens with, applied to itself: an option silently
    dropped is worse than one refused."""
    reported = unsupported(RunOptions(max_turns=5, max_budget_usd=1.0))
    assert "max_turns" in reported
    assert "max_budget_usd" in reported


def test_no_option_is_both_enforced_and_unsupported() -> None:
    """The guard that would have caught 10.1 as a contradiction rather than as a
    measurement: a name in both tuples is a claim that something enforces it and
    a claim that nothing does."""
    assert not set(SERVICE_ENFORCED) & set(NOT_SUPPORTED)


# --- the turn deadline ------------------------------------------------------


def test_an_absent_timeout_takes_the_deployment_default() -> None:
    assert resolve_timeout(None, Settings()) == float(Settings().default_request_timeout_s)


def test_a_requested_timeout_within_the_cap_is_honoured() -> None:
    assert resolve_timeout(45, Settings()) == 45.0


def test_a_timeout_above_the_cap_is_REFUSED_not_clamped() -> None:
    """**Refused, and that is the decision.** Silently shortening a caller's
    deadline produces a 504 they cannot explain; a 400 names the cap and the
    field to read it from."""
    settings = Settings()
    with pytest.raises(LimitExceeded) as excinfo:
        resolve_timeout(settings.max_allowed_timeout_s + 1, settings)
    message = str(excinfo.value)
    assert "timeout_s" in message
    assert "max_allowed_timeout_s" in message


def test_the_cap_itself_is_allowed() -> None:
    """An off-by-one here would refuse exactly the value `/v1/deployment`
    advertises as permitted, which is the worst possible place for one."""
    settings = Settings()
    assert resolve_timeout(settings.max_allowed_timeout_s, settings) == float(
        settings.max_allowed_timeout_s
    )


@pytest.mark.parametrize("name", [*SERVICE_ENFORCED, *NOT_SUPPORTED])
def test_the_named_options_all_exist_on_the_real_model(name: str) -> None:
    """Guards against a rename in the shared specification leaving this module
    naming a field that no longer exists -- which would report nothing and look
    fine."""
    assert name in RunOptions.model_fields


# --- the endpoint translation ------------------------------------------------
#
# **MEASURED 2026-08-09, and this is the pure half of that measurement.** A turn
# with `OPENAI_BASE_URL=https://probe.invalid/v1` reached
# `https://probe.invalid/v1/responses` and never `api.openai.com` -- confirming
# that the config-override route works and that `wire_api=responses` is the right
# shape. It cost nothing: an unresolvable host fails at DNS, and the discriminator
# is which host the failure names.
#
# The turn itself is not a test here -- it needs an app-server and 60 seconds of
# retries. What is tested is the translation, because that is where a wrong key
# name would silently leave traffic on the public API with a private key.


def test_no_endpoint_configured_produces_no_overrides() -> None:
    """**Empty matters more than it looks.** A build that always injected a
    provider would be overriding the endpoint even when nobody asked, replacing
    the app-server's own defaults with ours."""
    from agent_service.config import endpoint_overrides

    assert endpoint_overrides(None) == ()
    assert endpoint_overrides("") == ()


def test_the_endpoint_becomes_a_named_provider_and_is_selected() -> None:
    """The app-server addresses a base URL through a *named provider*, so setting
    the URL is not enough -- the provider must also be selected. Missing the
    second half is a container that looks configured and talks to the public API.
    """
    from agent_service.config import endpoint_overrides

    overrides = endpoint_overrides("https://relay.internal/v1")
    joined = "\n".join(overrides)
    assert "base_url=https://relay.internal/v1" in joined
    assert any(o.startswith("model_provider=") for o in overrides), (
        "the provider is defined but never selected, so the endpoint is ignored"
    )
    # Measured: the redirect landed on `<base>/responses`.
    assert "wire_api=responses" in joined


def test_the_credential_is_not_carried_in_the_overrides() -> None:
    """`open()` logs in through the app-server's auth store instead.

    Naming an `env_key` here would create a second credential path whose failure
    mode is a silent fallback to the wrong one -- and would put the key in the
    subprocess's argv, which is measurably readable by the agent itself.
    """
    from agent_service.config import endpoint_overrides

    joined = "\n".join(endpoint_overrides("https://relay.internal/v1"))
    assert "env_key" not in joined
    assert "api_key" not in joined.lower()


# --- setting_sources: measured, and it answers a consumer's whole thread ------


def test_the_published_sources_are_the_ones_honoured() -> None:
    """**Agent Studio asked whether this build has project-level configuration.**

    It does: Codex reads `AGENTS.md` from the thread's cwd, and
    `project_doc_max_bytes=0` suppresses it -- measured, two turns,
    `spike/probe_project_doc.py`. Until then this build published the whole
    vocabulary and honoured none of it, which is the same defect shape as
    `allow_mcp_servers: false` being advisory.
    """
    from agent_service.options import SUPPORTED_SETTING_SOURCES

    assert set(SUPPORTED_SETTING_SOURCES) == {"user", "project"}


def test_project_present_leaves_the_runtime_default_alone() -> None:
    """A positive override would pin a byte budget this service has no opinion
    about. Saying nothing is how "read the project doc" is expressed."""
    from agent_service.options import setting_source_overrides

    assert setting_source_overrides(RunOptions(setting_sources=["user", "project"])) == ()


def test_project_absent_switches_the_project_doc_off() -> None:
    """The one bit Studio's two agent modes turn on: a domain agent sends
    `["user"]` and must not read the checkout's `AGENTS.md`."""
    from agent_service.options import setting_source_overrides

    assert setting_source_overrides(RunOptions(setting_sources=["user"])) == (
        "project_doc_max_bytes=0",
    )


def test_an_omitted_field_is_the_deployments_default_not_a_stripped_agent() -> None:
    """**Omitted means "server default", which is what the field's own
    description promises.** A caller who never heard of `setting_sources` gets
    the runtime's ordinary behaviour rather than a silently reduced agent."""
    from agent_service.options import setting_source_overrides

    assert setting_source_overrides(RunOptions()) == ()


def test_local_is_refused_by_value_because_there_is_no_third_layer() -> None:
    """Refused by VALUE, not by field -- which is why `unsupported_options` does
    not name `setting_sources`. The field is honoured; one of its members has no
    equivalent, and `capabilities.setting_sources` publishes which do."""
    from agent_service.options import SettingSourceUnsupported, setting_source_overrides

    with pytest.raises(SettingSourceUnsupported) as excinfo:
        setting_source_overrides(RunOptions(setting_sources=["user", "local"]))

    assert "local" in str(excinfo.value)
    assert "capabilities" in str(excinfo.value).lower()


def test_an_empty_list_is_not_the_same_as_omission() -> None:
    """Studio's words: *`[]` is a third behaviour, not an absence.* An explicit
    empty list asks for no project doc, and gets it."""
    from agent_service.options import setting_source_overrides

    assert setting_source_overrides(RunOptions(setting_sources=[])) == (
        "project_doc_max_bytes=0",
    )


def test_max_effort_is_not_published_and_is_still_honoured() -> None:
    """CX-53: the published list is what this build delivers EXACTLY.

    `max` has no Codex equivalent and maps to `xhigh`. The narrowing is correct
    and stays; publishing `max` as available while quietly delivering one step
    less is what was wrong, and a client optimising for reasoning could not see
    it.
    """
    from agent_service.options import HONOURED_EFFORT_LEVELS, _EFFORT

    assert "max" not in HONOURED_EFFORT_LEVELS, "publishes a level it cannot deliver"
    assert "xhigh" in HONOURED_EFFORT_LEVELS
    # Behaviour is unchanged: still accepted, still the most there is.
    assert _EFFORT["max"] == "xhigh"


def test_the_published_effort_levels_cannot_drift_from_the_mapping() -> None:
    """Derived, not typed out beside the table -- the AS-32 drift guard."""
    from agent_service.options import HONOURED_EFFORT_LEVELS, _EFFORT

    assert set(HONOURED_EFFORT_LEVELS) == {
        level for level, mapped in _EFFORT.items() if level == mapped
    }
