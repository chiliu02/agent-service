"""Verify the SDK constructors the Plan 1 tests rely on. No API calls."""

import inspect

from claude_agent_sdk import (
    AssistantMessage,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

for cls in (ProcessError, CLIJSONDecodeError, CLINotFoundError, CLIConnectionError):
    print(f"{cls.__name__:22} {inspect.signature(cls.__init__)}")

print()
print("ProcessError       ->", ProcessError("boom", exit_code=1))
print("CLIJSONDecodeError ->", str(CLIJSONDecodeError("bad", ValueError("x")))[:70])
print("CLINotFoundError   ->", CLINotFoundError("missing"))

print()
print("SystemMessage      ->", SystemMessage(subtype="init", data={"session_id": "s"}))
print("AssistantMessage   ->", AssistantMessage(content=[TextBlock(text="hi")], model="m"))
print("UserMessage        ->", UserMessage(content=[]))
print("ToolUseBlock       ->", ToolUseBlock(id="t1", name="Read", input={}))
print("ToolResultBlock    ->", ToolResultBlock(tool_use_id="t1", content="ok", is_error=None))

r = ResultMessage(
    subtype="success",
    duration_ms=1,
    duration_api_ms=1,
    is_error=False,
    num_turns=1,
    session_id="s",
)
print("ResultMessage      -> terminal_reason=", r.terminal_reason, " result=", r.result)
