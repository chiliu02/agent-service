"""Per-turn token usage, cost and context use, read from each CLI's own transcript.

Every CLI writes usage per model call into its session file. Herdr's socket
carries none of it, so this is where `usage`, `model_usage`, `cost_usd` and
`context_usage` come from.

  claude  JSONL, `type: assistant`, `message.usage`; records repeat per
          `message.id`, so the last one per id counts
  codex   rollout JSONL, `payload.type: token_count`, `info.total_token_usage`
          is cumulative, so a turn is the difference; `model_context_window`
          is the only window any CLI records
  pi      session JSONL, `message.role: assistant`, `message.usage` with `cost`
  gemini  chat JSONL, `type: gemini`, `tokens`

Usage is normalised to the four Anthropic-style keys, so a reader sums the same
names whatever the CLI. Windows the file does not record come from
PROTO_CONTEXT_WINDOWS: a JSON map of model-name prefix to tokens.
"""
from __future__ import annotations

import json
import os

KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
DEFAULT_WINDOWS = {"claude": 200_000, "gemini": 1_048_576, "gpt": 272_000}


def windows() -> dict[str, int]:
    try:
        return {**DEFAULT_WINDOWS, **json.loads(os.environ.get("PROTO_CONTEXT_WINDOWS", "{}"))}
    except ValueError:
        return DEFAULT_WINDOWS


def window_for(model: str | None) -> int | None:
    if not model:
        return None
    best = None
    for prefix, size in windows().items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, size)
    return best[1] if best else None


def lines(path: str, start: int = 0, end: int | None = None) -> list[tuple[int, dict]]:
    """(byte offset, record) for each JSON line in [start, end)."""
    out: list[tuple[int, dict]] = []
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read() if end is None else f.read(max(0, end - start))
    pos = start
    for raw in data.split(b"\n"):
        if raw.strip():
            try:
                r = json.loads(raw)
                if isinstance(r, dict):
                    out.append((pos, r))
            except ValueError:
                pass
        pos += len(raw) + 1
    return out


def _zero() -> dict[str, int]:
    return {k: 0 for k in KEYS}


def _add(into: dict, model: str, u: dict) -> None:
    for k in KEYS:
        into["usage"][k] += u.get(k, 0)
    per = into["model_usage"].setdefault(model or "unknown", _zero())
    for k in KEYS:
        per[k] += u.get(k, 0)


TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_output_tokens")


def _tok(into: dict, input_uncached, output, cache_read, cache_write, reasoning) -> None:
    """Accumulate the spec's TokenUsage. ONE convention for all four CLIs: `input_tokens`
    EXCLUDES the cache counts, so input + cache_read + cache_write is the prompt total, and
    `output_tokens` INCLUDES reasoning. None means the CLI records no such counter, and it
    stays None: publishing 0 would claim a count nobody made."""
    t = into["token_usage"]
    for k, v in zip(TOKEN_KEYS, (input_uncached, output, cache_read, cache_write, reasoning)):
        if v is not None:
            t[k] = (t[k] or 0) + int(v)


def turn_usage(kind: str, path: str | None, offset: int) -> dict | None:
    """Usage of the calls written after `offset`, and the context the last call used."""
    if not path or not os.path.isfile(path):
        return None
    out = {"usage": _zero(), "model_usage": {}, "cost_usd": None, "context": None, "calls": 0,
           "token_usage": {k: None for k in TOKEN_KEYS}}
    last: dict | None = None  # {"used", "window", "model"}
    if kind == "claude":
        by_id: dict[str, tuple[str, dict]] = {}
        for _, r in lines(path, offset):
            m = r.get("message") if r.get("type") == "assistant" else None
            if isinstance(m, dict) and isinstance(m.get("usage"), dict):
                by_id[m.get("id") or str(len(by_id))] = (m.get("model") or "", m["usage"])
        for model, u in by_id.values():
            _add(out, model, {k: int(u.get(k) or 0) for k in KEYS})
            details = u.get("output_tokens_details") if isinstance(u.get("output_tokens_details"), dict) else {}
            _tok(out, u.get("input_tokens") or 0, u.get("output_tokens") or 0, u.get("cache_read_input_tokens") or 0,
                 u.get("cache_creation_input_tokens") or 0, details.get("thinking_tokens"))
            used = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            last = {"used": used, "window": window_for(model), "model": model}
        out["calls"] = len(by_id)
    elif kind == "codex":
        before = after = None
        model, ctx_window, last_call = "", None, None
        for pos, r in lines(path):
            p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            if p.get("type") == "turn_context" or r.get("type") == "turn_context":
                model = p.get("model") or model
            if p.get("type") == "token_count" and isinstance(p.get("info"), dict):
                info = p["info"]
                if pos < offset:
                    before = info.get("total_token_usage")
                else:
                    after, last_call = info.get("total_token_usage"), info.get("last_token_usage")
                    ctx_window = info.get("model_context_window") or ctx_window
                    out["calls"] += 1
        if after:
            b = before or {}

            def d(k):
                return int(after.get(k) or 0) - int(b.get(k) or 0)
            cached = d("cached_input_tokens")
            _add(out, model, {"input_tokens": d("input_tokens") - cached, "output_tokens": d("output_tokens"),
                              "cache_read_input_tokens": cached,
                              "cache_creation_input_tokens": d("cache_write_input_tokens")})
            _tok(out, d("input_tokens") - cached, d("output_tokens"), cached,
                 d("cache_write_input_tokens") if "cache_write_input_tokens" in after else None,
                 d("reasoning_output_tokens") if "reasoning_output_tokens" in after else None)
            if last_call:
                last = {"used": int(last_call.get("input_tokens") or 0), "window": ctx_window, "model": model}
    elif kind == "pi":
        cost = 0.0
        for _, r in lines(path, offset):
            m = r.get("message") if isinstance(r.get("message"), dict) else None
            if m and m.get("role") == "assistant" and isinstance(m.get("usage"), dict):
                u = m["usage"]
                model = m.get("model") or ""
                _add(out, model, {"input_tokens": int(u.get("input") or 0), "output_tokens": int(u.get("output") or 0),
                                  "cache_read_input_tokens": int(u.get("cacheRead") or 0),
                                  "cache_creation_input_tokens": int(u.get("cacheWrite") or 0)})
                _tok(out, u.get("input") or 0, u.get("output") or 0, u.get("cacheRead") or 0, u.get("cacheWrite") or 0,
                     u.get("reasoning"))  # pi writes it only when the model thought; otherwise it stays None
                cost += float((u.get("cost") or {}).get("total") or 0)
                used = int(u.get("input") or 0) + int(u.get("cacheRead") or 0) + int(u.get("cacheWrite") or 0)
                last = {"used": used, "window": window_for(model), "model": model}
                out["calls"] += 1
        out["cost_usd"] = round(cost, 6)
    elif kind == "gemini":
        for _, r in lines(path, offset):
            if r.get("type") == "gemini" and isinstance(r.get("tokens"), dict):
                t = r["tokens"]
                model = r.get("model") or ""
                cached = int(t.get("cached") or 0)
                _add(out, model, {"input_tokens": int(t.get("input") or 0) - cached,
                                  "output_tokens": int(t.get("output") or 0) + int(t.get("thoughts") or 0),
                                  "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0})
                _tok(out, int(t.get("input") or 0) - cached, int(t.get("output") or 0) + int(t.get("thoughts") or 0),
                     cached, None, t.get("thoughts"))  # gemini records no cache-write counter
                last = {"used": int(t.get("input") or 0), "window": window_for(model), "model": model}
                out["calls"] += 1
    if last:
        out["context"] = last
    return out if out["calls"] else None


def context_usage(ctx: dict | None) -> dict | None:
    """The `ContextUsage` shape: categories, with one named `Free space` (what Harness's freeTokens reads)."""
    if not ctx or not ctx.get("window"):
        return None
    used, window = ctx["used"], ctx["window"]
    return {"categories": [{"name": "Used", "tokens": used}, {"name": "Free space", "tokens": max(0, window - used)}],
            "total_tokens": used, "max_tokens": window, "model": ctx.get("model"),
            "source": "transcript"}
