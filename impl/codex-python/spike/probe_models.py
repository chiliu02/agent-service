"""Which models does `/v1/responses` actually serve to this key?

**The question `default_model` rests on.** This build published `gpt-5-codex`
until it was measured to 404 on the only key anyone here has, and the default is
`gpt-5.1` because of this probe (CX-21). Listing in `GET /v1/models` is not
evidence: every model below appears there, including the ones that 404.

**Direct HTTP, not the SDK, and that is the point.** A turn through the
app-server reports a failure that has already been through two translations;
this asks the endpoint the SDK will ask and reads the status code off the wire,
so a 404 is attributable to the model rather than to anything this service does.

**The control is the models that DO answer.** A run where everything 404s is
indistinguishable from a bad key, an expired account or a proxy in the way
without one -- which is the same reason `probe_network.py` runs `curl` outside
the sandbox before believing a block.

    uv run --no-project python spike/probe_models.py

Reads `OPENAI_API_KEY` (and honours `OPENAI_BASE_URL`, so it can be pointed at a
relay). **Costs approximately nothing**: a 404 is free and a 200 is capped at 16
output tokens on a one-word prompt.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

#: The codex family first -- the old default among them -- then the three that
#: answered 200 on 2026-08-09, `gpt-5.1` being the default since. The second
#: group is the control: if it 404s too, the finding is about the key.
MODELS = [
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-4.1-mini",
]


def _post(model: str) -> tuple[int, str]:
    """`(status, first line of the error)` for one model. Never raises."""
    body = json.dumps(
        {"model": model, "input": "hi", "max_output_tokens": 16}
    ).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            message = json.loads(payload)["error"]["message"]
        except Exception:  # noqa: BLE001 - the raw body is the fallback
            message = payload[:200]
        return exc.code, message
    except Exception as exc:  # noqa: BLE001 - a transport failure is a result
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    print(f"POST {BASE_URL}/responses\n")
    served = 0
    for model in MODELS:
        status, message = _post(model)
        print(f"  {model:<20} {status}  {message}")
        if status == 200:
            served += 1
    # Nothing answering is a finding about the key, not about the models.
    print(f"\n{served} of {len(MODELS)} answered 200")
    return 0 if served else 1


if __name__ == "__main__":
    raise SystemExit(main())
