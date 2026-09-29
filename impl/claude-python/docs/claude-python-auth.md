# `claude-python` — which credentials this build actually accepts

**A claude.ai subscription authenticates this build. The `.env` files said it
could not, and that sentence had never been measured.** It was written before the
first spike and repeated in three places for as long as this build has existed;
it is corrected here and in those files on 2026-09-05.

**Why it was worth a document rather than a one-line edit.** The sentence did not
merely misstate a fact — it sent a reader looking for a way to *replace the
Claude Agent SDK with the Claude Code CLI*, on the belief that the CLI was the
only path to subscription auth. That rewrite would have cost a fourth build and
bought nothing: the capability was already present, behind one environment
variable and one boot check. A false negative about your own software is
expensive in a direction that a false positive is not.

For running this build, see
[`claude-python-operations.md`](./claude-python-operations.md); for the evidence
behind other claims, [`claude-python-references.md`](./claude-python-references.md).

---

## 1. The claim that was wrong

Three files carried it, in two wordings:

| File | Line | Text |
|---|---|---|
| `.env.example` | 4–5 | "the claude.ai subscription login used by the Claude Code CLI is NOT valid for SDK-powered products. This must be a real API key." |
| `.env.compose.example` | 54–55 | the same sentence, in the compose credentials block |
| `.env` | 4–5, 88–89 | both of the above — the operator's file is `.env.example` with `.env.compose.example` appended, so it carried two copies |

Fixing one and not the others would have reintroduced it: the documented setup
flow is `cp .env.example .env` then `cat .env.compose.example >> .env`.

## 2. What was measured

Windows host, 2026-09-05. `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and
`CLAUDE_CODE_OAUTH_TOKEN` were all **absent from the environment** for every run
below. `claude auth status` reported:

```json
{ "loggedIn": true, "authMethod": "claude.ai",
  "apiProvider": "firstParty", "subscriptionType": "max" }
```

**The CLI.** `claude -p "reply with the single word: ok" --model haiku
--output-format json` returned `"subtype":"success"`, `"result":"ok"`, with
`total_cost_usd` populated.

**The SDK — the decisive one, since the claim was specifically about
"SDK-powered products".** A one-turn `claude_agent_sdk.query()` from this build's
own `.venv`:

```
ANTHROPIC_API_KEY present: False
ANTHROPIC_AUTH_TOKEN present: False
CLAUDE_CODE_OAUTH_TOKEN present: False
subtype: success | is_error: False | result: ok | cost_usd: 0.059193
```

**The service.** `claude-python` itself, unmodified, started with an empty key so
that `.env`'s real one could not apply:

```bash
ANTHROPIC_API_KEY="" \
AGENT_SERVICE_REQUIRE_CREDENTIALS=false \
AGENT_SERVICE_REQUIRE_MOUNTS=false \
AGENT_SERVICE_WORKSPACE_DIR=<abs path> \
AGENT_SERVICE_DEFAULT_MODEL=claude-haiku-4-5 \
  uv run uvicorn agent_service.main:app --host 127.0.0.1 --port 8791
```

```
POST /v1/query  {"prompt":"reply with the single word: ok","options":{"max_turns":1}}

{"result":"ok","is_error":false,"subtype":"success",
 "terminal_reason":"completed","num_turns":1,"total_cost_usd":0.0075426,
 "model_usage":{"claude-haiku-4-5":{...,"provider":"firstParty"}}}
```

Boot, turn, outcome recording and `model_usage` all worked on the OAuth
credential. Nothing in this build was changed to make that happen.

## 3. Why the SDK cannot behave differently from the CLI

It is not a second client. It is a wrapper that **ships and spawns the same
binary**:

- `claude_agent_sdk/_bundled/` carries the Claude Code executable. This build's
  `Dockerfile` installs no Node and no npm, yet the image runs the CLI — that is
  where it comes from.
- `_internal/transport/subprocess_cli.py` builds the child environment as
  `{**inherited_env, CLAUDE_CODE_ENTRYPOINT, **options.env, CLAUDE_AGENT_SDK_VERSION}`,
  filtering only `CLAUDECODE`. It never sets, requires, or looks for an API key.
- `_internal/session_resume.py` reads `CLAUDE_CODE_OAUTH_TOKEN` and the macOS
  Keychain OAuth credentials explicitly. The SDK is not merely tolerant of
  subscription auth; it knows about it.

And this service does not interfere: `get_settings()` pops exactly one name,
`AGENT_SERVICE_DATABASE_URL`. Everything else — including `HOME`, and therefore
the `.claude` directory under it — reaches the agent subprocess intact.

## 4. Precedence: a present key always wins

Measured, because the difference between "empty" and "invalid" is the one that
will waste an afternoon:

| `ANTHROPIC_API_KEY` | What happens |
|---|---|
| absent from the environment | falls back to the claude.ai OAuth credential; turn succeeds |
| set to the empty string | treated as absent; falls back to OAuth; turn succeeds |
| a valid key | the key is used; OAuth is not consulted |
| a **present but invalid** key | the key is used and there is **no fallback** — the turn hangs retrying. Killed at 120 s |

The last row is why "just clear the key" needs care: an invalid value is worse
than no value.

**`.env` interacts with this through `main.py`'s `load_dotenv(override=False)`.**
A name already in the environment is not overridden — and an empty string counts
as present. So `ANTHROPIC_API_KEY=""` in the shell is what neutralises a key
sitting in `.env`; deleting the line from `.env` does the same thing permanently.

## 5. The boot gate is what refuses a subscription

`config.py` defines the accepted set:

```python
CREDENTIAL_ENV_VARS: list[str] = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
```

`credentials_configured()` is a presence check over that list plus the three
cloud selectors (`CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY`), and
`verify_credentials()` exits 3 when none is set. An OAuth credential satisfies
none of them, so **the service refuses to start even though the agent it would
have spawned could authenticate perfectly well**. `config.py` already flagged
this gap in its own scope note; what was missing was the measurement, not the
suspicion.

`CLAUDE_CODE_OAUTH_TOKEN` appears nowhere in `impl/*/src` or `spec/` as of
2026-09-05.

**That list is a published capability**, exported as `credential_sources` from
`api.py` and `spec.py` and pinned by
`test_the_published_credential_specification_is_the_one_the_gate_checks`. Adding
a name to it moves `/v1/capabilities` and pulls
[`../../../docs/capability-divergence.md`](../../../docs/capability-divergence.md)
§2 with it — so it is a specification decision, not a local edit.

## 6. Running on a subscription today

**On a host that has logged in** (`claude auth login`), it works now, with one
flag:

```bash
AGENT_SERVICE_REQUIRE_CREDENTIALS=false
```

plus no `ANTHROPIC_API_KEY` in the environment or in `.env`. That is the
documented escape hatch, described in
[`claude-python-operations.md`](./claude-python-operations.md) for docs-only use;
here it is being used to get past a gate that is checking for the wrong thing.

**In the container** there is no keychain and no interactive login, so the
credential has to arrive as data. Two ways, both of which the SDK and the CLI
read identically:

- `claude setup-token` on the host — the CLI's own help describes it as "Set up a
  long-lived authentication token (requires Claude subscription)" — then pass the
  result as `CLAUDE_CODE_OAUTH_TOKEN`.
- Mount the host's `.claude/.credentials.json` into the image's `HOME`, which is
  `/home/agent` and is already required to be writable for the bundled binary.

Neither is wired into `compose.yaml` today, and
`AGENT_SERVICE_REQUIRE_CREDENTIALS=false` is still needed either way until §5's
list gains the name.

## 7. Two caveats that are not technical

**Whether a subscription may front a service is a terms question.** A Pro or Max
plan is priced for individual interactive use. That this repository *can*
authenticate a multi-tenant HTTP service with one is a measurement, not a
permission; check the plan's terms before depending on it.

**`total_cost_usd` stops meaning money.** On subscription auth the CLI still
populates it, at list price — the raw envelope carries `"costBasis": "list"`.
Anything downstream that bills or budgets off `total_cost_usd` (or off
`max_budget_usd`, which is enforced against the same figure) is then reading a
number that corresponds to no charge.
