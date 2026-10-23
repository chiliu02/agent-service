"""Second introspection pass. Still no API calls.

Follows up on findings from introspect.py:
  - the PreToolUse deny payload shape (documented nowhere on the reference page)
  - SandboxSettings, which the docs page does not mention at all
  - literal option values we need for /v1/capabilities
  - the full ClaudeSDKClient surface
  - content block types missing from the design's serialization list
"""

from __future__ import annotations

import dataclasses
import inspect
import typing

import claude_agent_sdk as sdk
from claude_agent_sdk import types as t


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def show(obj: typing.Any, name: str) -> None:
    """Print a TypedDict or dataclass shape."""
    print(f"\n-- {name}  ({type(obj).__name__})")
    if obj is None:
        print("   NOT FOUND")
        return
    if dataclasses.is_dataclass(obj):
        try:
            hints = typing.get_type_hints(obj)
        except Exception:
            hints = {}
        for f in dataclasses.fields(obj):
            ann = hints.get(f.name, f.type)
            print(f"   {f.name:<26} {str(ann).replace('typing.', '')}")
        return
    ann = getattr(obj, "__annotations__", None)
    if ann:
        required = getattr(obj, "__required_keys__", frozenset())
        for k, v in ann.items():
            mark = "required" if k in required else "optional"
            print(f"   {k:<26} {str(v).replace('typing.', ''):<50} [{mark}]")
        return
    if hasattr(obj, "__args__"):
        print(f"   union/literal args: {obj.__args__}")
        return
    print(f"   {obj!r}")


rule("HOOK OUTPUT SHAPES  (how a hook allows / denies)")
for n in (
    "SyncHookJSONOutput",
    "AsyncHookJSONOutput",
    "HookSpecificOutput",
    "PreToolUseHookSpecificOutput",
    "PostToolUseHookSpecificOutput",
    "PermissionRequestHookSpecificOutput",
    "UserPromptSubmitHookSpecificOutput",
):
    show(getattr(t, n, None), n)

rule("HOOK INPUT SHAPES")
for n in ("BaseHookInput", "PreToolUseHookInput", "PostToolUseHookInput"):
    show(getattr(t, n, None), n)

rule("HOOK EVENTS ACCEPTED BY ClaudeAgentOptions.hooks")
hints = typing.get_type_hints(sdk.ClaudeAgentOptions)
hooks_t = hints.get("hooks")
print(f"  {hooks_t}")
try:
    key_t = typing.get_args(typing.get_args(typing.get_args(hooks_t)[0])[0])
    print(f"\n  events: {sorted(x for a in key_t for x in typing.get_args(a))}")
except Exception as e:  # noqa: BLE001
    print(f"  (could not unwrap: {e})")

rule("SANDBOX  (present in the SDK, absent from the docs page)")
for n in ("SandboxSettings", "SandboxNetworkConfig", "SandboxIgnoreViolations"):
    show(getattr(t, n, None), n)

rule("LITERAL OPTION VALUES  (for /v1/capabilities)")
for n in (
    "PermissionMode",
    "SettingSource",
    "EffortLevel",
    "ToolsPreset",
    "SdkBeta",
    "SessionStoreFlushMode",
    "ServerToolName",
):
    obj = getattr(t, n, None)
    args = typing.get_args(obj) if obj is not None else ()
    print(f"  {n:<24} {list(args) if args else obj}")

rule("SYSTEM PROMPT SHAPES")
for n in ("SystemPromptPreset", "SystemPromptFile"):
    show(getattr(t, n, None), n)

rule("THINKING CONFIG SHAPES")
for n in ("ThinkingConfigAdaptive", "ThinkingConfigEnabled", "ThinkingConfigDisabled", "TaskBudget"):
    show(getattr(t, n, None), n)

rule("CONTENT BLOCK UNION  (what serialization must handle)")
cb = getattr(t, "ContentBlock", None)
print(f"  ContentBlock = {cb}")
for n in ("ServerToolUseBlock", "ServerToolResultBlock"):
    show(getattr(t, n, None), n)

rule("MESSAGE UNION  (what the run loop must handle)")
msg = getattr(t, "Message", None)
print(f"  Message = {msg}")
for n in ("RateLimitEvent", "RateLimitInfo", "ModelUsage", "MirrorErrorMessage"):
    show(getattr(t, n, None), n)

rule("ClaudeSDKClient FULL SURFACE")
for name, fn in inspect.getmembers(sdk.ClaudeSDKClient, inspect.isfunction):
    if name.startswith("_") and name != "__init__":
        continue
    try:
        print(f"  {name}{inspect.signature(fn)}")
    except (ValueError, TypeError):
        print(f"  {name}(?)")

rule("MCP SERVER CONFIG SHAPES")
for n in ("McpSdkServerConfig", "McpStdioServerConfig", "McpHttpServerConfig", "McpSSEServerConfig"):
    show(getattr(t, n, None), n)

rule("create_sdk_mcp_server / tool SIGNATURES")
print(f"  create_sdk_mcp_server{inspect.signature(sdk.create_sdk_mcp_server)}")
print(f"  tool{inspect.signature(sdk.tool)}")
