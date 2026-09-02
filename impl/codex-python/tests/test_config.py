"""Settings, the process-capacity estimate, and what the entrypoint resolves.

`max_sessions` against the container's process limit.

**The two are configured independently**, so a deployment can advertise a cap
the container cannot carry -- measured at ~30 processes per session, which puts
`pids_limit: 512` at about 16 sessions whatever `max_sessions` says.

The limit is passed in explicitly everywhere below. Reading the real
`/sys/fs/cgroup` would make these tests assert something different on a
developer's machine, in a container, and in CI -- and the one case that matters
most (no limit to read) is exactly the one a host cannot be asked to produce.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.config import (
    PIDS_BASELINE,
    PIDS_PER_SESSION,
    Settings,
    normalise_log_level,
    process_capacity_warning,
    process_limit,
)


def _settings(max_sessions: int) -> Settings:
    return Settings(
        require_credentials=False, require_mounts=False, max_sessions=max_sessions
    )


def test_a_cap_the_container_can_carry_says_nothing() -> None:
    """Silence is the normal case and must stay silent. A boot warning that
    fires on a correct deployment is one an operator learns to skip."""
    assert process_capacity_warning(_settings(8), limit=512) is None


def test_a_cap_the_container_cannot_carry_is_reported() -> None:
    """512 pids is about 16 sessions; 64 is not."""
    warning = process_capacity_warning(_settings(64), limit=512)
    assert warning is not None
    assert "64" in warning and "512" in warning
    # It names the 503, because that is what the operator will actually see
    # when the estimate turns out to be right.
    assert "503" in warning


def test_no_limit_to_read_makes_no_claim() -> None:
    """Not in a container, or started with no `pids_limit`. **Three different
    situations and one honest answer**: nothing can be compared, so nothing is
    said. A guessed limit would warn about a constraint that does not exist."""
    assert process_capacity_warning(_settings(1000), limit=None) is None


def test_the_boundary_is_the_measured_figure_and_not_a_round_number() -> None:
    """Pins the arithmetic rather than the sentence. Exactly what fits must not
    warn; one more must."""
    limit = PIDS_BASELINE + PIDS_PER_SESSION * 4
    assert process_capacity_warning(_settings(4), limit=limit) is None
    assert process_capacity_warning(_settings(5), limit=limit) is not None


def test_process_limit_never_raises() -> None:
    """It is called from the lifespan, where an exception is a failed boot. On
    a host with no cgroup file it must answer `None` rather than fail."""
    value = process_limit()
    assert value is None or isinstance(value, int)


# --- the log level, and the trap underneath it ------------------------------


def test_an_unknown_log_level_names_the_valid_set() -> None:
    """`logging` matches level names case-sensitively, so the boot would
    otherwise abort with `Unknown level: 'info'` from inside `basicConfig` --
    which names neither the variable nor the alternatives."""
    assert normalise_log_level("info") == "INFO"
    with pytest.raises(ValueError, match="unknown log level"):
        normalise_log_level("chatty")


def test_from_env_POPS_the_database_url(monkeypatch) -> None:  # noqa: ANN001
    """**The trap the entrypoint has to route around.** The pop is a security
    requirement -- the agent inherits this process's environment and can run
    shell commands -- and its consequence is that the SECOND `from_env()` in a
    process sees no database at all."""
    monkeypatch.setenv("AGENT_SERVICE_DATABASE_URL", "postgresql://x/y")
    assert Settings.from_env().database_url == "postgresql://x/y"
    assert Settings.from_env().database_url is None


def test_the_entrypoint_resolves_settings_ONCE() -> None:
    """So the app runs on the same object whose log level was read.

    Resolving twice -- once for logging, once inside `create_app()` -- would
    have switched persistence off in production, silently, while every test
    went on passing: the tests pass settings in explicitly and never take the
    second read.
    """
    import agent_service.main as entrypoint

    assert entrypoint.app.state.settings is entrypoint._settings


def test_the_ca_bundle_variable_is_published_and_says_it_REPLACES() -> None:
    """CX-51, and `replaces_default_trust` is the half that matters.

    **`NODE_EXTRA_CA_CERTS` does nothing on this build** -- it is what the Claude
    build reads, and setting it here refuses the connection inside the container
    before anything is sent, so a terminator's access log has no line to
    correlate with.

    **`SSL_CERT_FILE` REPLACES this runtime's root store rather than adding to
    it**: measured, a container given a private authority then fails to reach the
    real API with *invalid peer certificate: UnknownIssuer*. A deployment needing
    both a privately-signed gateway and a public host cannot have both through
    this variable, and it should read that here rather than discover it.
    """
    from agent_service.config import CA_BUNDLE_SOURCE
    from agent_service.spec import specification

    published = specification()["ca_bundle_source"]
    assert published == CA_BUNDLE_SOURCE, "a second copy of a published value drifts"
    assert published == {
        "variable": "SSL_CERT_FILE",
        "shape": "file",
        "replaces_default_trust": True,
    }


def test_the_preboot_spec_names_this_build() -> None:
    """CX-52: `impl` on the pre-boot surface, the same object as on capabilities.

    **`/v1/capabilities` needs a running container and some decisions precede
    one** -- the environment it is created with, and any file written between
    create and start. Until this field existed, a consumer keying a per-build
    table at that moment had only the image tag an operator typed or a provider
    an operator chose, either of which can disagree with what is inside.
    """
    from agent_service.spec import specification
    from agent_service.versions import IMPLEMENTATION_NAME, IMPLEMENTATION_VERSION

    published = specification()
    assert published["impl"] == {
        "name": IMPLEMENTATION_NAME,
        "version": IMPLEMENTATION_VERSION,
    }
    assert published["impl"]["version"] == published["version"]


def test_codex_home_reaches_the_agent_as_an_ABSOLUTE_path(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """CX-55: the app-server resolves it against the WORKSPACE, not against us.

    `Settings.codex_home` defaults to the relative `./codex-home`. Passing that
    string through made the app-server look for it under the workspace, where it
    does not exist, and exit -- surfacing as `TransportClosedError` with no
    mention of the path. Every local run hit it; the container never did,
    because its Dockerfile sets an absolute path.
    """
    from agent_service.sessions import CodexSession

    monkeypatch.chdir(tmp_path)
    (tmp_path / "workspace").mkdir()
    session = CodexSession(cwd=str(tmp_path / "workspace"), codex_home="./codex-home")

    home = session._config.env["CODEX_HOME"]
    assert Path(home).is_absolute(), f"{home!r} is relative; the agent cannot find it"
    assert Path(home).is_dir(), "the directory must exist -- the app-server will not create it"

def test_the_model_api_names_the_target_family_not_the_language() -> None:
    """CX-57: the value is the target family, and the suffix is not in it.

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
    assert published == "codex"
    assert published != IMPLEMENTATION_NAME, "the language suffix leaked in"

def test_the_preboot_specification_imports_no_database_code() -> None:
    """CX-58: `schema_revision` must not cost the pre-boot command SQLAlchemy.

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
    """CX-58: the image states the DDL it requires, and cannot state a different one.

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
    from agent_service.config import Settings

    return Settings()
