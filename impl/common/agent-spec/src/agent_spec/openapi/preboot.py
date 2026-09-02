"""Publishing a build's PRE-BOOT facts in its own OpenAPI document.

**The pre-boot specification was never HTTP, and that was taken to mean it could
not be in the document.** It used to be a command inside the image --
`agent-service-spec`, removed in 0.19.0 -- which answered where no service could.
What was wrong was concluding that the document therefore had nothing to say:
the reader who needs these facts is deciding whether to pull an image at all,
and asking an image to answer that is a runtime dependency in front of a
build-time question.

**The consumer depends on the specification artifact, not on our images.** It
holds the published documents at test scope and resolves them at build time; an
image is loaded at runtime, and several of the decisions these facts inform --
which credential variable to inject, which variable carries a private
certificate authority, which database revision to migrate to -- are made before
any container exists. Requiring a `docker pull` to learn them puts a runtime
dependency in front of a build-time question, and the answer was reachable from
no path the consumer was told to depend on.

**This is the same argument `examples.py` makes one level over**, and the same
remedy: a document that describes only shapes leaves a consumer holding every
implementation's document unable to see how the implementations differ. That
module puts each build's capability payload into its own document. This one puts
each build's pre-boot answer into its own document.

## Why `const` rather than an enum, and why that matters

Each build publishes **its own** values, pinned with `const`. So
`model_api` in `openapi-<version>-gemini-python.json` reads

    "model_api": {"const": "gemini"}

which is a real constraint a validator enforces and a generator emits as a
literal type. Nothing anywhere enumerates across builds, so nothing has to
predict how many builds will exist -- an enum in a shared file would carry the
half we know and imply the half we do not, and would be falsified by a fourth
build that broke no rule.

The **core** falls out of this for free: `core_document` intersects the three
documents, so the shared shape survives into `openapi-<version>-core.json` and the
per-build `const`s drop out of it. The core says the eleven fields exist; each
implementation's document says what they are.

## The rule this creates, and it is the point rather than the cost

**A published document now ASSERTS these values, so moving one requires a new
document version.** Before this, the pre-boot surface could change with no
version moving anywhere, which is exactly why it drifted out of the
specification's reach. Two of the values move on streams of their own and are
therefore NOT pinned:

* `version` and `impl.version` -- the build stream. Several builds bump between
  two documents, and a real version here would break AS-24 the first time one
  did. `examples.py` learned this the same way.
* everything else IS pinned, `schema_revision` included: the Alembic head has
  its own stream, and a build that starts requiring a different one has changed
  what its document promises. That is a version, not an edit.
"""

from __future__ import annotations

from typing import Any

#: Where the shape lands in the document. A component schema rather than a
#: root-level extension: `x-`-prefixed keys are invisible to most generators and
#: carry no descriptions, and this has to be readable by the same toolchain the
#: rest of the document already goes through.
SCHEMA_NAME = "PrebootSpec"

#: Fields whose value moves on the IMPLEMENTATION stream, published open.
#:
#: **Pinning one would break AS-24 on the next build bump**, which is a change
#: that touches no route and moves no document. Dotted, so a nested field can be
#: named without exempting the object around it: `impl.name` stays pinned while
#: `impl.version` does not.
MOVING: frozenset[str] = frozenset({"version", "impl.version"})

_NON_EMPTY_STRING: dict[str, Any] = {"type": "string", "minLength": 1}

#: `(name, schema, description)` per field, in the order `spec.py` builds them.
#: Order is fixed here rather than taken from the payload so a generated document
#: cannot reshuffle between runs and produce a diff that means nothing.
FIELDS: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "version",
        {"type": ["string", "null"], "minLength": 1},
        "This build's own version. Moves on the implementation stream, so it is "
        "NOT pinned here -- read it from the image. Equal to `impl.version`.",
    ),
    (
        "document_version",
        _NON_EMPTY_STRING,
        "The OpenAPI document this image serves -- this document. A `-snapshot` "
        "suffix means it can change under you.",
    ),
    (
        "schema_revision",
        _NON_EMPTY_STRING,
        "The Alembic revision this image requires of its database; a boot gate "
        "refuses any other and the container exits 3. Pinned here because the "
        "database is chosen before the container is created, and starting one to "
        "read the refusal is a late and expensive way to ask.",
    ),
    (
        "impl",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "version"],
            "properties": {
                "name": dict(
                    _NON_EMPTY_STRING,
                    description="The build. Same value as `capabilities.impl.name`, "
                    "and what a per-implementation table keys on.",
                ),
                "version": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "description": "Equal to the top-level `version`, and open "
                    "for the same reason.",
                },
            },
        },
        "The image's own statement of which build it is. The two substitutes are "
        "both worse: an image tag is a string an operator typed and a configured "
        "provider is a field an operator chose, so either can disagree with what "
        "is actually running.",
    ),
    (
        "credential_sources",
        {"type": "array", "items": _NON_EMPTY_STRING, "minItems": 1},
        "Environment variables carrying a model credential for this build. "
        "Validate the variable you inject against this list before starting a "
        "container. Never empty: a build no credential could satisfy could not "
        "take a turn.",
    ),
    (
        "model_api",
        _NON_EMPTY_STRING,
        "The target family this build drives, reached through this build's own "
        "`credential_sources` and `endpoint_source`. A consumer relaying to a "
        "vendor carries one mapping: `claude` is the Anthropic API, `codex` the "
        "OpenAI API, `gemini` the Gemini API. **Not a restatement of "
        "`impl.name`**, which carries the implementation language -- a second "
        "build driving the same target in another language publishes the same "
        "`model_api` and a different `impl.name`.",
    ),
    (
        "provider_selectors",
        {"type": "array", "items": _NON_EMPTY_STRING},
        "Environment variables that move this build onto a cloud provider -- "
        "Bedrock, Vertex, Foundry, GCA. **Never treat one as a credential.** An "
        "operator engaging one has changed something `model_api` does not claim "
        "to cover. Empty is a truthful answer for a build whose agent has no "
        "such switches.",
    ),
    (
        "auth_enforced",
        {"type": "boolean"},
        "Whether this BINARY checks the bearer token at all. Distinct from "
        "`auth_required` on `/healthz` and `/v1/capabilities`, which means *a "
        "token is configured on this running instance* -- and a caller "
        "provisioning a container has no service to ask. An image that took a "
        "token and enforced nothing would report `auth_required: true` while "
        "protecting nothing.",
    ),
    (
        "endpoint_source",
        _NON_EMPTY_STRING,
        "The one environment variable that redirects this image's model traffic. "
        "**Singular, not a list**, because a consumer choosing from a list is a "
        "consumer guessing. Names a VARIABLE, never a URL, and is not derivable "
        "from `credential_sources`.",
    ),
    (
        "ca_bundle_source",
        {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["variable", "shape", "replaces_default_trust"],
            "properties": {
                "variable": dict(
                    _NON_EMPTY_STRING,
                    description="The environment variable an additional "
                    "certificate authority is delivered under. A name, never a "
                    "path: the path is the consumer's to choose.",
                ),
                "shape": {
                    "enum": ["file", "directory"],
                    "description": "Where to put the PEM. **Enumerated because "
                    "the set really is closed** -- there is no third kind of "
                    "filesystem entry -- unlike the per-build values around it, "
                    "which are pinned with `const` instead.",
                },
                "replaces_default_trust": {
                    "type": "boolean",
                    "description": "Whether the default trust store SURVIVES. "
                    "`true` means a container cannot reach a public host and a "
                    "privately-signed one at the same time.",
                },
            },
        },
        "How a private certificate authority reaches this image, for a consumer "
        "behind its own TLS terminator. **An object rather than a name**, "
        "because a name alone cannot be acted on: a directory where a file is "
        "wanted fails exactly as a wrong name does. `null` is a real answer -- "
        "measured, and this build honours the OS trust store only -- and differs "
        "from the field being absent, which means nobody looked. A consumer "
        "guessing one name fleet-wide is wrong on at least one build.",
    ),
    (
        "listen",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["address", "port"],
            "properties": {
                "address": dict(
                    _NON_EMPTY_STRING,
                    description="The in-container bind address. `0.0.0.0` is "
                    "IPv4 only.",
                ),
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "The in-container port to publish.",
                },
            },
        },
        "Where the service listens inside the container, so a port mapping can "
        "be decided before anything is started.",
    ),
    (
        "runs_as",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["uid", "gid"],
            "properties": {
                "uid": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "The numeric user id the service runs as.",
                },
                "gid": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "The numeric group id the service runs as.",
                },
            },
        },
        "**The NUMBERS, because a host directory needs a number.** A consumer that "
        "bind-mounts a directory it composes must chown it before the container "
        "exists, and Docker creates a missing mount point as `root:root 0755` -- "
        "so the mount is read-write and the first thing the agent writes fails, "
        "at a point where nothing names the cause. The image already answers "
        "`Config.User`, and the answer is the wrong type: a NAME, which means "
        "nothing on the host filesystem and resolves to a number only by running "
        "the container, which is strictly too late. **A mode is the consumer's to "
        "choose and an owner is not**, which is why this is published rather than "
        "left to a convention. Requested by Agent Harness (2026-08-19).",
    ),
)


def _pin(schema: dict[str, Any], value: Any, path: str) -> dict[str, Any]:
    """`schema` with this build's answer pinned as `const`, recursively.

    **Objects are pinned field by field rather than whole**, so a nested value on
    a moving stream stays open while its siblings are pinned -- `impl.name` is a
    fact about the build and `impl.version` is not. Pinning the object whole
    would force the choice to be made for all of its fields at once.

    A `null` value pins nothing: the field's own `["object", "null"]` type
    already says null is permitted, and `{"const": None}` would forbid the
    object form for a build that later grows one.
    """
    if path in MOVING:
        return schema
    properties = schema.get("properties")
    if isinstance(properties, dict) and isinstance(value, dict):
        return dict(
            schema,
            properties={
                name: _pin(sub, value[name], f"{path}.{name}" if path else name)
                for name, sub in properties.items()
                if name in value
            },
        )
    if value is None:
        return schema
    return dict(schema, const=value)


def preboot_schema(specification: dict[str, Any]) -> dict[str, Any]:
    """The `PrebootSpec` component for the build that printed `specification`.

    The shape is shared and the values are this build's, which is what makes one
    document answer both *what is published here* and *what does it mean*.
    """
    return {
        "title": SCHEMA_NAME,
        "description": (
            "This build's pre-boot facts. **Not an HTTP surface** -- every field "
            "is needed before a container exists to be asked, which is why it "
            "appears here as a component rather than as a response: the "
            "environment the container is created with, a certificate written "
            "between create and start, and which database it may be pointed at. "
            "Read the image's `com.npf.agent-service.impl` and "
            "`.document-version` labels to find this document; nothing has to be "
            "executed. Values are pinned with `const` where they belong to the "
            "build; `version` and `impl.version` move on the implementation "
            "stream and are left open."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [name for name, _, _ in FIELDS],
        "properties": {
            name: _pin(
                dict(schema, description=description),
                specification.get(name),
                name,
            )
            for name, schema, description in FIELDS
        },
    }


def attach_preboot(app: Any, specification: dict[str, Any]) -> None:
    """Publish this build's pre-boot facts as the `PrebootSpec` component.

    Wraps `app.openapi` and adds the component after FastAPI has finished, for
    the same reason `attach_capabilities_example` does: FastAPI's generation ends
    in an `exclude_none` encode, and a null here is a build being explicit --
    `ca_bundle_source: null` means *measured, and there is none*, which is not
    the same as the field being absent.

    **Applied in the app rather than at publication time.** AS-24 is byte
    equality between the published document and what the container serves, so a
    component the dump script added would make every running service disagree
    with its own published document.
    """
    component = preboot_schema(specification)
    build = app.openapi

    def openapi() -> dict[str, Any]:
        schema = build()
        schema.setdefault("components", {}).setdefault("schemas", {})[
            SCHEMA_NAME
        ] = component
        app.openapi_schema = schema
        return schema

    app.openapi = openapi


def mismatches(document: dict[str, Any], specification: dict[str, Any]) -> list[str]:
    """Where a document's `PrebootSpec` disagrees with what a build prints.

    **The check that makes the document trustworthy rather than merely present.**
    A published value nothing compares against is a value that goes stale
    silently, which is the failure the pre-boot surface had in the first place.
    Used two ways: in each build's own tests against `specification()`, and in
    the conformance suite against the output of a real image.

    Fields on the implementation stream are skipped -- the document leaves them
    open on purpose, so there is nothing to disagree with.
    """
    component = (
        document.get("components", {}).get("schemas", {}).get(SCHEMA_NAME)
    )
    if not isinstance(component, dict):
        return [
            f"the document publishes no {SCHEMA_NAME} component, so a consumer "
            "must pull an image to learn what this build reads"
        ]
    return _compare(component.get("properties", {}), specification, "")


def _compare(
    properties: dict[str, Any], values: dict[str, Any], path: str
) -> list[str]:
    found: list[str] = []
    for name, schema in properties.items():
        here = f"{path}.{name}" if path else name
        if here in MOVING or not isinstance(schema, dict):
            continue
        actual = values.get(name)
        nested = schema.get("properties")
        if isinstance(nested, dict) and isinstance(actual, dict):
            found += _compare(nested, actual, here)
            continue
        if "const" not in schema:
            continue
        if schema["const"] != actual:
            found.append(
                f"{here}: the document says {schema['const']!r} and this build "
                f"prints {actual!r}. A published value moves with a new document "
                "version, never by editing one"
            )
    return found
