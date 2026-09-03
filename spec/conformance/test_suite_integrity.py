"""A guard on this suite itself.

A suite that reports success while executing nothing is worse than a failing
one: it is indistinguishable from a passing one at every level anybody looks.
That happened -- `conftest.py`'s `pytest_collection_modifyitems` receives EVERY
collected test rather than the ones beside it, and an early version marked the
whole run skipped: `550 skipped, 0 passed`, exit 0.

**This module moved here with the suite in Plan 8 step 3**, from the
implementation's `tests/test_suite_integrity.py`, and it had to: it asserts
something about what THIS package collects, and after the move the
implementation's pytest run no longer sees this package at all. The half that
guards the in-process suite stayed behind, because that is what it is about.
"""

from __future__ import annotations


def test_the_document_tier_is_not_skipped(request) -> None:  # noqa: ANN001
    """The tier that needs no service must actually run.

    The document tier and the negative control read published JSON and need no
    service, so they run on a bare checkout. That is their entire value -- a
    negative control which only runs on a machine with a container running is a
    negative control nobody runs. `conftest.py` decides what to skip from a
    test's FIXTURE LIST rather than its path, and this is what pins that: widen
    the skip back to the whole package and this fails.
    """
    document_tier = [
        item
        for item in request.session.items
        if "test_spec_document" in str(item.path)
        or "test_spec_negative_control" in str(item.path)
    ]
    assert len(document_tier) > 10, (
        f"only {len(document_tier)} document-tier conformance tests collected; "
        "they should run without AGENT_SERVICE_TEST_BASE_URL"
    )

    skipped = [item for item in document_tier if item.get_closest_marker("skipif")]
    assert not skipped, (
        f"{len(skipped)} document-tier tests carry a skipif marker -- they need no "
        "service and must not be gated on one"
    )


def test_the_container_tier_asks_for_no_running_service(request) -> None:  # noqa: ANN001
    """`test_boot_gates.py` talks to an IMAGE. It must never need a base URL.

    **This exists because it happened.** Renaming the module-local fixture
    `published_contract` to `published_spec` on 2026-08-07 collided with
    `conftest.py`'s session-scoped `published_spec`, which fetches the OpenAPI
    document from a RUNNING service and skips when
    `AGENT_SERVICE_TEST_BASE_URL` is unset. Five of the ten boot-gate tests
    silently became skips -- `sss.ss....` -- and **the `gates` stage still
    reported PASS**, because a skip is not a failure. That is the exact shape
    this module was written to catch, one tier along.

    The fixture is `preboot_spec` now. This asserts the property rather than the
    name: nothing in the container tier may depend, at any depth, on a fixture
    that requires a service, because the whole point of the tier is that it
    starts its own containers and reads exit codes.
    """
    gates = [
        item for item in request.session.items if "test_boot_gates" in str(item.path)
    ]
    if not gates:  # the module is skipped wholesale without AGENT_SERVICE_TEST_IMAGE
        return

    offenders = {
        item.name: sorted(set(item.fixturenames) & {"base_url", "api", "published_spec"})
        for item in gates
        if set(item.fixturenames) & {"base_url", "api", "published_spec"}
    }
    assert not offenders, (
        "container-tier tests depend on service-scoped fixtures and will SKIP "
        f"rather than fail when no service is running: {offenders}. A name "
        "collision with conftest.py is the likely cause -- see this test's docstring."
    )


# --- the paid tier's own options ---------------------------------------------


def test_the_paid_tier_sends_no_option_the_build_refuses() -> None:
    """**The literal this replaced made the whole paid tier unrunnable against
    the second implementation**, and nothing noticed because the tier is
    deselected by default: `{"model": "claude-haiku-4-5", "max_turns": 1, ...}`
    named one SDK's model and set an option `codex-python` answers 400 to, so
    every test there died at session creation for a reason no clause is about.

    Driven from both builds' REAL published lists, measured 2026-08-09, so this
    is not a test of a rule against itself.
    """
    from .conftest import cheap_option_payload

    # claude-python refuses nothing.
    assert cheap_option_payload([], "claude-haiku-4-5") == {
        "max_turns": 1,
        "allowed_tools": [],
        "model": "claude-haiku-4-5",
    }

    codex_refuses = [
        {"field": "allowed_tools"},
        {"field": "disallowed_tools"},
        {"field": "max_budget_usd"},
        {"field": "max_turns"},
        {"field": "mcp_servers"},
        {"field": "setting_sources"},
        {"field": "system_prompt", "types": ["object"]},
    ]
    payload = cheap_option_payload(codex_refuses, "gpt-5-mini")
    assert "max_turns" not in payload, "a refused, non-empty option must be dropped"
    assert payload["allowed_tools"] == [], (
        "an EMPTY container asks for nothing and is not refused -- dropping it "
        "discards the no-tools intent for no gain"
    )
    assert payload["model"] == "gpt-5-mini"


def test_no_model_is_named_unless_the_operator_names_one() -> None:
    """A model name belongs to one SDK. Unset, the deployment's default is used
    -- which is a cost the operator has to know about and cannot be guessed at
    from inside this package."""
    from .conftest import cheap_option_payload

    assert "model" not in cheap_option_payload([], None)


def test_a_structured_entry_strips_its_field() -> None:
    """**Entries are `{field, types?}`, and this is the shape that replaced the
    prose.** Agent Studio measured that a client comparing field names could
    never match `"system_prompt (preset form)"`; the fixture reads `field` now
    and a bare string is only tolerated for a build older than the change."""
    from .conftest import cheap_option_payload

    assert "max_turns" not in cheap_option_payload([{"field": "max_turns"}], None)
    # A pre-0.19.0 build published bare strings. Tolerated, not expected.
    assert "max_turns" not in cheap_option_payload(["max_turns"], None)
