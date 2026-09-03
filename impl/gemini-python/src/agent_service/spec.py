"""The pre-boot facts, and the source of the document's `PrebootSpec`.

**This was a COMMAND until 0.19.0** -- `docker run --rm <image>
agent-service-spec` -- and it is not one any more. Everything it printed is now
published in this build's own OpenAPI document, as the `PrebootSpec` component
with the values pinned by `const`, so a consumer reads them from an artifact it
already resolves at build time instead of by running a container.

`agent_spec.openapi.preboot` turns this dictionary into that component, and
`api.py` attaches it inside `create_app` -- which it must, because AS-24 is byte
equality between the published document and what a running service serves.

WHAT THE FACTS ARE FOR. Which credential variable this image reads, which
variable moves its endpoint, which one delivers a private certificate authority,
which DDL revision it requires, and where it listens. Every one is decided
BEFORE a container exists -- the environment it is created with, a certificate
written between create and start, the database it is pointed at -- which is why
none of them can be answered by `GET /v1/capabilities`.

**`docker inspect` is the entry point now.** The image's labels carry the impl
and the document version, which is the key that finds the document holding the
rest. Nothing has to be executed.

Still imports NOTHING but `config` and `versions`. It no longer has to run in an
image whose service cannot start, but the constraint costs nothing and keeps the
one place these constants are read free of anything that could fail.
"""


from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from agent_service.config import (
    CA_BUNDLE_SOURCE,
    CREDENTIAL_ENV_VARS,
    MODEL_API,
    ENDPOINT_ENV_VAR,
    LISTEN_ADDRESS,
    LISTEN_PORT,
    RUNS_AS_GID,
    RUNS_AS_UID,
    PROVIDER_SELECTOR_ENV_VARS,
)
from agent_spec.db.revision_id import EXPECTED_REVISION
from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_NAME


def specification() -> dict[str, object]:
    """What a caller needs before boot -- credentials, and where to connect."""
    try:
        build_version = version("agent-service-gemini-python")
    except PackageNotFoundError:  # pragma: no cover - only outside an install
        build_version = None
    return {
        "version": build_version,
        "document_version": DOCUMENT_VERSION,
        # **The OTHER thing this image is built against** (GP-62). An image
        # depends on two published artifacts -- the OpenAPI document above and
        # the DDL -- and they move on separate streams, so one cannot be read
        # off the other. It was baked into every image already and published
        # nowhere: an operator asking "will this accept my database" had to
        # start a container and read the refusal.
        #
        # Pre-boot rather than on `/v1/capabilities` for the usual reason: the
        # database is chosen before the container is created.
        "schema_revision": EXPECTED_REVISION,
        # **The build's own name, on the surface a caller reads BEFORE the
        # container runs.** It was already computed and published twice --
        # `capabilities.impl` and the released document filenames -- and the
        # pre-boot spec was the one place it was absent, which is the wrong
        # side of the line `credential_sources` and `endpoint_source` are on:
        # a consumer keying a per-build table has to key it at `docker create`
        # time, when nothing is running to ask.
        #
        # **The two substitutes a consumer is left with are both worse**: an
        # image tag is a string an operator typed and a configured provider is
        # a field an operator chose, so either can disagree with what is
        # actually running. This cannot.
        #
        # Same object as `/v1/capabilities`, and `version` above is the same
        # local, so the two copies of it cannot drift.
        "impl": {"name": IMPLEMENTATION_NAME, "version": build_version},
        "credential_sources": list(CREDENTIAL_ENV_VARS),
        # The agent target this build drives -- `gemini`, the family name
        # without the language suffix (GP-61). A consumer relaying to a vendor
        # maps it: `gemini` is the Gemini API.
        "model_api": MODEL_API,
        "provider_selectors": list(PROVIDER_SELECTOR_ENV_VARS),
        # **TRUE, and it means THIS BINARY CHECKS THE HEADER** -- not that a
        # token is configured on any particular instance, which is what
        # `auth_required` on /healthz and /v1/capabilities means. A caller
        # provisioning a container has no service to ask, which is why the
        # distinction is published here as well as there. It was `false` while
        # this build had no `auth.py`, which was the honest answer then.
        "auth_enforced": True,
        # **The variable the agent actually reads, measured from the installed
        # bundle** (GP-42). This said `null` first, on the reasoning in GP-03
        # that a plausible name is not a measurement -- and the platform's
        # boot-gate suite refused the null, because AS-29 needs one name a
        # provisioner can set. Both were right; what closed it was measuring.
        "endpoint_source": ENDPOINT_ENV_VAR,
        # The variable an additional certificate authority is delivered
        # under. **Absent and null differ**: an image too old to publish the
        # field has never been measured, `null` means measured and there is
        # none. An object rather than a name, because a name alone cannot be
        # acted on -- a directory where a file is wanted fails exactly as a
        # wrong name does, and whether the default trust store SURVIVES
        # decides whether the container can still reach a public host.
        "ca_bundle_source": CA_BUNDLE_SOURCE,
        "listen": {"address": LISTEN_ADDRESS, "port": LISTEN_PORT},
        # **The numbers a consumer needs before `docker create`.** Docker creates
        # a missing bind-mount point as `root:root 0755` and this service runs as
        # 1000, so the mount is read-write and the agent's first write fails with
        # nothing naming the cause. `Config.User` on the image says `agent`, a
        # name, which is the wrong type for a host filesystem.
        "runs_as": {"uid": RUNS_AS_UID, "gid": RUNS_AS_GID},
    }
