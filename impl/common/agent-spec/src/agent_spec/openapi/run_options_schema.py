"""`GET /v1/schemas/run-options`: `accepts`, rendered as JSON Schema.

**One fact in two shapes.** `deployment.accepts` is branchable -- a client reads
`unsupported_options` and decides -- and this is the same narrowing expressed as
something a validator can run. Neither is derived from the other at runtime by a
consumer: the service publishes both, and a conformance clause asserts they
agree, so a client picks whichever shape suits it.

**Why the service does this rather than the client.** The narrowing is a
DEPLOYMENT-time fact: two containers of one image answer differently, so it
cannot sit in a frozen document, and no standard says a deployment narrows a
published contract at runtime. What a client would otherwise write is this
module, once per client, from prose.

**Every rule here is mechanical and comes from the published payload.** A
property needing a hand-written branch is a property that cannot be published
as a schema, and belongs in the guide as prose instead.
"""

from __future__ import annotations

import copy
from typing import Any

DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: `accepts` key -> (`RunOptions` property, how it narrows).
VOCABULARIES: tuple[tuple[str, str, str], ...] = (
    ("permission_modes", "permission_mode", "labelled"),
    ("effort_levels", "effort", "enum"),
    ("setting_sources", "setting_sources", "items"),
    ("strict_mcp_config", "strict_mcp_config", "default"),
)

#: `accepts.limits` key stem -> the property it bounds, once the prefix is off.
LIMIT_TARGETS: dict[str, str] = {
    "turns": "max_turns",
    "max_turns": "max_turns",
    "budget_usd": "max_budget_usd",
    "max_budget_usd": "max_budget_usd",
    "timeout_s": "timeout_s",
    "request_timeout_s": "timeout_s",
}


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    return "array"


def _branches(schema: dict) -> list[dict]:
    return schema["anyOf"] if "anyOf" in schema else [schema]


def _drop_null(schema: dict) -> dict:
    """Collapse `anyOf: [X, {type: null}]` to X.

    Not cosmetic: nothing is required and the service reads `exclude_unset`, so
    an explicit null means the same as omitted -- while a renderer meeting the
    two-arm union draws a one-of picker for a field that has one shape.
    """
    if "anyOf" not in schema:
        return schema
    kept = [b for b in schema["anyOf"] if b.get("type") != "null"]
    if len(kept) != 1:
        return {**schema, "anyOf": kept}
    merged = {k: v for k, v in schema.items() if k != "anyOf"}
    merged.update(kept[0])
    return merged


def _refuse(props: dict, entry: dict, forbidden: list[str]) -> None:
    """Apply one `unsupported_options` entry.

    **A whole-field refusal is TWO edits.** Removing the property is not enough:
    unknown properties are rejected, so a bare removal makes a published refusal
    indistinguishable from a typo -- the schema must also forbid the name, which
    is what tells a form generator *this build refuses `max_turns`* rather than
    *unknown key*.
    """
    field = entry["field"]
    if field not in props:
        return
    types, values = entry.get("types"), entry.get("values")
    if not types and not values:
        del props[field]
        forbidden.append(field)
        return
    if types:
        kept = [b for b in _branches(props[field]) if b.get("type") not in types]
        if kept:
            props[field] = (_drop_null({**props[field], "anyOf": kept}) if len(kept) > 1
                            else _drop_null({**{k: v for k, v in props[field].items()
                                                if k != "anyOf"}, **kept[0]}))
        return
    survivors = [v for v in (True, False) if v not in values] if any(
        b.get("type") == "boolean" for b in _branches(props[field])) else []
    if len(survivors) == 1:
        props[field] = {**_drop_null(props[field]), "const": survivors[0]}
    else:
        props[field] = {**_drop_null(props[field]), "not": {"enum": list(values)}}


def _mcp(props: dict, accepts: dict, defs: dict) -> None:
    """Narrow `mcp_servers` by the name pattern and the transports.

    A per-SERVER refusal is not a field refusal, and this is where the
    difference stops being prose: the property survives, and its keys and its
    union are narrowed instead.
    """
    prop = props.get("mcp_servers")
    if prop is None:
        return
    prop = _drop_null(copy.deepcopy(prop))
    mcp = accepts.get("mcp") or {}
    if mcp.get("server_name_pattern"):
        prop["propertyNames"] = {"pattern": mcp["server_name_pattern"]}
    transports = mcp.get("transports")
    union = prop.get("additionalProperties")
    if transports and isinstance(union, dict):
        # **The union is an `anyOf` of `$ref`s, not one `$ref`.** Handling only
        # the single-ref shape makes this a no-op that looks like a rule -- a
        # build publishing two transports kept a schema accepting three.
        arms = union["anyOf"] if "anyOf" in union else [union]
        kept = []
        for arm in arms:
            target = defs.get(arm.get("$ref", "").rsplit("/", 1)[-1], {})
            const = ((target.get("properties") or {}).get("type") or {}).get("const")
            if const is None or const in transports:
                kept.append(arm)
        if kept and len(kept) != len(arms):
            prop["additionalProperties"] = kept[0] if len(kept) == 1 else {"anyOf": kept}
    props["mcp_servers"] = prop


def effective_run_options_schema(
    run_options_schema: dict[str, Any],
    accepts: dict[str, Any],
    *,
    impl: str,
) -> dict[str, Any]:
    """`RunOptions` narrowed by one deployment's `accepts` group.

    `run_options_schema` is `RunOptions.model_json_schema()`; `accepts` is the
    group as published. Both come from the same process, so this cannot describe
    a deployment other than the one answering.
    """
    schema = copy.deepcopy(run_options_schema)
    props: dict = schema.get("properties", {})
    defs: dict = schema.get("$defs", {})
    forbidden: list[str] = []

    for entry in accepts.get("unsupported_options") or []:
        _refuse(props, entry, forbidden)

    for key, field, kind in VOCABULARIES:
        value = accepts.get(key)
        if field not in props:
            continue
        if value == []:
            del props[field]
            forbidden.append(field)
            continue
        if not value:
            continue
        prop = _drop_null(copy.deepcopy(props[field]))
        if kind == "default":
            prop["default"] = value
        elif kind == "labelled":
            prop = {k: v for k, v in prop.items() if k not in ("type", "enum")}
            prop["oneOf"] = [
                {"const": m["id"], "title": m.get("name", m["id"]),
                 **({"description": m["description"]} if m.get("description") else {})}
                for m in value
            ]
        elif kind == "enum":
            prop["enum"] = list(value)
        elif kind == "items":
            prop["items"] = {**_drop_null(prop.get("items", {})), "enum": list(value)}
        props[field] = prop

    tools = accepts.get("default_allowed_tools") or []
    if tools:
        vocabulary = sorted(set(tools) | set(accepts.get("always_disallowed_tools") or []))
        for field in ("allowed_tools", "disallowed_tools"):
            if field in props:
                prop = _drop_null(copy.deepcopy(props[field]))
                # **`examples`, never `enum`.** An unpublished tool name is
                # accepted and dropped rather than refused, so an enum here would
                # promise a 400 that never happens. The names are suggestions.
                prop["items"] = {**_drop_null(prop.get("items", {})),
                                 "examples": vocabulary}
                props[field] = prop
        if "allowed_tools" in props:
            props["allowed_tools"]["default"] = list(tools)

    for name, value in (accepts.get("limits") or {}).items():
        for prefix, keyword in (("max_allowed_", "maximum"), ("default_", "default")):
            if name.startswith(prefix):
                target = LIMIT_TARGETS.get(name[len(prefix):])
                if target and target in props:
                    props[target] = {**_drop_null(props[target]), keyword: value}

    if accepts.get("allow_mcp_servers") is False and "mcp_servers" in props:
        del props["mcp_servers"]
        forbidden.append("mcp_servers")
    _mcp(props, accepts, defs)

    narrowed = {
        "$schema": DIALECT,
        "$id": f"urn:agent-service:{impl}:run-options",
        "title": "RunOptions",
        "description": (
            "The effective RunOptions for THIS deployment: the published model "
            "narrowed by this instance's /v1/deployment `accepts` group. An "
            "instance this schema accepts is a request this service accepts."
        ),
        "type": "object",
        "properties": props,
        # An unknown property is a 422 naming the key, so the schema says so.
        "additionalProperties": False,
    }
    if forbidden:
        # One clause per name: `not: {required: [a, b]}` would forbid only the
        # instance carrying BOTH, and accept either alone. Silent if wrong.
        narrowed["allOf"] = [{"not": {"required": [name]}}
                             for name in sorted(set(forbidden))]
    if defs:
        narrowed["$defs"] = defs
    return narrowed
