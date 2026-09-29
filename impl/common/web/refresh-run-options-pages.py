"""Refresh the two JSON blobs each `run-options-<impl>.html` is generated from.

    uv run --no-project python impl/common/web/refresh-run-options-pages.py

The pages are one template plus two blobs: `BUILD_CAPS`, which is the
`/v1/capabilities` example carried by that build's own OpenAPI document, and
`PROPS`, which is `components.schemas.RunOptions.properties` from the same
document. Both were hand-pasted, which means they drift the moment a capability
or a field description moves -- and a page that renders a stale refusal is worse
than no page, because it looks live.

Standard library only, and it edits nothing but the two blobs: everything
between the `const BUILD_CAPS = {` / `const PROPS = {` lines and their closing
`};` is replaced, and the template around them is left byte for byte.

**Versions are redacted to `x.y.z`.** The page is checked in and a version moves
every release; a redacted value cannot go stale and cannot be mistaken for the
one in front of the reader.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = ROOT / "spec" / "openapi"

BUILDS = ("claude-python", "codex-python", "gemini-python")
REDACTED = "x.y.z"


def _document(build: str) -> dict:
    matches = sorted(SPEC.glob(f"{build}-*.json"))
    if not matches:
        raise SystemExit(f"no OpenAPI document for {build} in {SPEC}")
    return json.loads(matches[-1].read_text(encoding="utf-8"))


def _redact(caps: dict) -> dict:
    """Every version becomes `x.y.z`, at whatever depth it sits."""
    out = dict(caps)
    for key, value in out.items():
        if isinstance(value, dict) and "version" in value:
            out[key] = {**value, "version": REDACTED}
        elif key.endswith("_version") and key != "document_version":
            out[key] = REDACTED
    return out


def _capabilities_example(document: dict) -> dict:
    """The example on the RESPONSE, which is where each build attaches it.

    Not on the schema: the same `Capabilities` model is shared by all three
    builds, so a per-build example could not live there.
    """
    response = document["paths"]["/v1/capabilities"]["get"]["responses"]["200"]
    example = response["content"]["application/json"].get("example")
    if example is None:
        raise SystemExit("the document's /v1/capabilities 200 carries no example")
    # Already redacted by the generator; re-applied so the page cannot carry a
    # real version even if that ever changes.
    return _redact(example)


def _run_options_properties(document: dict) -> dict:
    return document["components"]["schemas"]["RunOptions"]["properties"]


def _replace_blob(page: str, name: str, value: dict) -> str:
    body = json.dumps(value, indent=1, ensure_ascii=False)
    pattern = re.compile(rf"const {name} = \{{.*?\n\}};", re.DOTALL)
    if not pattern.search(page):
        raise SystemExit(f"{name} blob not found -- the template has moved")
    # **A lambda, not a string.** `re.sub` interprets backslash escapes in a
    # replacement string, so a JSON `\n` inside a description would become a
    # real newline and break the JavaScript literal it sits in.
    return pattern.sub(lambda _: f"const {name} = {body};", page, count=1)


def main() -> int:
    for build in BUILDS:
        path = HERE / f"run-options-{build}.html"
        document = _document(build)
        page = path.read_text(encoding="utf-8")
        page = _replace_blob(page, "BUILD_CAPS", _capabilities_example(document))
        page = _replace_blob(page, "PROPS", _run_options_properties(document))
        path.write_text(page, encoding="utf-8")
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
