# Security policy

## Reporting a vulnerability

Use GitHub's **[private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)**
— the *Report a vulnerability* button on this repository's **Security** tab.
That opens a private advisory only the maintainers can read.

Please do **not** open a public issue for anything you believe is exploitable.

Include what you did, what happened, and which build and version
(`GET /v1/capabilities` reports `impl.name` and `impl.version`; the image
carries both as labels). A reproduction against
`impl/gemini-python/tests/fake_cli_agent.py` — which needs no credential and
emits the real stream shapes — is worth more than a description, and costs
nothing to run.

Expect an acknowledgement within a week. This is a small project and there is
no paid response commitment behind that number.

## Supported versions

The current release only. There is no long-term-support branch and no
backporting: fixes land on `main` and go out in the next version.

| Version | Supported |
|---|---|
| 0.19.0 | ✅ |
| < 0.19.0 | ❌ |

## Read this before reporting: the threat model is unusual

**This service exists to give a coding agent a shell.** Every build ships
`Bash` (or its equivalent) enabled, and all three publish
`permission_enforcement: "none"`. So the following are **the specification
working as designed**, not vulnerabilities:

- A prompt causes the agent to run an arbitrary command, read a file, or write
  one. That is the product.
- A prompt causes the agent to reach the network — on `claude-python` and
  `gemini-python`, which publish `sandbox.network_access: true`.
- A prompt causes a write outside `/workspace` — on `claude-python` and
  `gemini-python`, which publish
  `sandbox.confines_writes_to_workspace: false`.
- An unauthenticated caller reaches the API. Authentication is **off by
  default** on all three builds (`AGENT_SERVICE_REQUIRE_AUTH` defaults false),
  and `/v1/capabilities` says so via `auth_required`.

**The container is the security boundary, and it is the only one this project
claims.** `codex-python` is the exception worth knowing about: it sandboxes
every turn and publishes `sandbox.network_access: false`, so its agent cannot
reach the network at all.

What *is* in scope, and worth reporting:

- Anything that crosses the container boundary — a container escape, or a path
  that reaches a host resource the operator did not mount.
- A caller reading or affecting **another caller's** session, transcript or
  workspace when the deployment intended them separated.
- A credential leaking somewhere it should not be: into a response body, a log
  line, an event, a transcript row, or a process argument list. MCP bearer
  tokens are the sharp case — this is why a `422` deliberately omits `input`.
- Authentication being bypassable when it *is* configured
  (`AGENT_SERVICE_REQUIRE_AUTH=true` with a token set).
- A boot gate that fails open: the service starting when it should have
  exited 3 for a missing credential, a missing mount, or missing auth.
- Anything that contradicts what `/v1/capabilities` publishes. The published
  capability surface is a contract, and a build that under-reports its own
  reach is a defect regardless of whether the reach itself is intended.

## Running one of these safely

**Do not put an unauthenticated instance on a network you do not control.**
The defaults are tuned for a developer's own machine, not for a shared host.
Minimum for anything else:

1. **Set `AGENT_SERVICE_REQUIRE_AUTH=true` and an `AGENT_SERVICE_AUTH_TOKEN`.**
   With `require_auth` set and no token configured, the service refuses to
   boot rather than starting unauthenticated — which is the point of the gate.
2. **Bind to loopback and tunnel**, rather than publishing the port. The
   compose files publish `127.0.0.1:8000` for this reason.
3. **Keep `require_mounts` at its default (`true`).** Docker silently *creates*
   a missing bind-mount source and starts the container anyway; the service
   checks instead, and exits 3.
4. **Mount only what the agent should reach**, and mount reference material
   read-only. The mount split is the real confinement on two of the three
   builds.
5. **Chown the bind-mount source to `uid:gid 1000:1000` before starting** —
   `PrebootSpec.runs_as`, `const`-pinned in each build's OpenAPI document.
   Docker creates a missing mount point as `root:root`, and the agent is not
   root.
6. **Bound the container**: `--memory`, `--pids-limit`,
   `--security-opt no-new-privileges:true`, `--cap-drop ALL`. Nothing bounds
   memory unless you say so; measured at ~110 MiB and ~17 pids per session over
   a ~250 MiB warm baseline.
7. **Read `always_disallowed_tools`** on `/v1/capabilities` before assuming a
   tool is unavailable, and read the build's own guide under
   `impl/<build>/docs/` before deploying it. The three builds differ in what
   confines the agent, and `permission_enforcement: "none"` means three
   different things across them.

[`docs/security-posture.md`](./docs/security-posture.md) is the full threat
model — the assets, what actually holds them today, and the section on what
authentication cannot fix at all.
