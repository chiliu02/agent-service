"""Publishing a build's REAL capability payload in its own document.

**An OpenAPI document describes the shape of `/v1/capabilities` and says nothing
about the values.** So a consumer holding every implementation's document still
cannot see how the implementations differ -- `allow_supplied_sdk_session_id`,
`always_disallowed_tools`, `mcp.transports` and the rest exist only in a running
service's response. Reading three documents tells you the three are identical,
which is true of their schema and false of their behaviour.

This module puts each build's own answer into its own document, as the response
example, so the four published JSON files carry the differences a consumer
compares builds on.

## Why it cannot be done in the route

FastAPI ends `get_openapi()` with

    jsonable_encoder(OpenAPI(**output), by_alias=True, exclude_none=True)

which strips **every null in the whole document**, wherever it came from --
`responses[...]["content"]`, `openapi_extra`, both. Measured: an example
containing `{"field": "effort", "types": null}` is published as
`{"field": "effort"}`.

**That is not cosmetic, because a null is the informative value here.**
`turn_token_overhead: null` is how a build says it has not measured the
overhead, and `usage_counts_tool_calls: null` says the same of its usage
counter. An example that drops them publishes silence where a build was being
explicit, and a consumer diffing the example against a live payload finds fields
missing that the service really does send.

So the example is re-attached AFTER FastAPI has finished, which is the only
point at which it survives.

## What must be true of the payload

**It must be deployment-invariant.** AS-24 requires a running service to serve
exactly its published document, so an example built from live settings would
make every deployment's document differ from the published one the moment an
operator changed a port or a cap. Each build passes capabilities built from its
OWN DEFAULTS, and names the fields that are therefore illustrative.
"""

from __future__ import annotations

from typing import Any

CAPABILITIES_PATH = "/v1/deployment"

#: Fields whose value comes from the DEPLOYMENT rather than from the build, and
#: which a published example therefore shows only as that build's default.
#:
#: **The list is short on purpose.** Everything outside it is a fact about the
#: build, is exactly what a live instance returns, and each build has a test
#: pinning that -- so the example cannot quietly drift into fiction. Widening
#: this set weakens every one of those tests at once.
DEPLOYMENT_DEPENDENT: frozenset[str] = frozenset({
    "workspace_dir", "reference_dirs", "limits", "max_sessions",
    "require_credentials", "require_mounts", "auth_required",
    "allow_mcp_servers", "default_model", "impl",
})


#: What a version that moves on the IMPLEMENTATION stream is published as.
#:
#: Deliberately not version-shaped. `0.0.0` would be copied into a client and
#: believed; this cannot be mistaken for an answer.
VERSION_PLACEHOLDER = "x.y.z"

#: Dotted paths whose value moves on the implementation stream, and which are
#: therefore published as `VERSION_PLACEHOLDER` rather than as the truth.
#:
#: **The document is frozen at a release and these are not.** A build bumps for
#: any reason at all, several times between two documents -- so a real version
#: here means the served document stops matching the published one the first
#: time that happens, which is AS-24 broken by a change that touched no route.
#: Before 2026-08-16 it was survivable only because every version so far has
#: been a `-snapshot`, and a snapshot can be regenerated; the cut is what would
#: have made it permanent.
#:
#: **It is the same mistake as a spec version in an image tag**: a value from a
#: moving stream inside an artifact that cannot be corrected afterwards.
#:
#: `spec.document_version` is deliberately NOT here -- it moves with the
#: document itself, so it is a real value that changes exactly when the file it
#: sits in changes.
MOVING_VERSIONS: frozenset[str] = frozenset({
    "service.impl.version", "service.sdk.version", "service.sdk_version",
})


def placeholdered(payload: dict[str, Any]) -> dict[str, Any]:
    """`payload` with every `MOVING_VERSIONS` path replaced, others untouched.

    A copy: the caller's dict is a live capability payload and must not be
    edited. Only the named leaves change, so `sdk.name` stays the build's real
    answer and remains worth comparing -- the exemption is a leaf, never a whole
    object, which is what stops it widening into "the example is fiction".

    Public because the tests that keep the example honest apply it to the live
    payload rather than re-listing the paths, so the rule cannot be stated twice
    and drift.
    """
    result = dict(payload)
    for path in MOVING_VERSIONS:
        parts = path.split(".")
        cursor = result
        for step in parts[:-1]:
            nested = cursor.get(step)
            if not isinstance(nested, dict):
                cursor = None
                break
            cursor[step] = dict(nested)
            cursor = cursor[step]
        if cursor is not None and parts[-1] in cursor:
            cursor[parts[-1]] = VERSION_PLACEHOLDER
    return result


def flat(payload: dict[str, Any]) -> dict[str, Any]:
    """The grouped payload as one mapping, for checks that do not care where a
    field lives.

    **Not a way back to the flat payload**, and not published: the groups are
    the contract. This exists so a check about a field's VALUE does not have to
    know its group, which would make every such check break when a field moves
    between groups -- exactly the kind of churn the grouping is supposed to end.
    """
    from agent_spec.openapi.schemas import Deployment  # noqa: PLC0415

    merged: dict[str, Any] = {}
    for group in Deployment.GROUPS:
        section = payload.get(group)
        if not isinstance(section, dict):
            continue
        for name, value in section.items():
            # **`limits` lives in two groups now**, so a plain update would drop
            # one of them silently -- the request ceilings or the enforced
            # figures, depending on iteration order. Merging is what makes this
            # helper equivalent to the flat payload it stands in for.
            if isinstance(value, dict) and isinstance(merged.get(name), dict):
                merged[name] = {**merged[name], **value}
            else:
                merged[name] = value
    return merged


def attach_capabilities_example(app: Any, example: dict[str, Any]) -> None:
    """Publish `example` as the 200 example on `GET /v1/capabilities`.

    Wraps `app.openapi` and re-applies the example after FastAPI's own
    null-stripping encode. Composes with any other wrapper -- each one wraps the
    previous, and the result is cached in `app.openapi_schema` exactly as
    FastAPI's own does.

    **Versions that move on the implementation stream are replaced** on the way
    in, so a build bumping does not rewrite its own published document. See
    `MOVING_VERSIONS`.
    """
    example = placeholdered(example)
    build = app.openapi

    def openapi() -> dict[str, Any]:
        schema = build()
        operation = schema.get("paths", {}).get(CAPABILITIES_PATH, {}).get("get")
        if operation is not None:
            content = operation.setdefault("responses", {}).setdefault(
                "200", {}
            ).setdefault("content", {}).setdefault("application/json", {})
            content["example"] = example
        app.openapi_schema = schema
        return schema

    app.openapi = openapi
