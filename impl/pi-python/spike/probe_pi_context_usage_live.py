"""How full is a RESUMED pi session's window, before its first turn? (PI-65)

**SPENDS MONEY, a little.** Two one-word turns and one compaction, on a pinned
cheap model. Everything else in this probe is an RPC read with no model call.

**Why this exists.** Agent Harness reads `context_usage` from a session opened
with `resume`, before that session's first turn. This build spawns
`pi --mode json` per turn (PI-11) and has no long-lived pi process, so the only
way to ask pi is a short `pi --mode rpc --session <id>` process that sends
`get_session_stats` and exits. This probe measures whether that works, what it
returns, and where the window comes from.

**What it measures, in order:**

1. Two turns in `--mode json`, the way the build takes them, so a real session
   file exists. The last assistant message's `usage` is printed.
2. `get_session_stats` + `get_state` from a new RPC process on that session,
   with no turn: `contextUsage`, the model pi resolved, and the wall time.
3. The same with NO `--model` flag, beside an RPC process on NO session with no
   `--model`. If the first resolves the session's model and the second resolves
   a different one, the model is restored from the session file and not from a
   default.
4. The window under each way a model can reach pi through a gateway:
   a built-in model with no override; the same with a `models.json` entry that
   carries only `baseUrl` (what this build writes, PI-42); a model id pi does
   not know under a built-in provider; a custom provider whose model declares
   no `contextWindow`; and one that declares `contextWindow: 32000`. Each row
   also says whether `get_available_models` lists the resolved model.
5. `compact` over RPC (one model call), with `keepRecentTokens` lowered in a
   scratch `settings.json` so that a two-turn session is big enough, then `get_session_stats` in the same
   process and again from a new process: does `tokens` become `null`, and does
   it stay `null` across a resume?
6. One more `--mode json` turn, then a new RPC process: does `tokens` come back?
7. The agent's OWN compaction, which its docs put at `contextTokens >
   contextWindow - reserveTokens`: a turn with the threshold set far above the
   session (control), then one with it set below. Counts compaction entries in
   the session file before and after each.

Step 4 also declares a model with `contextWindow: 0`, the documented case where
`contextUsage` is omitted.

**Inside the image**, which is where the build runs it: the probe is stdlib
only, so the image's own Python runs it with `PI_BINARY=pi`:

    docker run --rm --name pi-ctx-probe -e GEMINI_API_KEY -e PI_BINARY=pi \
      -v "<this spike dir>:/probe:ro" --entrypoint python \
      agent-service-pi-python:<version> /probe/probe_pi_context_usage_live.py

**Nothing in step 4 sends a request.** The gateway `baseUrl` is
`http://127.0.0.1:9`, the discard port, so a stray request fails rather than
reaching anyone; no step there asks the model anything.

**Run it** from `impl/pi-python`, with a Gemini key in the environment:

    GEMINI_API_KEY=... uv run python spike/probe_pi_context_usage_live.py

`PI_PROBE_MODEL` overrides the model (default `google/gemini-3.1-flash-lite`).
`PI_BINARY` overrides the binary (default `spike/node_modules/.bin/pi`, or
`pi.cmd` on Windows; `npm ci` in `spike/` installs it). `PROBE_KEEP=1` keeps
the scratch directory and prints its path.

**On Windows the binary is a `.cmd` shim**, so killing the shim leaves node
holding the pipes. Each RPC process is therefore ended with `taskkill /T`, and
stderr goes to DEVNULL; reading stderr after a kill hangs this probe.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

MODEL = os.environ.get("PI_PROBE_MODEL", "google/gemini-3.1-flash-lite")
PROVIDER, MODEL_ID = MODEL.split("/", 1)
TURN_TIMEOUT_S = 90
RPC_TIMEOUT_S = 30
COMPACT_TIMEOUT_S = 120

HERE = Path(__file__).resolve().parent
DEFAULT_BIN = HERE / "node_modules" / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")
PI = os.environ.get("PI_BINARY", str(DEFAULT_BIN))

#: The same three variables the build sets on every agent process.
AGENT_ENV = {"PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}


class Pi:
    def __init__(self, root: Path) -> None:
        self.sessions = root / "sessions"
        self.agent = root / "agent"
        self.ws = root / "ws"
        for d in (self.sessions, self.agent, self.ws):
            d.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, **AGENT_ENV, "PI_CODING_AGENT_DIR": str(self.agent)}
        self.base = [PI, "--session-dir", str(self.sessions),
                     "--no-skills", "--no-extensions", "--no-context-files"]

    def models_json(self, doc: dict | None) -> None:
        path = self.agent / "models.json"
        if doc is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps(doc), encoding="utf-8")

    def compactions(self) -> int:
        """Compaction entries across the session files."""
        n = 0
        for f in self.sessions.rglob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    n += json.loads(line).get("type") == "compaction"
                except ValueError:
                    continue
        return n

    def turn(self, prompt: str, session: list[str]) -> dict | None:
        """One `--mode json` turn; the last assistant message's usage."""
        p = subprocess.run(
            [*self.base, "--mode", "json", *session,
             "--provider", PROVIDER, "--model", MODEL_ID, "-p", prompt],
            cwd=self.ws, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", timeout=TURN_TIMEOUT_S)
        usage = None
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            msg = ev.get("message") or {}
            if ev.get("type") == "message_end" and msg.get("role") == "assistant":
                usage = msg.get("usage")
        print(f"  turn rc={p.returncode} last assistant usage={json.dumps(usage)}")
        return usage

    def rpc(self, args: list[str], commands: list[dict],
            timeout: float = RPC_TIMEOUT_S) -> tuple[dict, float]:
        """Send commands to a fresh RPC process; return {id: response}, seconds.

        **One at a time, each after the previous one's response.** Sent together,
        pi answered `get_session_stats` while a `compact` was still running, so
        the figure printed as "after compact" was from before it.
        """
        # stderr to a FILE: a pipe read after the kill hangs on Windows (above).
        err_path = self.agent.parent / "rpc-stderr.txt"
        with open(err_path, "w", encoding="utf-8") as err:
            p = subprocess.Popen([*self.base, "--mode", "rpc", *args], cwd=self.ws,
                                 env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=err, text=True, encoding="utf-8")
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: [lines.put(x) for x in p.stdout], daemon=True).start()
        t0 = time.monotonic()
        got: dict = {}
        for c in commands:
            try:
                p.stdin.write(json.dumps(c) + "\n")
                p.stdin.flush()
            except OSError:
                # The agent exited before reading: report how, not a traceback.
                p.wait(timeout=10)
                tail = err_path.read_text(encoding="utf-8", errors="replace").strip()
                print(f"    agent EXITED before the command, rc={p.returncode}: {tail[-300:]}")
                return got, time.monotonic() - t0
            while c["id"] not in got and time.monotonic() - t0 < timeout:
                try:
                    msg = json.loads(lines.get(timeout=1))
                except queue.Empty:
                    if p.poll() is not None:
                        # Exited after reading: e.g. a models.json it rejects.
                        tail = err_path.read_text(encoding="utf-8", errors="replace").strip()
                        print(f"    agent EXITED, rc={p.returncode}: {tail[-300:]}")
                        return got, time.monotonic() - t0
                    continue
                except ValueError:
                    continue
                if msg.get("id") == c["id"]:
                    got[c["id"]] = msg
        elapsed = time.monotonic() - t0
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.kill()
        return got, elapsed

    def look(self, label: str, args: list[str]) -> dict:
        """get_state + get_session_stats + get_available_models, printed."""
        got, dt = self.rpc(args, [{"id": "state", "type": "get_state"},
                                  {"id": "stats", "type": "get_session_stats"},
                                  {"id": "models", "type": "get_available_models"}])
        state = (got.get("state") or {}).get("data") or {}
        stats = (got.get("stats") or {}).get("data") or {}
        listed = ((got.get("models") or {}).get("data") or {}).get("models") or []
        model = state.get("model") or {}
        key = (model.get("provider"), model.get("id"))
        in_catalogue = any((m.get("provider"), m.get("id")) == key for m in listed)
        print(f"--- {label}  ({dt:.2f}s)")
        print(f"    resolved model={key[0]}/{key[1]} contextWindow={model.get('contextWindow')} "
              f"listed by get_available_models={in_catalogue}")
        print(f"    session={stats.get('sessionId')} messages={stats.get('totalMessages')} "
              f"contextUsage={stats.get('contextUsage')}")
        return {"model": model, "stats": stats, "listed": listed}


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY") and PROVIDER == "google":
        print("GEMINI_API_KEY is not set -- this probe needs one", file=sys.stderr)
        return 2
    root = Path(tempfile.mkdtemp(prefix="pi-ctx-")).resolve()
    pi = Pi(root)
    sid = str(uuid.uuid4())
    print(f"binary={PI} model={MODEL} scratch={root}")
    try:
        print("\n== 1. two turns, the build's way")
        pi.turn("Reply with the single word: ok", ["--session-id", sid])
        last = pi.turn("Reply with the single word: again", ["--session", sid])
        print(f"  REFERENCE last assistant totalTokens={(last or {}).get('totalTokens')}")

        print("\n== 2. a new RPC process on the session, no turn")
        pi.look("rpc --session + --model", ["--session", sid,
                                            "--provider", PROVIDER, "--model", MODEL_ID])

        print("\n== 3. where the model comes from")
        pi.look("rpc --session, NO --model", ["--session", sid])
        default = pi.look("rpc, NO session, NO --model (pi's own default)", [])["model"]

        print("\n== 4. the window, per route to the model")
        gw = {"baseUrl": "http://127.0.0.1:9/gw"}
        pi.look("built-in model, no models.json", ["--session", sid,
                                                   "--provider", PROVIDER, "--model", MODEL_ID])
        pi.models_json({"providers": {PROVIDER: gw}})
        pi.look("built-in model, baseUrl-only override (what this build writes)",
                ["--session", sid, "--provider", PROVIDER, "--model", MODEL_ID])
        seen = pi.look("unknown id under a built-in provider, baseUrl-only override",
                       ["--session", sid, "--provider", PROVIDER, "--model", "my-private-model"])
        # pi copies its default model for the provider when an id is unknown
        # (PI-65). Every field but id/name is that model's, so compare a few.
        same = {k: (seen["model"].get(k), default.get(k))
                for k in ("contextWindow", "maxTokens", "api", "reasoning")}
        print(f"    vs pi's default {default.get('provider')}/{default.get('id')}: "
              f"(unknown, default) per field = {same}")
        pi.models_json(None)
        pi.look("unknown id under a built-in provider, no models.json",
                ["--session", sid, "--provider", PROVIDER, "--model", "my-private-model"])
        custom = {**gw, "api": "openai-completions", "apiKey": "x"}
        pi.models_json({"providers": {"gw": {**custom, "models": [{"id": "my-private-model"}]}}})
        pi.look("custom provider, model declared WITHOUT contextWindow",
                ["--session", sid, "--provider", "gw", "--model", "my-private-model"])
        pi.models_json({"providers": {"gw": {**custom, "models": [
            {"id": "my-private-model", "contextWindow": 32000}]}}})
        pi.look("custom provider, model declared WITH contextWindow 32000",
                ["--session", sid, "--provider", "gw", "--model", "my-private-model"])
        # The documented "omitted when no ... context window is available".
        # Measured: the agent rejects a declared window of 0 -- it drops the
        # whole provider and exits 1, "Unknown provider" -- so this case cannot
        # be reached through configuration.
        pi.models_json({"providers": {"gw": {**custom, "models": [
            {"id": "my-private-model", "contextWindow": 0}]}}})
        pi.look("custom provider, model declared with contextWindow 0 (expect no contextUsage)",
                ["--session", sid, "--provider", "gw", "--model", "my-private-model"])
        pi.models_json(None)

        print("\n== 5. compaction")
        # pi keeps the newest `keepRecentTokens` (default 20000) and summarizes
        # only what is older, so a session smaller than that answers "Nothing to
        # compact (session too small)". This session's four messages are a few
        # tokens each; 50 still kept all of them (measured). 1 keeps only the
        # newest. Probe-only: the build writes no settings.json.
        settings = pi.agent / "settings.json"
        settings.write_text(json.dumps({"compaction": {"keepRecentTokens": 1}}),
                            encoding="utf-8")
        got, dt = pi.rpc(["--session", sid, "--provider", PROVIDER, "--model", MODEL_ID],
                         [{"id": "c", "type": "compact"},
                          {"id": "s", "type": "get_session_stats"}],
                         timeout=COMPACT_TIMEOUT_S)
        c = got.get("c") or {}
        print(f"--- compact ({dt:.2f}s) success={c.get('success')} error={c.get('error')} "
              f"tokensBefore={(c.get('data') or {}).get('tokensBefore')}")
        print(f"    same process, after compact: contextUsage="
              f"{((got.get('s') or {}).get('data') or {}).get('contextUsage')}")
        pi.look("new RPC process after compaction", ["--session", sid])
        settings.unlink(missing_ok=True)

        print("\n== 6. one more turn after compaction")
        last = pi.turn("Reply with the single word: done", ["--session", sid])
        print(f"  REFERENCE last assistant totalTokens={(last or {}).get('totalTokens')}")
        window = pi.look("new RPC process after that turn", ["--session", sid])["model"].get(
            "contextWindow") or 0

        print("\n== 7. the agent's own compaction, after a turn in --mode json")
        # Documented and in the source: it compacts when contextTokens >
        # contextWindow - reserveTokens. A reserve of window-1000 puts the
        # threshold at 1000 tokens, below this session's ~1600; a reserve of
        # window-100000 puts it far above, as the control. `keepRecentTokens: 1`
        # in both, or a session this small has nothing to compact (step 5).
        for label, threshold in (("control, threshold 100000", 100_000),
                                 ("forced, threshold 1000", 1_000)):
            before = pi.compactions()
            settings.write_text(json.dumps({"compaction": {
                "reserveTokens": window - threshold, "keepRecentTokens": 1}}), encoding="utf-8")
            pi.turn("Reply with the single word: more", ["--session", sid])
            settings.unlink(missing_ok=True)
            print(f"--- {label}: compaction entries {before} -> {pi.compactions()}")
            pi.look(f"new RPC process after the {label} turn", ["--session", sid])
    finally:
        pi.models_json(None)
        if os.environ.get("PROBE_KEEP") == "1":
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
