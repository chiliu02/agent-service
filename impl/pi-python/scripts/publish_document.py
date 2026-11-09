"""Write this build's OpenAPI document into `spec/openapi/`.

**AS-24 is byte equality**: what this writes is exactly what a running container
serves at `/openapi.json`, so the document is generated from the app rather than
hand-maintained.

    uv run python scripts/publish_document.py

**The settings used are the reference ones**, not a live deployment's
(`capabilities.reference_capabilities`), because a document that varied with an
operator's port or cap would differ from the published one the moment anything
was configured.

**A snapshot filename is regenerated at will; a bare version is not.** Renaming
one to a released number, or moving `spec/VERSION`, is the user's decision every
time -- the platform's versioning document at the repository root has the whole
process, and this script deliberately implements none of it.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from agent_service.api import create_app
from agent_service.config import Settings
from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_NAME

#: The same deployment-invariant settings `reference_capabilities()` uses. They
#: are duplicated rather than imported because that helper returns a built
#: payload and this needs the `Settings` the app is constructed from.
REFERENCE = Settings(
    workspace_dir=PurePosixPath("/workspace"),
    agent_dir_root=PurePosixPath("/var/lib/agent-service/agent-dirs"),
    session_store=PurePosixPath("/var/lib/agent-service/sessions"),
    pi_binary=Path("agent-not-probed-for-the-published-example"),
    # The document must be generatable on a machine with no credential.
    require_credentials=False,
)


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    out = root / "spec" / "openapi" / f"{IMPLEMENTATION_NAME}-{DOCUMENT_VERSION}.json"
    document = create_app(REFERENCE).openapi()
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(root)} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
