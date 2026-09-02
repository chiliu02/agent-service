"""Static introspection of claude_agent_sdk. Makes no API calls.

Answers the spec's "confirm during implementation" items:
  N1  exact ResultMessage field set (cost / usage / duration / turns)
  Q9  ClaudeAgentOptions fields we rely on (add_dirs, env, setting_sources)
  C   hook callback / deny payload shape, and the can_use_tool alternative
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
import typing


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def show_dataclass(obj: type) -> None:
    if not dataclasses.is_dataclass(obj):
        print(f"  (not a dataclass: {obj!r})")
        return
    try:
        hints = typing.get_type_hints(obj)
    except Exception:  # forward refs that don't resolve
        hints = {}
    for f in dataclasses.fields(obj):
        ann = hints.get(f.name, f.type)
        ann_s = getattr(ann, "__name__", None) or str(ann).replace("typing.", "")
        if f.default is not dataclasses.MISSING:
            default = f" = {f.default!r}"
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            default = " = <factory>"
        else:
            default = "  (required)"
        print(f"  {f.name:<28} {ann_s:<44}{default}")


def main() -> None:
    import claude_agent_sdk as sdk

    rule("PACKAGE")
    print(f"  version : {getattr(sdk, '__version__', '<none>')}")
    print(f"  file    : {sdk.__file__}")
    print(f"  python  : {sys.version.split()[0]}")

    rule("__all__")
    names = sorted(getattr(sdk, "__all__", dir(sdk)))
    for i in range(0, len(names), 3):
        print("  " + "".join(n.ljust(34) for n in names[i : i + 3]))

    # --- N1: the message types --------------------------------------------
    for name in (
        "ResultMessage",
        "SystemMessage",
        "AssistantMessage",
        "UserMessage",
        "StreamEvent",
    ):
        obj = getattr(sdk, name, None)
        if obj is None:
            print(f"\n-- {name}: NOT EXPORTED")
            continue
        rule(f"MESSAGE TYPE: {name}")
        show_dataclass(obj)

    rule("CONTENT BLOCK TYPES")
    for name in (
        "TextBlock",
        "ThinkingBlock",
        "ToolUseBlock",
        "ToolResultBlock",
    ):
        obj = getattr(sdk, name, None)
        print(f"\n-- {name}{'' if obj else '  (NOT EXPORTED)'}")
        if obj:
            show_dataclass(obj)

    # --- ClaudeAgentOptions ------------------------------------------------
    rule("ClaudeAgentOptions")
    show_dataclass(sdk.ClaudeAgentOptions)

    rule("OPTIONS FIELDS THE DESIGN DEPENDS ON")
    present = {f.name for f in dataclasses.fields(sdk.ClaudeAgentOptions)}
    for f in (
        "cwd",
        "add_dirs",
        "env",
        "setting_sources",
        "system_prompt",
        "allowed_tools",
        "disallowed_tools",
        "permission_mode",
        "can_use_tool",
        "hooks",
        "max_turns",
        "max_budget_usd",
        "include_partial_messages",
        "resume",
        "fork_session",
        "effort",
        "thinking",
        "mcp_servers",
        "agents",
    ):
        print(f"  {'OK  ' if f in present else 'MISS'}  {f}")

    # --- hooks & permissions ----------------------------------------------
    rule("HOOKS")
    hm = getattr(sdk, "HookMatcher", None)
    print(f"-- HookMatcher: {hm}")
    if hm:
        show_dataclass(hm)

    for tname in ("HookEvent", "HookCallback", "HookJSONOutput", "HookContext"):
        t = getattr(sdk, tname, None)
        print(f"\n-- {tname}: {t if t is not None else 'NOT EXPORTED'}")
        if t is not None and hasattr(t, "__args__"):
            print(f"     args: {t.__args__}")
        if t is not None and hasattr(t, "__annotations__"):
            for k, v in getattr(t, "__annotations__", {}).items():
                print(f"     {k}: {v}")

    rule("PERMISSIONS (can_use_tool)")
    for tname in (
        "PermissionResultAllow",
        "PermissionResultDeny",
        "ToolPermissionContext",
        "CanUseTool",
        "PermissionMode",
    ):
        t = getattr(sdk, tname, None)
        print(f"\n-- {tname}: {t if t is not None else 'NOT EXPORTED'}")
        if t is not None and dataclasses.is_dataclass(t):
            show_dataclass(t)
        elif t is not None and hasattr(t, "__args__"):
            print(f"     args: {t.__args__}")

    # --- where the deny shape actually lives -------------------------------
    rule("HOOK OUTPUT TYPES (searching submodules for deny/permissionDecision)")
    import pkgutil

    hits: list[str] = []
    for mod in pkgutil.walk_packages(sdk.__path__, prefix="claude_agent_sdk."):
        try:
            m = __import__(mod.name, fromlist=["_"])
        except Exception:
            continue
        for attr in dir(m):
            low = attr.lower()
            if "hook" in low and ("output" in low or "decision" in low or "json" in low):
                hits.append(f"{mod.name}.{attr}")
    for h in sorted(set(hits)):
        print(f"  {h}")
    if not hits:
        print("  (none found by name — inspect types module manually)")

    # --- query / client signatures ----------------------------------------
    rule("ENTRY POINT SIGNATURES")
    print(f"  query{inspect.signature(sdk.query)}")
    for meth in ("connect", "query", "receive_response", "interrupt", "disconnect"):
        fn = getattr(sdk.ClaudeSDKClient, meth, None)
        if fn:
            print(f"  ClaudeSDKClient.{meth}{inspect.signature(fn)}")

    rule("ERRORS")
    for name in (
        "ClaudeSDKError",
        "CLINotFoundError",
        "CLIConnectionError",
        "ProcessError",
        "CLIJSONDecodeError",
    ):
        print(f"  {'OK  ' if getattr(sdk, name, None) else 'MISS'}  {name}")

    # --- bundled binary ----------------------------------------------------
    rule("BUNDLED CLI BINARY")
    import pathlib

    root = pathlib.Path(sdk.__file__).parent
    found = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and (p.suffix in {".exe", ""} or "claude" in p.name.lower())
        and p.stat().st_size > 1_000_000
    ]
    for p in sorted(found)[:20]:
        print(f"  {p.relative_to(root)}  ({p.stat().st_size / 1e6:.1f} MB)")
    if not found:
        print("  (no large binary under the package — may resolve via PATH or node_modules)")


if __name__ == "__main__":
    main()
