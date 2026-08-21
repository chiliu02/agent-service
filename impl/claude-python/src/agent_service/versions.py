"""Two version numbers that used to be one, and what each of them means.

**Plan 8 step 5 broke a pun this codebase relied on.** Until 0.11.0 there was a
single number: `pyproject.toml`'s `version` was passed to FastAPI as `version=`,
so it was simultaneously the build's version and the version of the interface
document the build served. For one implementation that was correct and cheap.
It stops being either the moment a second implementation exists, because two
builds in two languages have to serve the SAME document while being obviously
different builds.

So:

* **`DOCUMENT_VERSION`** is the SPECIFICATION's. It is what `/openapi.json` reports
  as `info.version`, what names `spec/openapi-<version>-<impl>.json`, and
  what AS-24 compares. Every implementation that claims to satisfy a given
  document reports the same value here. The source of truth is
  `spec/VERSION` at the platform root, which this repeats because the
  container has no access to it -- `impl/claude-python/tests/test_api_meta.py`
  is what stops the two drifting.

* **`IMPLEMENTATION_VERSION`** is this build's, and it is
  `pyproject.toml`'s `version`. It appears in `/v1/capabilities` under
  `implementation`, beside `sdk`. It is the number a release is tagged with
  (`agent-service-claude-python:<version>`) and the one a bug report should carry.

They are both `0.13.0` today and that is still a coincidence, not a rule: 0.12.0
introduced the split and moved both at once, and 0.13.0 moved both again because
its two changes happened to be one of each kind -- a specification clause (the bind
address) and an implementation fix (the unreachable-database message). Nothing
requires them to agree again, and nothing should be written that assumes they
do.

**Deliberately importing nothing.** `agent_service.spec` runs in an image
whose service cannot start and imports only `config`; this module has to be as
cheap as that one needs it to be.
"""

from __future__ import annotations

#: The interface document this build implements. MUST equal `spec/VERSION`
#: at the platform root -- pinned by
#: `tests/test_api_meta.py::test_the_served_version_is_the_specification_document_version`.
DOCUMENT_VERSION = "0.19.0"

#: This build. MUST equal `pyproject.toml`'s `version` -- pinned by
#: `tests/test_api_meta.py::test_the_implementation_version_matches_the_package`.
IMPLEMENTATION_VERSION = "0.18.14"

#: Which implementation this is, in the same shape `Sdk.name` uses. Matches the
#: directory under `impl/`, because that is the name a second implementation
#: would be told apart by.
IMPLEMENTATION_NAME = "claude-python"
