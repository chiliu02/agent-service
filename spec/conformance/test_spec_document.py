"""Conformance, document tier: the published spec satisfies the specification.

**No service, no Docker, no tokens.** These read `spec/openapi-<version>-<impl>.json`
for the version in `pyproject.toml` and run `predicates.py` over it, so they run
on a bare checkout — including on a machine that has never built the image.

Why this tier is worth having when the live tier exists: AS-24 proves a running
service serves *exactly* the published document. So a clause proved against the
document holds for the service too, without a container in the loop. The live
tier is then free to spend its time on what a document cannot show — real status
lines, real headers, real SSE framing, the CLI subprocess.
"""

from __future__ import annotations

from typing import Any

import pytest

from . import predicates


@pytest.mark.parametrize("clause", sorted(predicates.PREDICATES))
def test_the_published_document_satisfies_the_clause(
    clause: str, pinned_spec: dict[str, Any]
) -> None:
    predicates.PREDICATES[clause](pinned_spec)
