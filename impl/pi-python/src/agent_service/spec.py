"""The pre-boot facts, and the source of the document's `PrebootSpec`.

Everything here is published in this build's own OpenAPI document as the
`PrebootSpec` component, with the values pinned by `const`, so a consumer reads
them from an artifact it already resolves at build time instead of by running a
container.

`agent_spec.openapi.preboot` turns this dictionary into that component, and
`api.py` attaches it inside `create_app` -- which it must, because AS-24 is byte
equality between the published document and what a running service serves.

WHAT THE FACTS ARE FOR. Which credential variable this image reads, which
variable moves its traffic, which one delivers a private certificate authority,
which DDL revision it requires, and where it listens. Every one is decided
BEFORE a container exists, which is why none can be answered by `GET
/v1/deployment`.

**Imports nothing but `config` and `versions`.** The constraint costs nothing
and keeps the one place these constants are read free of anything that can fail.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from agent_spec.db.revision_id import EXPECTED_REVISION

from agent_service.config import (
    CA_BUNDLE_SOURCE,
    CREDENTIAL_ENV_VARS,
    ENDPOINT_ENV_VAR,
    GATEWAY_MAP_SOURCE,
    LISTEN_ADDRESS,
    LISTEN_PORT,
    MODEL_API,
    PROVIDER_SELECTOR_ENV_VARS,
    RUNS_AS_GID,
    RUNS_AS_UID,
)
from agent_service.versions import DOCUMENT_VERSION, IMPLEMENTATION_NAME


def specification() -> dict[str, object]:
    """What a caller needs before boot -- credentials, and where to connect."""
    try:
        build_version = version("agent-service-pi-python")
    except PackageNotFoundError:  # pragma: no cover - only outside an install
        build_version = None
    return {
        "version": build_version,
        "document_version": DOCUMENT_VERSION,
        # The OTHER artifact this image is built against. An image depends on
        # two published things -- the OpenAPI document above and the DDL -- and
        # they move on separate streams, so one cannot be read off the other.
        "schema_revision": EXPECTED_REVISION,
        "impl": {"name": IMPLEMENTATION_NAME, "version": build_version},
        "credential_sources": list(CREDENTIAL_ENV_VARS),
        # **`pi`, and it names no vendor** (`PI-06`). The first build here whose
        # family does not map to one API: the vendor is chosen per request.
        "model_api": MODEL_API,
        "provider_selectors": list(PROVIDER_SELECTOR_ENV_VARS),
        # **TRUE, and it means THIS BINARY CHECKS THE HEADER** -- not that a
        # token is configured on any particular instance, which is what
        # `auth_required` on /healthz and /v1/deployment means. A caller
        # provisioning a container has no service to ask, which is why the
        # distinction is published here as well as there.
        "auth_enforced": True,
        # **A proxy, because there is no single base URL to name** (`PI-07`).
        "endpoint_source": ENDPOINT_ENV_VAR,
        # **The other half, and the one a gateway can sit behind** (`PI-56`).
        # The proxy above moves every turn; this is what lets the consumer
        # holding the account credential read the request it is moving.
        "gateway_map_source": GATEWAY_MAP_SOURCE,
        # **Absent and null differ**: an image too old to publish the field has
        # never been measured, `null` means measured and there is none.
        "ca_bundle_source": CA_BUNDLE_SOURCE,
        "listen": {"address": LISTEN_ADDRESS, "port": LISTEN_PORT},
        # **The numbers a consumer needs before `docker create`.** Docker creates
        # a missing bind-mount point as `root:root 0755` and this service runs as
        # 1000, so the mount is read-write and the agent's first write fails with
        # nothing naming the cause. `Config.User` on the image says a name, which
        # is the wrong type for a host filesystem.
        "runs_as": {"uid": RUNS_AS_UID, "gid": RUNS_AS_GID},
    }
