"""The pre-boot specification, and the version edges.

**Free: no agent, no credential, no container.** Everything here is a property
of this build's own constants, which is the point -- the pre-boot facts have to
answer in an image whose service cannot start, so its inputs must be reachable
without one.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from agent_service.config import (
    CREDENTIAL_ENV_VARS,
    PROVIDER_SELECTOR_ENV_VARS,
    credentials_configured,
)
from agent_service.spec import specification
from agent_service.versions import (
    DOCUMENT_VERSION,
    IMPLEMENTATION_NAME,
    IMPLEMENTATION_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT.parents[1]


def test_document_version_equals_the_platform_spec_version() -> None:
    """`DOCUMENT_VERSION` MUST equal `spec/VERSION`.

    The edge that makes two implementations report the same contract. It is
    pinned here rather than assumed because nothing else reads both files.
    """
    assert DOCUMENT_VERSION == (PLATFORM / "spec" / "VERSION").read_text().strip()


def test_implementation_version_equals_pyproject() -> None:
    """`IMPLEMENTATION_VERSION` MUST equal `pyproject.toml`'s `version`."""
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert IMPLEMENTATION_VERSION == manifest["project"]["version"]


def test_implementation_name_matches_the_directory() -> None:
    """What tells two implementations apart, and it is the directory name."""
    assert IMPLEMENTATION_NAME == ROOT.name


def test_the_two_lists_are_disjoint() -> None:
    """AS-25. A selector satisfies the gate; it authenticates nothing.

    The conformance suite asserts exactly this against a running image, and it
    is cheap enough to assert here too rather than wait for a container.
    """
    assert set(CREDENTIAL_ENV_VARS).isdisjoint(PROVIDER_SELECTOR_ENV_VARS)
    assert CREDENTIAL_ENV_VARS, "a build whose credential list is empty can never boot"


def test_the_gate_reads_exactly_what_the_specification_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What is advertised cannot drift from what is checked.

    Every published name, one at a time: setting it alone must satisfy the gate.
    A name that appears in the list and is not consulted is the shape of a
    capability nothing enforces.
    """
    published = specification()
    names = [*published["credential_sources"], *published["provider_selectors"]]
    for name in names:
        for other in names:
            monkeypatch.delenv(other, raising=False)
        monkeypatch.setenv(name, "x")
        assert credentials_configured(), f"{name} is published but not consulted"


def test_the_gate_is_false_with_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*CREDENTIAL_ENV_VARS, *PROVIDER_SELECTOR_ENV_VARS):
        monkeypatch.delenv(name, raising=False)
    assert not credentials_configured()


def test_endpoint_source_names_the_variable_the_agent_reads() -> None:
    """GP-42, and the history is the point.

    This asserted `None` first, on the grounds that GP-03 left the custom
    gateway unmeasured and a plausible name is not a measurement. The platform's
    boot-gate suite then refused the null: AS-29 requires every image to name
    one variable a provisioner can set.

    **Both were right, and what closed the gap was measuring** --
    `process.env["GOOGLE_GEMINI_BASE_URL"]` is read by the binary and
    interpolated into the request URL. Pinned to the measured name so that
    changing it stays a deliberate act with evidence behind it.
    """
    assert specification()["endpoint_source"] == "GOOGLE_GEMINI_BASE_URL"


def test_the_ca_bundle_variable_is_the_one_this_runtime_reads() -> None:
    """GP-55, and the value is the argument for the field existing.

    **`SSL_CERT_FILE` is what the other two builds read and it does nothing
    here.** One variable set fleet-wide therefore covers two of three and fails
    silently on this one -- which is the guess the field exists to end.

    This is the only build of the three carrying a visible Node runtime, and the
    variable is Node's own: it ADDS to the root store rather than replacing it,
    so a container can reach a privately-signed gateway and a public host at
    once.
    """
    from agent_service.config import CA_BUNDLE_SOURCE

    published = specification()["ca_bundle_source"]
    assert published == CA_BUNDLE_SOURCE, "a second copy of a published value drifts"
    assert published == {
        "variable": "NODE_EXTRA_CA_CERTS",
        "shape": "file",
        "replaces_default_trust": False,
    }


def test_the_preboot_spec_names_this_build() -> None:
    """GP-56: `impl` on the pre-boot surface, the same object as on capabilities.

    **This build is the reason the field was asked for.** The consumer's
    per-build table is keyed at `docker create` time, and the fact it most needs
    to look up there -- which variable carries a certificate authority -- differs
    on this build from the other two. Without a name available before boot, that
    table can only be a single global that is wrong for one of us.
    """
    from agent_service.versions import IMPLEMENTATION_NAME

    published = specification()
    assert published["impl"] == {
        "name": IMPLEMENTATION_NAME,
        "version": IMPLEMENTATION_VERSION,
    }
    assert published["impl"]["version"] == published["version"]
    assert published["impl"]["name"] == "gemini-python"

def test_the_model_api_names_the_target_family_not_the_language() -> None:
    """GP-61: the value is the target family, and the suffix is not in it.

    `impl.name` carries the implementation language and this does not, which
    is what keeps the two fields from being one. Asserted against a literal
    rather than derived from `IMPLEMENTATION_NAME`, because deriving it would
    pass even if the suffix leaked back in.

    The consumer maps this to a vendor API on their own side.
    """
    from agent_service.config import MODEL_API
    from agent_service.spec import specification
    from agent_service.versions import IMPLEMENTATION_NAME

    published = specification()["model_api"]
    assert published == MODEL_API, "a second copy of a published value drifts"
    assert published == "gemini"
    assert published != IMPLEMENTATION_NAME, "the language suffix leaked in"

def test_the_preboot_specification_imports_no_database_code() -> None:
    """GP-62: `schema_revision` must not cost the pre-boot command SQLAlchemy.

    A FRESH INTERPRETER, for the same reason as the wiring test it sits beside:
    once any other test has imported the database seam, an in-process
    `sys.modules` check passes no matter what this module does.

    The value is the Alembic head, which lives next to the boot gate that
    compares it against a live database -- and importing THAT module pulls
    SQLAlchemy. The pre-boot facts are read once, at import, to build the
    document's `PrebootSpec` component, so the constant comes from the
    import-free leaf instead. The command that used to make this urgent is
    gone, and the constraint is kept: it costs nothing, and it keeps the one
    place these constants are read free of anything that can fail.
    """
    import subprocess
    import sys

    code = (
        "import sys;"
        "from agent_service.spec import specification;"
        "d = specification();"
        "assert d['schema_revision'], 'the revision is not published';"
        "assert not [m for m in sys.modules if m.startswith('sqlalchemy')], "
        "'the pre-boot specification imported a database stack'"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr


def test_the_published_schema_revision_is_the_one_the_boot_gate_enforces() -> None:
    """GP-62: the image states the DDL it requires, and cannot state a different one.

    An image depends on two published artifacts -- the OpenAPI document and the
    DDL -- and they move on separate streams, so neither can be read off the
    other. Both are on the pre-boot surface because the database is chosen
    before the container is created.
    """
    from agent_service.spec import specification
    from agent_spec.db.revision import EXPECTED_REVISION

    published = specification()["schema_revision"]
    assert published == EXPECTED_REVISION, "the image would accept a database it refuses"
    assert specification()["document_version"], "the other half of the pair is missing"


# --- the pre-boot facts, published in this build's OWN document --------------


def _preboot_component() -> dict:
    """This build's `PrebootSpec`, straight out of the document it serves."""
    from agent_spec.openapi.preboot import SCHEMA_NAME

    from agent_service.api import create_app

    document = create_app(_preboot_settings()).openapi()
    component = document.get("components", {}).get("schemas", {}).get(SCHEMA_NAME)
    assert isinstance(component, dict), (
        "the document publishes no PrebootSpec, so a consumer holding the "
        "specification must pull an image to learn what this build reads"
    )
    return component


def test_the_document_publishes_this_builds_preboot_facts() -> None:
    """The document must say exactly what this build's constants hold.

    **The consumer depends on the specification at build time and loads images at
    runtime**, and several decisions these facts inform -- which credential
    variable to inject, which variable carries a private certificate authority,
    which database revision to migrate to -- are made before any container
    exists. Publishing them only on the image put a runtime dependency in front
    of a build-time question.

    So the document carries them, and this is what stops it carrying them
    WRONGLY: a published value nothing compares against goes stale silently,
    which is the failure the pre-boot surface had in the first place.
    """
    from agent_spec.openapi.preboot import mismatches

    from agent_service.api import create_app
    from agent_service.spec import specification

    document = create_app(_preboot_settings()).openapi()
    found = mismatches(document, specification())
    assert not found, "the document and the binary disagree: " + "; ".join(found)


def test_the_preboot_component_pins_what_a_consumer_provisions_with() -> None:
    """Every provisioning fact is a `const`, not a free string.

    **This is the whole reason it is in the document rather than only on the
    image.** A shape that says `model_api` is "any non-empty string" tells a
    consumer nothing it can act on; `{"const": "gemini"}` is a constraint a
    validator enforces and a generator emits as a literal type.

    **No enum anywhere**, and that is deliberate: each build states its own
    value, so nothing has to predict how many builds will exist. A closed set in
    a shared file would carry the half we know and imply the half we do not, and
    a fourth build breaking no rule would falsify it.
    """
    properties = _preboot_component()["properties"]
    for field in (
        "document_version",
        "schema_revision",
        "model_api",
        "credential_sources",
        "provider_selectors",
        "auth_enforced",
        "endpoint_source",
    ):
        assert "const" in properties[field], (
            f"{field} is published open, so a consumer reading the specification "
            "still has to start a container to learn it"
        )
    assert "const" in properties["impl"]["properties"]["name"]
    assert "const" in properties["listen"]["properties"]["port"]


def test_the_versions_that_move_are_not_pinned() -> None:
    """`version` and `impl.version` must stay open, or AS-24 breaks on a bump.

    A build bumps for any reason at all, several times between two documents,
    and the document is frozen at a release. A real version pinned here means the
    served document stops matching the published one the first time that happens
    -- AS-24 broken by a change that touched no route. The capabilities example
    beside it learned this the same way.
    """
    properties = _preboot_component()["properties"]
    assert "const" not in properties["version"]
    assert "const" not in properties["impl"]["properties"]["version"]


def _preboot_settings():
    """Declared defaults only -- the same rule the capabilities example follows."""
    from pathlib import Path as _P

    from agent_service.config import Settings

    return Settings(
        workspace_dir=_P("workspace"),
        agent_home_root=_P("temp") / "agent-home",
        transcript_store=_P("temp") / "transcripts",
        gemini_binary=_P("gemini"),
        require_credentials=False,
    )
