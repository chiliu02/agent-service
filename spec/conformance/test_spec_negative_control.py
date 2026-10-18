"""The negative control: prove the checks can fail.

**No service, no Docker, no tokens.**

A conformance suite that has only ever seen a conforming document proves
nothing, because passing is what a broken check does too. Until this file
existed, "26 passed" and "26 checks that cannot fail" were indistinguishable on
this side. Adopted from Agent Studio's suite at specification sign-off, which
had it when this side did not; the sign-off names it as the one thing worth
importing.

The fixture is a **real** non-conforming document — `spec/conformance/fixtures/openapi-0.2.0.json`,
the one Studio actually read and built against — not a mutated copy of the
current spec. A mutation would only prove the predicate reads the field it was
just handed; 0.2.0 proves the predicates would have caught the surface that
really shipped.

**What 0.2.0 lacked**, measured here rather than quoted:

| Clause | Missing in 0.2.0 |
|---|---|
| AS-1  | `credential_sources`, `provider_selectors` — a credential mechanism nothing could read |
| AS-5  | `max_sessions` — the cap existed only in a 429's prose |
| AS-7  | `x-sdk-session-id` — the header Studio wrote an SSE scanner to live without |
| AS-8  | the first-turn wording, which is why the wrong conclusion was reachable |
| AS-13 | `sdk_session_id` on create — the join was an observation, not a field |
| AS-17a| `SessionRecord.sdk_session_id` |
| AS-11 | `deployment.behaviour.query_reports_sdk_session_id` — **new on 2026-08-09**, see below |

**Two predicates cannot distinguish these two documents, and that is recorded
rather than hidden.** AS-17 and AS-23 already held in 0.2.0: the nullable
per-turn cost fields were there all along, and no route has been removed. They
earn their place in the document tier but add nothing here, so they are asserted
in the *passing* direction instead, which keeps this file honest about what it
does and does not discriminate.

**AS-11 MOVED from that list to the failing one on 2026-08-09, and the move is
the interesting part.** It used to be undiscriminating for a reason worth
remembering: `RunResponse.sdk_session_id` was in 0.2.0 all along, so the clause
already held and Studio's SSE scanner was a failure to read rather than
something this side had failed to publish.

What changed is that the clause stopped being a prohibition. It forbade
`/v1/query*` from declaring `x-sdk-session-id` — a rule generalised out of one
SDK's timing, which the Codex build can satisfy and has no reason to. The
prohibition is now a published capability instead
(`query_reports_sdk_session_id`, AS-32), and 0.2.0 does not have it. So the
predicate discriminates, and it discriminates on the half that a client actually
branches on.

**The guard that forced this file to be edited is `test_every_predicate_is_classified`.**
Changing a predicate cannot silently leave it in the wrong list.
"""

from __future__ import annotations

from typing import Any

import pytest

from . import predicates

#: Measured against `spec/conformance/fixtures/openapi-0.2.0.json`, not assumed.
#:
#: **AS-23 moved here on 2026-09-03**, when `/v1/capabilities` was renamed to
#: `/v1/deployment`. A 0.2.0 document cannot carry a route that did not exist
#: yet, so the clause now fails on it -- and that is the clause working: a
#: renamed route IS a route that disappeared, which is exactly the breach AS-23
#: is written to catch. The rename is a deliberate break with a notice, not an
#: accident, and the control records which of the two it was.
MUST_FAIL_ON_0_2_0 = ("AS-1", "AS-5", "AS-7", "AS-8", "AS-11", "AS-13", "AS-17a",
                      "AS-23")

#: Held in 0.2.0 already. Asserted so the split stays deliberate.
ALREADY_HELD_IN_0_2_0 = ("AS-17",)


@pytest.mark.parametrize("clause", MUST_FAIL_ON_0_2_0)
def test_the_predicate_rejects_the_non_conforming_document(
    clause: str, non_conforming_spec: dict[str, Any]
) -> None:
    """The check fires. If this passes, the check has stopped being able to."""
    with pytest.raises(AssertionError) as caught:
        predicates.PREDICATES[clause](non_conforming_spec)

    # A predicate that failed for an unrelated reason -- a KeyError dressed up,
    # a typo'd schema name -- would still satisfy `raises`. The message must
    # name the clause it is speaking for.
    assert clause in str(caught.value), (
        f"{clause}'s predicate failed without naming {clause}: {caught.value}"
    )


@pytest.mark.parametrize("clause", ALREADY_HELD_IN_0_2_0)
def test_the_predicate_accepts_what_0_2_0_already_got_right(
    clause: str, non_conforming_spec: dict[str, Any]
) -> None:
    """The other direction: these predicates do not reject on age alone.

    Without this, a predicate that failed on *every* document would look like a
    working check in the table above.
    """
    predicates.PREDICATES[clause](non_conforming_spec)


def test_every_predicate_is_classified() -> None:
    """Adding a predicate forces a decision about the negative control.

    Otherwise the natural thing happens: a clause is added to the document tier,
    nobody asks whether it can fail, and the control silently stops covering the
    suite it is meant to validate.
    """
    classified = set(MUST_FAIL_ON_0_2_0) | set(ALREADY_HELD_IN_0_2_0)
    assert classified == set(predicates.PREDICATES), (
        "unclassified predicates: "
        f"{sorted(set(predicates.PREDICATES) - classified)}; "
        "run each against spec/conformance/fixtures/openapi-0.2.0.json and list it as one or the other"
    )
