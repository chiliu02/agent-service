"""Two version numbers, exactly as every implementation carries them.

`DOCUMENT_VERSION` is the SPECIFICATION's and MUST equal `spec/VERSION` at the
platform root -- every implementation satisfying a given document reports the
same value. `IMPLEMENTATION_VERSION` is this build's, equals `pyproject.toml`'s
`version`, and is what an image tag and a bug report carry.

**`IMPLEMENTATION_VERSION` is a hand-written copy of `pyproject.toml`'s
`version`, and a test in this build fails if they drift.** That is the same
arrangement as the document-version label and `runs_as`: a copy is allowed where
something reads the original and compares.

**The reason this module imports nothing is now weaker than it was.** It was
`agent_service.spec` running as a command in an image whose service could not
start -- and that command was removed in 0.19.0. Deriving the version from
`importlib.metadata` would trade a literal that moves every release for a
distribution name that essentially never moves, and it is worth doing; it is not
worth doing between a release being prepared and the tag being cut.
"""

from __future__ import annotations

#: MUST equal `spec/VERSION`.
DOCUMENT_VERSION = "0.19.0"

#: This build. MUST equal `pyproject.toml`'s `version`.
IMPLEMENTATION_VERSION = "0.0.19"

#: Matches the directory under `impl/`, because that is what tells two
#: implementations apart. Reported as `capabilities.impl.name`.
IMPLEMENTATION_NAME = "codex-python"
