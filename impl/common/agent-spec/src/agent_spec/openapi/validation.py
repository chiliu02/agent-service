"""One 422, shared by every build: a problem document that names the fields.

**This module exists because three artifacts disagreed** (2026-08-19, reported by
the consumer). Two builds returned the framework's `HTTPValidationError`, all
three *declared* it, and all three consumer guides said errors — *including a 422
from validation* — are RFC 7807 problem documents. So the documents contradicted
the guides, and one build contradicted its own document.

Fixing it in one build would have left the other two lying to their own readers,
and fixing the guides would have kept a 422 outside the error vocabulary every
other status obeys. **So all three move together**, which is also what keeps the
shared core intact: AS-31 compares the three documents, and a 422 that changed in
one of them would drop out of the intersection.

Two things, and a build calls both:

    app.add_exception_handler(RequestValidationError, validation_handler)
    declare_validation_problem(app)

**The handler and the declaration must be applied together.** Either alone
recreates the defect this module removes — a build that answers with a shape its
document does not describe, or a document that describes a shape the build does
not answer with.
"""

from __future__ import annotations

from typing import Any

from agent_spec.openapi.schemas import ValidationFailure, ValidationProblem

#: The media type RFC 7807 requires. Set explicitly rather than left to the
#: framework, which would say `application/json` and be technically true and
#: useless to a client dispatching on it.
PROBLEM_MEDIA_TYPE = "application/problem+json"

#: What a 422 is called in the document. One component, referenced by every
#: operation that takes a body.
COMPONENT = "ValidationProblem"


def validation_problem(errors: list[dict[str, Any]]) -> ValidationProblem:
    """Build the payload from the framework's raw error list.

    **`input` is dropped here and nowhere else**, so there is exactly one place
    to look to be sure it cannot be echoed. The framework includes it in every
    entry; a malformed body can carry a caller's MCP bearer token, and an error
    body is the thing most likely to be logged by whatever sits in front of an
    unauthenticated service.

    `url` is dropped too, being a link to the framework's own documentation
    rather than anything about this request.
    """
    return ValidationProblem(
        type="about:blank",
        title="Request validation failed",
        status=422,
        detail=f"{len(errors)} validation error(s)",
        errors=[
            ValidationFailure(
                loc=[part for part in error.get("loc", ())],
                msg=str(error.get("msg", "")),
                type=str(error.get("type", "")),
            )
            for error in errors
        ],
    )


def declare_validation_problem(app: Any) -> None:
    """Point every declared 422 at `ValidationProblem` instead of the framework's.

    **Applied to the app rather than at publication time**, for the reason
    `enforce_canonical_order` gives and which is the same one: the generators
    write what the service serves, so rewriting only on the way out would leave
    the live document and the published file disagreeing, and AS-24's comparison
    would not notice.

    **The framework's `HTTPValidationError` component is left in place** even
    though nothing references it any more. Removing it would be tidier and would
    also remove `ValidationError`, which it composes and which nothing here
    controls; an unreferenced component costs a reader one lookup and costs a
    consumer nothing.
    """
    build = app.openapi

    def openapi() -> dict[str, Any]:
        document = build()
        _rewrite(document)
        app.openapi_schema = document
        return document

    app.openapi = openapi


def _rewrite(document: dict[str, Any]) -> None:
    """Swap the 422 schema reference and its media type, in place."""
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    if COMPONENT not in schemas:
        schemas.update(_component_schemas())

    for operations in document.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            response = operation.get("responses", {}).get("422")
            if not response:
                continue
            response["description"] = "Request validation failed"
            response["content"] = {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": f"#/components/schemas/{COMPONENT}"}
                }
            }


def _component_schemas() -> dict[str, Any]:
    """`ValidationProblem` and `ValidationFailure`, from the models themselves.

    Generated rather than written out, so the description prose lives in one
    place -- the models -- and a change there reaches the document without a
    second edit.
    """
    from pydantic import TypeAdapter

    definitions: dict[str, Any] = {}
    for model in (ValidationProblem, ValidationFailure):
        schema = TypeAdapter(model).json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions.update(schema.pop("$defs", {}))
        definitions[model.__name__] = schema
    return definitions
