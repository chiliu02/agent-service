"""The CORE document: what every implementation's OpenAPI document must share.

**Plan 8 step 6, and it exists because a measurement inverted the expectation.**
The core boundary was argued about for weeks as though implementations would
differ widely. Measured 2026-08-08 between `claude-python` and `codex-python`:
every path, method, `operationId`, parameter, request body, component schema and
response schema was **identical**, and every differing leaf in the two documents
was **prose**. The core is not a small agreed subset; it is almost the whole
document, and this module computes it.

## What is in the core, and what is not

| | |
|---|---|
| **Core** — identical in every implementation | operations, `operationId`s, parameters, request bodies, component schemas, and the response schema for every status the core declares |
| **Per-build** — free to differ | `summary`, `description`, `title`, `example(s)`; and **additional** status codes and response headers |

**Prose is the only free difference, and the boundary is not about size.** It is
whether a correct client can ignore it: a client executes no `description`, and a
status code that can arrive is a branch. That is why an added status code is
permitted by AS-31 but must be published on `/v1/capabilities` under AS-32 --
discoverable at runtime, not by diffing two documents.

## Derived, never authored

The core is computed from the implementations' own published documents, so it
cannot claim something no build serves. That direction has one hazard, and it is
worth stating where the code lives:

**Intersection is monotonic, so a weak implementation ERODES the core.** The day a
third build lands without `PATCH /v1/sessions/{sid}`, that route leaves the core
and every existing build stays "conforming". So a core that SHRINKS is a breaking
change under AS-23: it needs a version, a stated reason, and a notice.
`shrinkage()` is what lets the CI say so rather than regenerate quietly.
"""

from __future__ import annotations

from typing import Any

from agent_spec.openapi.ordering import canonical

#: Keys whose values are prose: a client executes none of them, so two
#: implementations may legitimately disagree here and the core omits them.
#:
#: **`title` is included and that needs saying**, because it is also the name of
#: a schema in `components`. It is omitted as a VALUE, never as a key path -- a
#: schema still appears in the core under its own name; only its human-facing
#: `title` string is dropped.
PROSE_KEYS = frozenset({"summary", "description", "title", "example", "examples"})


class _Missing:
    """A leaf the implementations do not agree on. Never appears in output."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


MISSING = _Missing()


def strip_prose(node: Any) -> Any:
    """The document with every prose value removed, recursively."""
    if isinstance(node, dict):
        return {k: strip_prose(v) for k, v in node.items() if k not in PROSE_KEYS}
    if isinstance(node, list):
        return [strip_prose(v) for v in node]
    return node


def _intersect(a: Any, b: Any) -> Any:
    """The part of two already-prose-stripped nodes that agrees."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: dict[str, Any] = {}
        for key, value in a.items():
            if key not in b:
                continue
            merged = _intersect(value, b[key])
            if merged is not MISSING:
                out[key] = merged
        return out
    if isinstance(a, list) and isinstance(b, list):
        # **A list is all-or-nothing.** Two lists of different length are not
        # partially the same thing: `required: [a, b]` and `required: [a]` are
        # different contracts, and silently intersecting them would publish a
        # core asserting a weaker requirement than either build enforces.
        if len(a) != len(b):
            return MISSING
        merged_items = [_intersect(x, y) for x, y in zip(a, b)]
        return MISSING if any(item is MISSING for item in merged_items) else merged_items
    return a if a == b else MISSING


def core_document(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """The structural core of one or more implementations' documents.

    With a single document this is just `strip_prose` -- which is the honest
    answer while one implementation exists, and is why the core is worth
    generating before the second one lands rather than after.
    """
    if not documents:
        raise ValueError("the core needs at least one implementation document")
    stripped = [strip_prose(doc) for doc in documents]
    core = stripped[0]
    for other in stripped[1:]:
        core = _intersect(core, other)
    # **Ordered explicitly, because `_intersect` iterates the FIRST document.**
    # Without this the core's own path order is decided by which build happens
    # to be passed first -- it matched claude-python only because that is the
    # order the caller built its list in. The core is what the implementations
    # are compared against, so it must not inherit an accident from one of them.
    return canonical(core)


def leaves(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every scalar in a document, as `(dotted.path, value)`."""
    if isinstance(node, dict):
        out: list[tuple[str, Any]] = []
        for key, value in node.items():
            out.extend(leaves(value, f"{path}.{key}"))
        return out
    if isinstance(node, list):
        out = []
        for index, value in enumerate(node):
            out.extend(leaves(value, f"{path}[{index}]"))
        return out
    return [(path, node)]


def conformance_failures(document: dict[str, Any], core: dict[str, Any]) -> list[str]:
    """Where `document` fails to contain `core` (AS-31). Empty means conforming.

    **One-directional on purpose.** An implementation may ADD -- a status code,
    a response header -- and AS-31 permits it; what it may not do is lack or
    contradict anything the core states. So this reports only core leaves that
    are absent or different, and says nothing about extras.

    Prose is stripped from `document` before comparing, because the core has none
    and a description is not something a build can fail to match.
    """
    stripped = dict(leaves(strip_prose(document)))
    failures: list[str] = []
    for path, expected in leaves(core):
        if path not in stripped:
            failures.append(f"missing {path} (core says {expected!r})")
        elif stripped[path] != expected:
            failures.append(f"{path} is {stripped[path]!r}, core says {expected!r}")
    return failures


def shrinkage(previous_core: dict[str, Any], new_core: dict[str, Any]) -> list[str]:
    """Core leaves that the new core has lost. **Non-empty is a breaking change.**

    See the module docstring: the core is derived, derivation is monotonic, and a
    build that cannot do something removes it for everyone. This is the check
    that makes such a removal a decision rather than a regeneration.
    """
    new_leaves = dict(leaves(new_core))
    return [
        path
        for path, _value in leaves(previous_core)
        if path not in new_leaves
    ]
