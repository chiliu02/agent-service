"""Guards on the test suite itself.

A suite that reports success while executing nothing is worse than a failing
one: it is indistinguishable from a passing one at every level anybody looks.
This module exists because that happened -- the conformance suite's
`conftest.py` added a skip marker in `pytest_collection_modifyitems`, whose
`items` argument is EVERY collected test rather than the ones beside the
conftest, and a full run reported `550 skipped, 0 passed` and exit 0.

**Half of this module moved out in Plan 8 step 3.** The conformance suite is now
`spec/conformance/`, a separate project with its own `pyproject.toml`, and
this run does not collect it -- so the guard on ITS document tier moved with it,
to `spec/conformance/test_suite_integrity.py`. What stayed is the guard on
the in-process suite, which is what this file is about. The conformance
exclusion below is kept and is now a no-op: it costs one predicate and it is the
thing that would have to be re-added the moment anything pulls that package back
into this run.
"""

from __future__ import annotations


def test_the_in_process_suite_actually_runs(request) -> None:  # noqa: ANN001
    """At least most of the collected tests must be selected and runnable.

    Deliberately crude: it does not care which tests exist, only that the suite
    has not been switched off wholesale by a marker, a conftest hook, or an
    `addopts` change.
    """
    session = request.session
    collected = [
        item for item in session.items if "conformance" not in str(item.path)
    ]
    assert len(collected) > 200, (
        f"only {len(collected)} non-conformance tests were collected; something "
        "is deselecting the suite"
    )

    skip_marked = [item for item in collected if item.get_closest_marker("skipif")]
    # A handful of tests skip for real reasons (Postgres, platform). A majority
    # skipping means something global switched them off.
    assert len(skip_marked) < len(collected) // 2, (
        f"{len(skip_marked)} of {len(collected)} non-conformance tests carry a "
        "skipif marker -- a global skip has been applied"
    )


def test_the_ci_runner_never_re_selects_the_paid_tests() -> None:
    """**A command-line `-m` REPLACES `addopts`, and that once cost nothing only
    by accident.**

    `ci.py --fast` passes `-m` to skip the postgres tests. pytest takes the LAST
    `-m`, so a bare `-m "not postgres"` silently re-selects everything
    `addopts = "-m 'not live'"` exists to deselect -- including the two tests in
    `test_live.py` that spend real money.

    Measured 2026-08-08: under `-m "not postgres"` those two are collected.
    Nothing was ever spent, because they carry a second guard
    (`skipif(not credentials_configured())`) and pytest does not load `.env` --
    but export `ANTHROPIC_API_KEY` in a shell, as the quick start invites, and
    every `git commit` would spend ~$0.125 through the pre-commit hook.

    This asserts the runner composes the markers rather than replacing them.
    Reading `ci.py` as text because it is not importable from here -- it is
    stdlib-only, at the platform root, and deliberately not a package.
    """
    import re
    from pathlib import Path as _Path

    ci = (_Path(__file__).resolve().parents[3] / ".ci" / "ci.py").read_text(encoding="utf-8")
    markers = re.findall(r'cmd \+= \["-m", "([^"]+)"\]', ci)
    assert markers, "ci.py no longer passes -m at all; this guard needs rewriting"
    for expr in markers:
        assert "not live" in expr, (
            f"ci.py passes -m {expr!r}, which REPLACES addopts' \"-m 'not live'\" "
            "and re-selects the tests that spend money"
        )
