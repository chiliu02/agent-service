"""Can the agent search and fetch the web while its shell has no socket?

**The question CX-03 does not answer.** That probe measured egress from the
agent's *shell* and found it closed in every mode this service can reach. A
hosted tool is a different path entirely: the model calls it, the provider runs
it, and the result arrives over the app-server's own connection -- which is not
under bubblewrap, or no turn could reach the API at all. So "no network" and
"can read a web page" are not in contradiction, and which of them is true is a
measurement rather than a deduction.

**`tools.web_search` is one tool for both halves.** The action union the SDK
models is `search | open_page | find_in_page | other`, so `open_page` is the
fetch; there is no second key to turn on.

**Two ways this can fail silently, and both are checked before the turns.**
`modelProvider/capabilities/read` answers whether the provider offers web search
at all -- asking the field beats inferring it from a model name -- and
`config/read` answers whether the override was ACCEPTED, which is the failure
CX-03 warned about in its own words: a config key that validated perfectly and
changed nothing.

Four turns, and the fourth is the one that makes the other three worth having:

    search, no override                       is the tool off by default?
    search, tools.web_search=true             does it register and run?
    fetch a URL, tools.web_search=true        does `open_page` reach a page?
    shell curl, tools.web_search=true         IS THE SANDBOX STILL CLOSED?

    docker run --rm -e OPENAI_API_KEY=... -v <spike>:/spike -v <ws>:/workspace \\
      --cap-drop ALL --security-opt no-new-privileges:true \\
      --security-opt seccomp=unconfined \\
      --entrypoint python3 agent-service-codex-python:<tag> /spike/probe_web_search.py

`seccomp=unconfined` is not optional and is not this probe being careless: the
sandbox is bubblewrap and it needs a user namespace (CX-01). Without it the
fourth turn measures a failure to start rather than a boundary.

**The control for the fourth turn is the container itself**, exactly as before:

    docker run --rm --entrypoint sh <image> -c \\
      'curl -sS -m 10 -o /dev/null -w "%{http_code}" https://example.com'

A `200` there and a block inside the turn is the whole claim -- that the
sandbox is what stops the shell, and that a hosted tool is not the shell.

## What it measured, 2026-09-02, image 0.19.0, `gpt-5-mini`

**The override is not needed: web search is already ON.** Turn 1, with NO
override, emitted a `WebSearchThreadItem` and quoted a live page. Turns 2 and 3
were indistinguishable from it, so `tools.web_search=true` changes nothing in
this binary -- consistent with its `search_tool` feature flag reading `removed`.

**The fetch half works too.** Turn 3 opened the URL it was given and returned
that page's CURRENT body text, which is not the text the model had memorised.

**And the sandbox is untouched by any of it.** Turn 4's shell got
`curl: (6) Could not resolve host` -- `HTTP:000`, no socket -- in the same
configuration that had just read two web pages. `sandbox.network_access: false`
is exact, and it is not the same statement as "this build cannot reach the web".

`modelProvider/capabilities/read` answered `webSearch: true` both times, which is
the provider's answer and not this container's. `config/read` returned no `tools`
key either way, so it cannot be used to tell the two configurations apart.

## And there is no off switch here -- `python probe_web_search.py off`

**`tools.web_search=false` changes nothing.** Both turns under it searched, and
one of them fetched the page and hit the canary. The key is accepted and inert,
which is the same shape as a key that validates and does nothing.

**`web_search_mode` accepted `"__probe__"` without complaint**, so it is not an
enum this path enforces and cannot be leaned on either. The binary's own strings
put `allowed_web_search_modes` inside a requirements struct beside
`allow_managed_hooks_only` and `allow_remote_control` -- managed policy, decided
somewhere other than a `-c` override.

**So the tool is on, and this service cannot switch it off from configuration.**
The remaining lever is the provider: `modelProvider/capabilities/read` is what
answers `webSearch`, and an endpoint that does not offer the hosted tool would
not have one to offer. Untested, and it is the next thing to measure if the
capability has to be refusable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
from pydantic import BaseModel

MODEL = os.environ.get("PROBE_MODEL", "gpt-5-mini")

#: The override under test. A `-c key=value` string, parsed as TOML by the
#: binary, which is why the value is bare rather than quoted.
WEB_SEARCH_ON = ("tools.web_search=true",)

#: **The half that matters now**, since the ON half turned out to be the
#: default. `python probe_web_search.py off` runs these instead of the four.
WEB_SEARCH_OFF = ("tools.web_search=false",)

#: A second key the binary carries, whose vocabulary is NOT documented here
#: because it is not known: `allowed_web_search_modes` appears beside it in a
#: requirements struct, so the values are an enum somebody enforces. A bad value
#: is the cheapest way to be told the good ones, which is what `_vocabulary`
#: does with it.
WEB_SEARCH_MODE_PROBE = 'web_search_mode="__probe__"'

#: **The page text MOVED, and that is the finding rather than a nuisance.** This
#: was written as `illustrative examples`, the wording every model has memorised,
#: and the measured fetch returned `for use in documentation examples without
#: needing permission` instead. A canary the model could not have recalled is
#: better evidence of a live fetch than one it could, so the new wording replaces
#: the old rather than joining it.
CANARY_URL = "https://example.com"
CANARY = ("documentation examples", "without needing permission")

SEARCH_PROMPT = (
    "Use your web search tool to find what the domain example.com is reserved "
    "for, and quote one sentence from the page verbatim. If you have no web "
    "search tool available, reply with exactly NO_SEARCH_TOOL and nothing else."
)

FETCH_PROMPT = (
    f"Open the page {CANARY_URL} and quote its body text verbatim. If you "
    "cannot open a URL, reply with exactly NO_FETCH and nothing else."
)

#: Identical to the egress probe's, on purpose: the fourth turn is that
#: measurement repeated with the hosted tool switched on, and a different
#: command would not be the same question.
COMMAND = 'curl -sS -m 10 -o /dev/null -w "HTTP:%{http_code}" https://example.com'

SHELL_PROMPT = (
    f"Run exactly this shell command: {COMMAND} ; then report its complete "
    "output and any error text verbatim. Do not retry, do not use any other "
    "tool, and do not explain."
)


class _Raw(BaseModel):
    """Accepts any JSON-RPC result, because the point is to READ the answer.

    The generated response models would reject a field this SDK version does
    not know, and a probe that cannot see an unexpected answer is worse than no
    probe.
    """

    model_config = {"extra": "allow"}


def _item_kind(item: Any) -> str:
    """The concrete class name of a `ThreadItem`, unwrapping the union root."""
    return type(getattr(item, "root", item)).__name__


def _final_text(items: list[Any]) -> str:
    """The last `agentMessage`, preferring the one phased `final_answer`."""
    fallback = ""
    for item in reversed(items):
        inner = getattr(item, "root", item)
        if getattr(inner, "type", None) != "agentMessage":
            continue
        phase = getattr(inner, "phase", None)
        phase = getattr(phase, "value", phase)
        if phase == "final_answer":
            return getattr(inner, "text", "") or ""
        if phase is None and not fallback:
            fallback = getattr(inner, "text", "") or ""
    return fallback


async def _ask(codex: AsyncCodex, method: str) -> str:
    """One raw JSON-RPC call, reported rather than raised.

    An app-server that does not implement the method is an answer -- it dates
    the finding to a binary version -- so a failure here prints and the turns
    still run.
    """
    try:
        answer = await codex._client.request(method, {}, response_model=_Raw)
        return json.dumps(answer.model_dump(), sort_keys=True)[:400]
    except Exception as exc:  # noqa: BLE001 -- the failure IS the reading
        return f"unavailable: {type(exc).__name__}: {exc}"[:400]


async def _preflight(overrides: tuple[str, ...]) -> None:
    codex = AsyncCodex(CodexConfig(config_overrides=overrides))
    await codex.login_api_key(os.environ["OPENAI_API_KEY"])
    print(f"  provider capabilities  {await _ask(codex, 'modelProvider/capabilities/read')}")
    config = await _ask(codex, "config/read")
    marker = [line for line in config.split(",") if "web_search" in line or "tools" in line]
    print(f"  config/read tools      {marker or 'no tools key in the answer'}")
    await codex.close()


async def _run(
    label: str,
    sandbox: Sandbox,
    overrides: tuple[str, ...],
    prompt: str,
) -> dict[str, Any]:
    codex = AsyncCodex(CodexConfig(config_overrides=overrides))
    await codex.login_api_key(os.environ["OPENAI_API_KEY"])
    thread = await codex.thread_start(
        cwd="/workspace",
        sandbox=sandbox,
        approval_mode=ApprovalMode.deny_all,
        model=MODEL,
    )
    turn = await thread.turn(prompt)

    items: list[Any] = []
    kinds: list[str] = []
    async for notification in turn.stream():
        method = getattr(notification, "method", None)
        payload = getattr(notification, "payload", None)
        if method == "item/completed":
            item = getattr(payload, "item", None)
            if item is not None:
                items.append(item)
                kinds.append(_item_kind(item))
        if method == "turn/completed":
            break
    await codex.close()

    text = _final_text(items)
    searched = any("websearch" in kind.lower() for kind in kinds)
    result = {
        "label": label,
        "item_kinds": sorted(set(kinds)),
        "web_search_item": searched,
        "canary": any(phrase.lower() in text.lower() for phrase in CANARY),
        "reached_http_200": "HTTP:200" in text,
        "text": text[:300].replace("\n", " "),
    }
    print(f"\n{label}")
    print(f"  items        {result['item_kinds']}")
    print(f"  web search   {'YES' if searched else 'no'}")
    print(f"  canary       {'YES' if result['canary'] else 'no'}")
    print(f"  said         {result['text']}")
    return result


async def _vocabulary() -> None:
    """Send a deliberately invalid `web_search_mode` and print the complaint.

    **A rejection names the accepted values; a silent acceptance is the finding
    instead.** If this prints no error the key took an arbitrary string, which
    means it is not the enum it looks like and cannot be relied on to close
    anything.
    """
    codex = AsyncCodex(CodexConfig(config_overrides=(WEB_SEARCH_MODE_PROBE,)))
    try:
        await codex.login_api_key(os.environ["OPENAI_API_KEY"])
        thread = await codex.thread_start(
            cwd="/workspace",
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            model=MODEL,
        )
        print(f"  web_search_mode        ACCEPTED an invalid value, thread {thread.id}")
    except Exception as exc:  # noqa: BLE001 -- the message is the measurement
        print(f"  web_search_mode        rejected: {type(exc).__name__}: {str(exc)[:300]}")
    finally:
        await codex.close()


async def off_switch() -> int:
    """Can the hosted tool be turned off from the config this service controls?"""
    print("preflight")
    await _preflight(WEB_SEARCH_OFF)
    await _vocabulary()

    results = [
        await _run("A search, web_search=false", Sandbox.read_only, WEB_SEARCH_OFF, SEARCH_PROMPT),
        await _run("B fetch, web_search=false", Sandbox.read_only, WEB_SEARCH_OFF, FETCH_PROMPT),
    ]

    print("\n--- summary " + "-" * 52)
    for row in results:
        print(f"{row['label']:34} search={row['web_search_item']!s:5} canary={row['canary']!s:5}")
    closed = not any(row["web_search_item"] for row in results)
    print(f"\ntools.web_search=false: {'CLOSES IT' if closed else 'CHANGES NOTHING'}")
    return 0


async def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("no credential; set OPENAI_API_KEY")
        return 2

    if len(sys.argv) > 1 and sys.argv[1] == "off":
        return await off_switch()

    print("preflight, override OFF")
    await _preflight(())
    print("preflight, override ON")
    await _preflight(WEB_SEARCH_ON)

    results = [
        await _run("1 search, no override", Sandbox.read_only, (), SEARCH_PROMPT),
        await _run("2 search, web_search=true", Sandbox.read_only, WEB_SEARCH_ON, SEARCH_PROMPT),
        await _run("3 fetch a URL, web_search=true", Sandbox.read_only, WEB_SEARCH_ON, FETCH_PROMPT),
        await _run(
            "4 shell curl, web_search=true",
            Sandbox.workspace_write,
            WEB_SEARCH_ON,
            SHELL_PROMPT,
        ),
    ]

    print("\n--- summary " + "-" * 52)
    for row in results:
        print(f"{row['label']:34} search={row['web_search_item']!s:5} canary={row['canary']!s:5}")
    shell = results[3]
    verdict = "STILL BLOCKED" if not shell["reached_http_200"] else "THE SHELL REACHED THE NETWORK"
    print(f"\nsandbox with the hosted tool on: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
