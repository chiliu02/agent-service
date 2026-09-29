"""Two version numbers, exactly as every implementation carries them.

`DOCUMENT_VERSION` is the SPECIFICATION's and MUST equal `spec/VERSION` at the
platform root -- every implementation satisfying a given document reports the
same value. `IMPLEMENTATION_VERSION` is this build's, equals `pyproject.toml`'s
`version`, and is what an image tag and a bug report carry.

**`IMPLEMENTATION_VERSION` is a hand-written copy of `pyproject.toml`'s
`version`, and a test in this build fails if they drift.** A copy is allowed
where something reads the original and compares.
"""

from __future__ import annotations

#: MUST equal `spec/VERSION`.
DOCUMENT_VERSION = "0.29.0-snapshot"

#: This build. MUST equal `pyproject.toml`'s `version`. **0.1.0 is its first
#: DELIVERED version**, cut with document 0.22.0; it sat at 0.0.1 while nothing
#: had shipped. Well below the document's number on purpose: the two streams are
#: independent and this one is three releases younger than the others.
IMPLEMENTATION_VERSION = "0.28.0"

#: Matches the directory under `impl/`, because that is what tells two
#: implementations apart. Reported as `deployment.service.impl.name`.
#:
#: **The suffix is load-bearing here in a way it has not been before** (`PI-01`).
#: The other three targets ship no SDK this service could use, or one that is
#: already Python. Pi ships a TypeScript SDK, so `pi-nodejs` is a coherent
#: second build of the SAME target -- it would publish this build's `model_api`
#: and a different name here, which is the case `model_api` was separated from
#: `impl.name` for.
IMPLEMENTATION_NAME = "pi-python"
