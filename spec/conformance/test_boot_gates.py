"""Conformance: the container tier — AS-2, AS-3, AS-25, AS-28, AS-29, and the
mounts refusal.

**These start containers. They do not talk to a running service**, which is why
they are gated on their own variable:

    AGENT_SERVICE_TEST_IMAGE=agentsvc-conf-agent-service:latest uv run pytest \
        tests/conformance/test_boot_gates.py

The rest of this package asks a *running* service what it does. That can never
reach AS-2's actual claim, because a service that exited 3 is not one anything
can talk to — `test_as2_a_running_service_proves_its_own_boot_gate_passed` says
so in its own docstring and checks only the shape of the claim. This module is
the missing half: it starts deliberately misconfigured images and reads the exit
code.

**The image name is required and deliberately has no default.** This machine
carries an `agent-service:latest` tag built 2026-08-02 which boots happily with
no credential at all, and an `agent-service:glibc` which serves 0.2.0. A default
would have quietly measured the wrong image — the first probe written while
building this module did exactly that, and reported that the credential gate did
not fire. Compose builds `<project>-agent-service`, so the name is
deployment-specific and the caller must say which one it means.

Free — no session, no turn, no credential. Slow: each case is a container start.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

IMAGE_ENV = "AGENT_SERVICE_TEST_IMAGE"
IMAGE = os.environ.get(IMAGE_ENV)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not IMAGE,
        reason=(
            f"{IMAGE_ENV} is not set. Point it at the image under test, e.g. "
            "AGENT_SERVICE_TEST_IMAGE=agentsvc-conf-agent-service:latest"
        ),
    ),
]

#: uvicorn's line once the lifespan's startup returned. Reaching it means every
#: gate passed, so a boot that is going to succeed is detected in a second or
#: two rather than by waiting out the timeout.
STARTUP_COMPLETE = "Application startup complete"

#: `config.py` raises from the lifespan, uvicorn turns that into
#: `sys.exit(STARTUP_FAILURE)`. The number is the specification, not an implementation
#: detail: a container orchestrator distinguishes 3 from 137 and from 0.
STARTUP_FAILURE = 3


def _docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def _logs(container: str) -> str:
    """BOTH streams. `docker logs` relays the container's stderr to its own,
    and uvicorn -- including every gate's refusal message -- logs to stderr.

    Reading `.stdout` alone returned empty logs for every container: the
    refusal assertions failed with nothing to match on, and `boot()` never saw
    its startup line, so each successful boot waited out the full timeout and
    the module took four minutes. Measured while writing it.
    """
    result = subprocess.run(
        ["docker", "logs", container], capture_output=True, text=True, check=False
    )
    return result.stdout + result.stderr


def boot(env: dict[str, str], timeout_s: float = 30.0) -> tuple[int | None, str]:
    """Start the image with `env` and report `(exit_code, logs)`.

    `exit_code` is `None` when the container was still running at the timeout
    **or** reached `STARTUP_COMPLETE` — both mean every gate passed. Any real
    integer is a refusal, and the test says which one it expects.
    """
    args = ["run", "-d"]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    container = _docker(*args, IMAGE).strip()

    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = _docker(
                "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", container
            ).split()
            logs = _logs(container)
            if state[0] == "exited":
                return int(state[1]), logs
            if STARTUP_COMPLETE in logs:
                return None, logs
            time.sleep(0.25)
        return None, _logs(container)
    finally:
        _docker("rm", "-f", container, check=False)


@contextlib.contextmanager
def running(env: dict[str, str], timeout_s: float = 30.0) -> Iterator[str]:
    """Like `boot`, but hands back a container that is STILL RUNNING.

    `boot` reads an exit code and removes the container, which is the whole
    shape of a gate test. AS-28 is the opposite question — *where is the socket
    of a service that started successfully* — so it needs the container alive
    long enough to look inside it.
    """
    args = ["run", "-d"]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    container = _docker(*args, IMAGE).strip()
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = _docker(
                "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", container
            ).split()
            logs = _logs(container)
            if state[0] == "exited":
                raise AssertionError(
                    f"the image exited {state[1]} instead of starting. Logs:\n{logs}"
                )
            if STARTUP_COMPLETE in logs:
                yield container
                return
            time.sleep(0.25)
        raise AssertionError(
            f"the image did not reach startup within {timeout_s}s. "
            f"Logs:\n{_logs(container)}"
        )
    finally:
        _docker("rm", "-f", container, check=False)


#: `/proc/net/tcp`'s state column for LISTEN. The file is documented in
#: `Documentation/networking/proc_net_tcp.rst`; the states are the TCP state
#: enum in hex, and `0A` is `TCP_LISTEN`.
TCP_LISTEN = "0A"

#: The local address a socket bound to every IPv4 interface reports. The column
#: is `<address>:<port>`, both hex, and the address is the raw 32-bit value —
#: byte order does not matter for this one because 0.0.0.0 is zero either way.
#: Loopback would read `0100007F`, which is what makes this discriminating.
ANY_IPV4 = "00000000"


def _listening_ipv4_ports(container: str) -> set[int]:
    """Every IPv4 port the container is LISTENing on, read from the kernel.

    **Not `ss`, `netstat` or `lsof`** — none is in this image, and installing
    one would measure a container that is not the one under test. `/proc` is
    always there and is the kernel's own answer rather than a tool's reading
    of it.
    """
    raw = _docker("exec", container, "cat", "/proc/net/tcp")
    ports: set[int] = set()
    for line in raw.splitlines()[1:]:  # first line is the column header
        fields = line.split()
        if len(fields) < 4 or fields[3] != TCP_LISTEN:
            continue
        address, _, port = fields[1].partition(":")
        if address == ANY_IPV4:
            ports.add(int(port, 16))
    return ports


#: The labels `docker inspect` carries. They are the key that finds the document
#: holding everything else -- and reading them executes nothing.
IMPL_LABEL = "com.npf.agent-service.impl"
DOCUMENT_LABEL = "com.npf.agent-service.document-version"
REVISION_LABEL = "com.npf.agent-service.schema-revision"


def _pinned(properties: dict) -> dict:
    """The values a `PrebootSpec` component pins, as the object it describes.

    A field with no `const` is one the document deliberately leaves open --
    `version` and `impl.version` move on the implementation stream -- so it is
    absent here rather than present and null. Absent and null differ on this
    surface and the distinction is load-bearing.
    """
    out = {}
    for name, schema in properties.items():
        if not isinstance(schema, dict):
            continue
        nested = schema.get("properties")
        if isinstance(nested, dict):
            inner = _pinned(nested)
            if inner:
                out[name] = inner
        elif "const" in schema:
            out[name] = schema["const"]
    return out


@pytest.fixture(scope="module")
def preboot_spec() -> dict[str, object]:
    """AS-25, answered from the SPECIFICATION rather than from a command.

    **This was `docker run --rm <image> agent-service-openapi` until 0.19.0.** The
    command is gone: every fact it printed is published in each implementation's
    own OpenAPI document as the `PrebootSpec` component, values pinned by
    `const`.

    **What changed is which artifact holds the truth, not which facts exist.** A
    consumer resolves the specification at build time and loads an image at
    runtime, and every decision these facts inform -- which credential variable
    to inject, which variable carries a private certificate authority, which
    revision to migrate to -- is made before a container exists. Requiring a
    container run put a runtime dependency in front of a build-time question.

    **Still an IMAGE test, and it still executes nothing.** `docker inspect`
    reads metadata rather than starting a process; the three labels say which
    build this is, which document it serves and which revision it wants, and the
    document keyed by the first two holds the rest. So this measures a real
    image against a published artifact -- which is more than the command could
    do, because the command could only ever agree with itself.

    NAMED `preboot_spec` AND NOT `published_spec`, because `conftest.py` has a
    session-scoped `published_spec` that fetches the document from a RUNNING
    service and skips when `AGENT_SERVICE_TEST_BASE_URL` is unset. This module
    talks to an image and never to a service, so colliding on that name silently
    skipped five of these tests -- as skips, not failures, which is the way it
    would have gone unnoticed.
    """
    labels = json.loads(
        _docker("inspect", "--format", "{{json .Config.Labels}}", IMAGE)
    )
    for label in (IMPL_LABEL, DOCUMENT_LABEL, REVISION_LABEL):
        assert labels.get(label), (
            f"the image carries no {label} label, so nothing identifies which "
            "published document states its pre-boot facts"
        )
    version, build = labels[DOCUMENT_LABEL], labels[IMPL_LABEL]
    name = f"{build}-{version}.json"
    root = Path(__file__).resolve().parents[1]
    path = root / "openapi" / name
    assert path.is_file(), (
        f"{name} is not published, so nothing outside this image states which "
        "credential variable it reads"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    component = document.get("components", {}).get("schemas", {}).get("PrebootSpec")
    assert isinstance(component, dict), (
        f"{name} has no PrebootSpec component, so a consumer holding the "
        "specification would still have to start a container"
    )
    specification = _pinned(component.get("properties", {}))
    # **The one place the image and the document are compared**, and it is what
    # keeps the rest of this module honest: every assertion below reads the
    # document, so without this they would measure a file rather than an image.
    # The labels are baked at build time from the same constants the document is
    # generated from, so a disagreement is a build that shipped against a
    # document it does not match.
    assert specification.get("schema_revision") == labels[REVISION_LABEL], (
        f"the image is labelled schema-revision {labels[REVISION_LABEL]!r} and "
        f"the document it names says {specification.get('schema_revision')!r}. "
        "One image, one revision"
    )
    assert specification.get("impl", {}).get("name") == build, (
        "the document's impl.name disagrees with the image's own label"
    )
    assert specification["credential_sources"], "AS-25: credential_sources came back empty"
    # **`provider_selectors` is NOT asserted non-empty here**, and it was until
    # 2026-08-08. That assertion contradicted the very test this fixture feeds:
    # an empty list is a truthful answer for a build whose SDK has no cloud
    # selectors, `impl/codex-python` is that build, and the fixture failed at
    # collection and took every test in this module with it. A fixture asserting
    # more than the clause is a suite that cannot measure a second
    # implementation, which is the whole reason this package is the
    # specification's and not any implementation's.
    return specification


def test_as25_the_two_lists_are_published_without_booting(
    preboot_spec: dict[str, object],
) -> None:
    """Both lists are readable with nothing started and nothing executed.

    The clause was satisfied by a command until 0.19.0 and is satisfied by
    the published document now. The property AS-25 actually asks for is
    unchanged -- *readable before boot* -- and it is strictly better served:
    a consumer no longer needs the image at all, only its labels.
    """
    # **NOT the specific names.** This suite is the specification's, and AS-25
    # requires the two lists to be PRINTED WITHOUT BOOTING -- not to contain any
    # particular variable. Hardcoding Claude's names here would fail every
    # non-Claude image, which is a defect in the suite rather than in the image;
    # the live tier had exactly that bug and it was found on 2026-08-08 by the
    # first second implementation to run against it.
    assert isinstance(preboot_spec["credential_sources"], list)
    assert preboot_spec["credential_sources"], (
        "AS-25: credential_sources is empty, so no credential could ever satisfy "
        "this image's boot gate"
    )
    assert isinstance(preboot_spec["provider_selectors"], list)
    # `provider_selectors` MAY be empty -- a build whose SDK has no cloud
    # selectors publishes `[]`, which is a truthful answer. Disjointness is the
    # property that matters and it is implementation-neutral.
    assert set(preboot_spec["credential_sources"]).isdisjoint(
        preboot_spec["provider_selectors"]
    )


def test_as29_the_image_publishes_where_it_will_listen(
    preboot_spec: dict[str, object],
) -> None:
    """AS-29's shape, read from the image without booting it (0.13.0).

    A consumer that provisions containers has to decide how to REACH one before
    it exists, so this rides the same pre-boot channel as `credential_sources`
    rather than `/v1/deployment` — by the time an endpoint could answer, the
    caller has already connected.

    `port` must be an integer, not a string: a consumer that has to parse it is
    a consumer that can get the parse wrong.
    """
    listen = preboot_spec["listen"]
    assert isinstance(listen, dict), f"AS-29: `listen` is {type(listen).__name__}"
    assert isinstance(listen["port"], int), (
        f"AS-29: port is {listen['port']!r}, which a consumer would have to parse"
    )
    assert isinstance(listen["address"], str)


def test_as28_it_listens_on_all_ipv4_interfaces_and_not_on_loopback(
    preboot_spec: dict[str, object],
) -> None:
    """AS-28, measured against the kernel rather than against the image's `CMD`
    (0.13.0). **This is the clause that protects a consumer's only route in.**

    After a consumer removes host port publishing, the whole route to a
    container is another container on the same Docker network resolving it by
    name — which works only if the service is bound to every interface. A
    change to loopback would look like a hardening improvement and would
    silently remove that route: this service's own security posture calls
    loopback binding a control, and it means the HOST side, where `compose.yaml`
    publishes `127.0.0.1:8000:8000` and is right.

    So the check reads `/proc/net/tcp` inside a running container and requires a
    LISTEN socket on `0.0.0.0`. Reading the `CMD` instead would prove only that
    the arguments say the right thing, which is the assertion an implementation
    in another language could not satisfy at all.

    **It also closes AS-29's second half** — *the port it prints is the port the
    service actually listens on* — by driving the expectation from the published
    value. A published port that had drifted from the socket would send a
    consumer confidently nowhere, which is worse than publishing nothing.

    `::` is deliberately not asserted in either direction. AS-28 requires
    nothing there, so an implementation that adds a dual-stack listener still
    conforms; it would only ever add a route.
    """
    listen = preboot_spec["listen"]
    assert isinstance(listen, dict)
    published_port = listen["port"]

    with running(
        {
            "AGENT_SERVICE_REQUIRE_CREDENTIALS": "false",
            "AGENT_SERVICE_REQUIRE_MOUNTS": "false",
        }
    ) as container:
        ports = _listening_ipv4_ports(container)
        # Read verbatim for the failure message: if nothing is on 0.0.0.0 the
        # useful question is what it IS bound to, and "loopback" is the answer
        # this test exists to catch.
        raw = _docker("exec", container, "cat", "/proc/net/tcp")

    assert published_port in ports, (
        f"AS-28/AS-29: the image publishes port {published_port} but nothing is "
        f"LISTENing on 0.0.0.0:{published_port}. Sockets on 0.0.0.0: "
        f"{sorted(ports) or 'none'}. A loopback bind reads `0100007F` in the "
        f"local_address column below and would remove a consumer's only route "
        f"into this container.\n/proc/net/tcp:\n{raw}"
    )


def test_as2_no_credential_refuses_to_boot_with_exit_3(
    preboot_spec: dict[str, object],
) -> None:
    """The clause the live suite cannot reach, measured.

    `require_mounts` is switched off so this isolates ONE gate. A test that
    tripped both would pass while proving nothing about which one fired.
    """
    code, logs = boot({"AGENT_SERVICE_REQUIRE_MOUNTS": "false"})

    assert code == STARTUP_FAILURE, f"expected exit 3, got {code}. Logs:\n{logs}"
    # The message must be actionable without reading the source: what to set,
    # and the way out for a docs-only boot.
    #
    # **Driven from the image's own published list, not from a name written
    # here.** This assertion read `"ANTHROPIC_API_KEY" in logs` until
    # 2026-08-08, which made it a test of one SDK rather than of the clause --
    # the same defect the live tier's credential assertions had, found the same
    # way. What AS-2 requires is that the refusal names a credential a caller
    # could actually set; which name that is belongs to the implementation.
    published = preboot_spec["credential_sources"]
    assert any(name in logs for name in published), (
        f"the refusal names none of the image's own published credential "
        f"sources {published}, so an operator reading it cannot act on it. "
        f"Logs:\n{logs}"
    )
    assert "AGENT_SERVICE_REQUIRE_CREDENTIALS=false" in logs
    # It is a presence check, so nothing here can echo a value.
    assert "MissingCredentials" in logs


def test_as2_any_one_published_variable_satisfies_the_gate(
    preboot_spec: dict[str, object],
) -> None:
    """"Any one variable from either array satisfies the boot gate."

    Driven from the image's own published lists (AS-25), not from a copy here —
    a matrix that drifted from the specification would be worse than no matrix.
    """
    names = [
        *preboot_spec["credential_sources"],
        *preboot_spec["provider_selectors"],
    ]
    refused = {}
    for name in names:
        code, logs = boot(
            {"AGENT_SERVICE_REQUIRE_MOUNTS": "false", name: "conformance-probe-value"}
        )
        if code is not None:
            refused[name] = (code, logs[-400:])

    assert not refused, f"published variables that did NOT satisfy the gate: {refused}"


def test_as3_a_provider_selector_is_not_read_as_a_credential(
    preboot_spec: dict[str, object],
) -> None:
    """AS-3, the half a document cannot show: a selector satisfies the gate and
    supplies no credential.

    The service boots, and `/healthz` reporting `credentials_configured: true`
    is the *gate's* view, not a claim that a key exists. The point being pinned
    is that the two lists are wired to the same gate and to nothing else —
    `test_as1_as3_capabilities_publishes_two_credential_lists` covers their
    disjointness on the live service.

    **Skipped when the image publishes no selectors**, which is a truthful
    answer rather than a gap -- `impl/codex-python` has no measured cloud
    selector for Codex and publishes `[]` rather than guessing one. There is
    nothing to assert AS-3 about on such a build, and a suite that failed it
    would be demanding a field of every implementation that the clause makes
    optional.
    """
    selectors = preboot_spec["provider_selectors"]
    if not selectors:
        pytest.skip("this image publishes no provider selectors; AS-3 has no subject")
    selector = selectors[0]
    code, logs = boot({"AGENT_SERVICE_REQUIRE_MOUNTS": "false", selector: "1"})
    assert code is None, f"{selector} did not satisfy the gate: exit {code}\n{logs}"


def test_a_variable_outside_the_published_lists_does_not_satisfy_the_gate(
    preboot_spec: dict[str, object],
) -> None:
    """The second sentence of AS-2: "No variable outside them does."

    Without this, a gate that accepted anything vaguely credential-looking would
    pass every test above.

    **The near-miss is DERIVED from a published name rather than written here.**
    `ANTHROPIC_TOKEN` was the hardcoded probe until 2026-08-08 — a fine near-miss
    for one image and a meaningless one for any other, since a build that never
    heard of Anthropic refuses it for the wrong reason and the test passes
    vacuously. Swapping the last segment for `TOKEN` produces the mistake a
    caller actually makes (`OPENAI_API_TOKEN` for `OPENAI_API_KEY`), against
    whichever names this image publishes.
    """
    published = {
        *preboot_spec["credential_sources"],
        *preboot_spec["provider_selectors"],
    }
    first = sorted(preboot_spec["credential_sources"])[0]
    near_miss = first.rsplit("_", 1)[0] + "_TOKEN" if "_" in first else first + "_TOKEN"
    assert near_miss not in published, (
        f"the derived near-miss {near_miss} is itself published, so this test "
        f"would assert the opposite of what it means. Published: {sorted(published)}"
    )

    code, logs = boot(
        {"AGENT_SERVICE_REQUIRE_MOUNTS": "false", near_miss: "not-a-published-name"}
    )
    assert code == STARTUP_FAILURE, (
        f"{near_miss} is outside the published lists and satisfied the gate: "
        f"exit {code}\n{logs}"
    )


def test_an_empty_value_does_not_satisfy_the_gate(
    preboot_spec: dict[str, object],
) -> None:
    """`credentials_configured()` is a presence check on a TRUTHY value.

    Setting a published name to the empty string is what an unset shell variable
    expands to in a compose file. Accepting it would let `KEY=${MISSING}` boot a
    service that cannot authenticate -- exactly the failure the gate exists to
    prevent.

    **The name comes from the image**, for the same reason as the test above: a
    hardcoded one is refused by an unrelated build for an unrelated reason, and
    the test then proves nothing about emptiness at all.
    """
    name = sorted(preboot_spec["credential_sources"])[0]
    code, logs = boot({"AGENT_SERVICE_REQUIRE_MOUNTS": "false", name: ""})
    assert code == STARTUP_FAILURE, (
        f"an empty value for the published {name} satisfied the gate: "
        f"exit {code}\n{logs}"
    )


def test_the_mounts_gate_refuses_and_names_the_directory() -> None:
    """The other gate, isolated the same way: credentials off, mounts on.

    `/workspace` EXISTS in the image — the service creates it — so "it exists"
    is precisely the state the bug produces, and the check is that it is on a
    real mount. A container started with no `-v` must be refused.
    """
    code, logs = boot({"AGENT_SERVICE_REQUIRE_CREDENTIALS": "false"})

    assert code == STARTUP_FAILURE, f"expected exit 3, got {code}. Logs:\n{logs}"
    assert "MissingMounts" in logs
    assert "AGENT_SERVICE_WORKSPACE_DIR" in logs
    assert "AGENT_SERVICE_REQUIRE_MOUNTS=false" in logs


def test_both_gates_off_boots_which_is_what_makes_the_others_mean_something() -> None:
    """The control. Every test above asserts a refusal; this asserts the image
    can boot at all.

    Without it, an image that was broken for some unrelated reason -- a bad
    entrypoint, a missing dependency -- would exit non-zero every time and read
    as a perfectly enforced set of gates.
    """
    code, logs = boot(
        {
            "AGENT_SERVICE_REQUIRE_CREDENTIALS": "false",
            "AGENT_SERVICE_REQUIRE_MOUNTS": "false",
        }
    )
    assert code is None, f"the image did not boot with both gates off: exit {code}\n{logs}"
    assert STARTUP_COMPLETE in logs


# --- the pre-boot fields a caller needs BEFORE it starts a container ---------


def test_auth_enforced_is_published_before_boot(preboot_spec) -> None:  # noqa: ANN001
    """`auth_enforced` says whether this BINARY checks the credential.

    **Distinct from `auth_required` and the distinction is the whole ask.**
    `auth_required` is on `/healthz` and `/v1/deployment` and means *a token is
    configured on this running instance*. This one means *this image checks the
    header at all* -- and a caller needs it while provisioning, when there is no
    service to ask, which is exactly why it is here and not there.

    A consumer requested it after finding it could not tell the two apart: an
    image that takes a token and enforces nothing would report `auth_required:
    true` while protecting nothing.
    """
    assert "auth_enforced" in preboot_spec, (
        "AS-25: the pre-boot specification does not publish auth_enforced, so a "
        "caller cannot tell an image that enforces a token from one that only "
        "reports having been given one"
    )
    assert isinstance(preboot_spec["auth_enforced"], bool)


def test_endpoint_source_names_one_variable(preboot_spec) -> None:  # noqa: ANN001
    """`endpoint_source` names the variable that moves this build's endpoint.

    **Singular, not a list**, because no build needs more than one and a consumer
    that has to choose from a list is a consumer guessing. If one ever does, the
    agreed shape is a list whose first entry the consumer takes.

    **It is not derivable from `credential_sources`.** One build's CLI reads the
    variable from the ambient environment; another's app-server reads no variable
    at all and the service translates it. A consumer injecting the wrong name gets
    a container that silently reaches the public API with a private key.
    """
    assert "endpoint_source" in preboot_spec, (
        "AS-25: the pre-boot specification does not publish endpoint_source, so a "
        "caller cannot know which variable redirects this image's model traffic"
    )
    value = preboot_spec["endpoint_source"]
    assert isinstance(value, str) and value, "endpoint_source must be a non-empty string"
    # A name, not a URL: this says WHERE to put the endpoint, never what it is.
    assert "://" not in value, (
        f"endpoint_source is {value!r}, which looks like a URL. It names an "
        "environment VARIABLE"
    )


def test_impl_names_the_build_before_it_runs(preboot_spec) -> None:  # noqa: ANN001
    """`impl` is on the pre-boot surface as well as on `/v1/deployment`.

    **The same object in two places, deliberately, and it is not a duplicate that
    can drift** -- both are built from one constant per build.

    `/v1/deployment` needs a RUNNING container, and two things a provisioning
    consumer does happen strictly before that: the environment a container is
    created with, and any file written between create and start -- a certificate
    authority among them, which cannot be added afterwards because the runtime
    reads its trust store once at startup. A consumer keying a per-build table
    therefore has to key it at create time, and until this field existed it could
    not.

    **The two substitutes are both worse and that is the argument.** An image tag
    is a string an operator typed; a configured provider is a field an operator
    chose. Either can disagree with what is actually running inside the image.
    `impl.name` is the image's own statement about itself.
    """
    assert "impl" in preboot_spec, (
        "AS-25: the pre-boot specification does not publish impl, so a caller "
        "cannot tell which build an image is without starting it -- and the "
        "decisions that need the answer are made before it starts"
    )
    impl = preboot_spec["impl"]
    assert isinstance(impl, dict), f"impl is {impl!r}; it is an object"
    assert isinstance(impl.get("name"), str) and impl["name"], (
        "impl.name must be a non-empty string, and it is what a consumer keys on"
    )
    # **The VERSION is deliberately absent, and that is the assertion.** It moves
    # on the implementation stream -- a build bumps several times between two
    # documents -- so the document leaves it open rather than pinning a value
    # that would break AS-24 on the next bump. A consumer that needs it reads the
    # image tag or `GET /v1/capabilities`, both of which move with the build.
    assert "version" not in impl, (
        "the document pins impl.version. A build bumping would then serve a "
        "document that no longer matches its published one, which is AS-24 "
        "broken by a change that touched no route"
    )


def test_ca_bundle_source_says_how_a_private_authority_is_delivered(
    preboot_spec,  # noqa: ANN001
) -> None:
    """`ca_bundle_source` names the variable an extra CA is delivered under.

    **The third variable of this kind, and the one no build's surface reveals.**
    `credential_sources` says which variable carries a key and `endpoint_source`
    which one moves the endpoint; this says which one carries trust. A consumer
    behind its own TLS terminator must deliver a private authority into the
    container or every turn fails at the handshake -- and the name is not
    inferable: two of the three builds here have no `node` on the PATH, and each
    embeds a different runtime honouring a different name.

    **A consumer that guesses one name fleet-wide is wrong on at least one
    build**, which is not hypothetical: `SSL_CERT_FILE` works on two of the three
    and does nothing on the third.

    **Present is required; a value of `null` is a real answer** -- *measured, and
    this build honours the OS trust store only* -- and is distinct from the field
    being absent, which means nobody looked. That is the same distinction
    `llm_correlation` draws, and for the same reason.
    """
    assert "ca_bundle_source" in preboot_spec, (
        "AS-25: the pre-boot specification does not publish ca_bundle_source, so "
        "a caller behind a private certificate authority cannot know which "
        "variable delivers it, and a wrong guess fails every turn at the "
        "handshake with nothing in the terminator's log to correlate"
    )
    value = preboot_spec["ca_bundle_source"]
    if value is None:
        return  # measured, and this build reads no such variable

    assert isinstance(value, dict), (
        f"ca_bundle_source is {value!r}; it is an object, or null when there is "
        "no such variable"
    )
    variable = value.get("variable")
    assert isinstance(variable, str) and variable, (
        "ca_bundle_source.variable must name a non-empty environment variable"
    )
    assert "/" not in variable and "\\" not in variable, (
        f"ca_bundle_source.variable is {variable!r}, which looks like a path. It "
        "names an environment VARIABLE; the path is the consumer's to choose"
    )
    # A file and a directory are not interchangeable: pointing either variable in
    # use here at a directory is refused by every one of these runtimes, and the
    # failure is indistinguishable from the wrong name.
    assert value.get("shape") in {"file", "directory"}, (
        f"ca_bundle_source.shape is {value.get('shape')!r}; a consumer writing "
        "one PEM needs to know where to put it"
    )
    # Whether the DEFAULT trust store survives. False on a build that adds to it,
    # true on one that replaces it -- and a container on a replacing build cannot
    # reach a public host and a privately-signed one at the same time.
    assert isinstance(value.get("replaces_default_trust"), bool), (
        "ca_bundle_source.replaces_default_trust must be a bool: a deployment "
        "that also reaches a public host over TLS needs it before it fails"
    )



def test_the_published_uid_is_the_uid_the_container_actually_runs_as(
    preboot_spec: dict[str, object],
) -> None:
    """`PrebootSpec.runs_as` is a hand-written copy, so it is checked against `id`.

    **A consumer acts on this before the container exists**, which is the whole
    reason it is published: Docker creates a missing bind-mount point as
    `root:root 0755`, the service runs as a non-root uid, and the first thing the
    agent writes fails with nothing naming the cause. `Config.User` on the image
    answers a NAME, which is the wrong type for a host filesystem and resolves to
    a number only by running the container -- strictly too late.

    So the number is written by hand into `config.py` beside the Dockerfile's
    `useradd`, and a hand-written copy of a fact needs a check that reads the
    fact. This one runs `id` in the image and compares.
    """
    runs_as = preboot_spec["runs_as"]
    assert isinstance(runs_as, dict), (
        "AS-25: the pre-boot spec does not publish `runs_as`, so nothing names "
        "the uid a consumer must chown a bind-mounted directory to"
    )

    for key, flag in (("uid", "-u"), ("gid", "-g")):
        published = runs_as[key]
        measured = int(_docker("run", "--rm", "--entrypoint", "id", IMAGE, flag))
        assert published == measured, (
            f"the document pins runs_as.{key}={published} and the image answers "
            f"{measured}. A consumer chowning a host directory to {published} "
            f"would hand it to the wrong {key[:-2] or key}"
        )
