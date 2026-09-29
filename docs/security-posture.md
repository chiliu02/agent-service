# Security posture — what threatens this, and what "production ready" means

**Answers [`open-questions.md` Q6](./open-questions.md) (service-level
authentication), and is written to be read by someone deciding what to build
rather than by someone who already knows the answer.**

Written 2026-08-07. Every claim about behaviour is measured — in this repo's
source, in the running container, or in Agent Studio's source where it is
Studio's half. Where something is reasoned rather than measured it says so.

**The short answer, before the reasoning:** authentication is *third* on the
list, the first item is not in this service at all, and the largest residual risk
is one that no authentication can reduce. If you read nothing else, read
[§6](#6-what-authentication-cannot-fix-ever).

---

## 1. What there is to lose

Threat modelling goes wrong when it starts from mechanisms. Start from assets —
you cannot rank defences without knowing what they defend.

| # | Asset | Why it is worth taking | What holds it today |
|---|---|---|---|
| **A1** | **Model spend** | Directly convertible to money. Nobody has to break anything to use it — it is the service's *purpose* | Studio's gateway holds the real Anthropic key; containers get a per-Agent token |
| **A2** | **The workspace** | Whatever is mounted: source, configuration, credentials committed to a repo, `.git` history | The mount boundary. Read-write by design — the agent is *supposed* to edit it |
| **A3** | **Other tenants' data** | Sessions, transcripts, prompts. Under Studio's D-17 nothing belonging to another user may be visible, *"not even its existence"* | One shared schema (D-08) + Studio's own scoping. `agent_id` (0.9.0) is what lets that scoping rest on data rather than bookkeeping |
| **A4** | **Credentials the container holds** | The gateway token, any MCP secret, anything in the environment | **Nothing.** See §4.3 — this is measured, structural, and by design |
| **A5** | **The host** | Everything above, for every tenant, plus whatever else runs there | The container boundary and its dropped capabilities |

**A1 and A2 are the ones that pay.** A3 is the one that ends a product. A5 is the
one everybody thinks about first and is the best defended.

## 2. Who would take it

Four adversaries, ordered by how likely they are to be the one you actually meet.

### 2.1 A prompt, not a person — the one that is underweighted

**The agent reads untrusted text and acts on it.** A file in the workspace, a web
page it fetched, a tool result, the contents of a repository it was asked to
review. Nothing is "breached": the agent does exactly what it is built to do,
having been told to do something else by data.

This adversary is first on the list because **it is the only one that arrives
through legitimate use**, and because every control in §4 except the last is
irrelevant to it. The caller was authorised. The network was correct. The
container was the right one.

### 2.2 An authorised user

A real Studio user, doing something they are permitted to start, to reach
something they are not permitted to see. The interesting cases are A3
(cross-tenant) and A1 (spend somebody else's budget).

### 2.3 Anyone who can route to the host

Today this is a live adversary rather than a hypothetical one — see §3.1.

### 2.4 A compromised container

Not really a separate adversary: any of the above who gets one turn has this,
because `Bash` is enabled and `permission_enforcement` defaults to `"none"`.
**Treat "the agent ran" and "an attacker has a shell in that container" as the
same event.** That is not a weakness to fix; it is what the service is for, and
it is why the container is the boundary.

## 3. How they would get it — measured, today

### 3.1 The `/v1` surface is reachable, and this is the live gap

**This service's own shipped deployment is loopback-bound.** `compose.yaml`
publishes `127.0.0.1:8000:8000`, and its comment calls that the most important
line in the file.

**Studio's provisioning is not.** Measured in Studio's own source and reported by
them: `DockerDaemons.create` sets no `NetworkMode`, so every container is on the
default bridge, and binds with `bindPort(0)` and **no host IP** — `0.0.0.0` on an
ephemeral port. ADR-0017 (per-user network, no published port) is **accepted and
entirely unbuilt.**

So: **an unauthenticated API whose documented capability is arbitrary shell
execution is reachable by anything that can route to the host.** One `POST
/v1/sessions` plus one prompt is A2, A4 and A1, and — because that session was
never recorded by Studio — A3 as a side effect.

This is the single largest item, and **it is not in this service.**

### 3.2 Prompt injection needs no gap at all

§2.1. There is no step here to describe: the agent is given text, the text says
to do something, the agent has `Bash`.

### 3.3 The container cannot keep a secret from the agent

Measured (`spike-findings.md` M2, 2026-08-07):

- the CLI subprocess runs as **uid 1000 — the agent's own user**;
- `/proc` is mounted without `hidepid`;
- MCP `headers` and `env` are serialised into a single `--mcp-config` **argv**,
  read back from `/proc/<pid>/cmdline` as the agent user in a live container.

`config.py` already records the same thing for the credential: it pops
`AGENT_SERVICE_DATABASE_URL` out of the environment at startup precisely because
the agent inherits it, and notes that `ANTHROPIC_API_KEY` **cannot** be hidden
that way because the CLI needs it.

**This is structural, not a defect.** The agent's own client must authenticate
with the secret, so the secret must be reachable by the agent's uid. No channel
changes that — a file instead of argv narrows the *audience*, not the secrecy.

### 3.4 Budget is not a control

Measured: with `max_budget_usd=0.05`, **eight** consecutive start-then-interrupt
turns advanced the CLI's accumulator by **$0.000649** and never tripped it; six
ordinary turns on the same connection tripped it at $0.0585. An interrupted turn
costs real inference and moves the figure the limit is checked against by almost
nothing.

**A caller who can interrupt can spend without limit under any value.** The
ceiling has to be at the account, or at a gateway that sees every request whether
or not its turn completed.

## 4. What each control actually buys

Ordered by risk removed per unit of work — which is *not* the order they are
usually built in.

### 4.1 Network isolation — the largest, and it is Studio's

Reachability is the precondition for §3.1 and for most of §2.3. ADR-0017's
per-user network plus an unpublished port removes the entire class, and Studio's
own answer to "how does Studio then reach it" is a per-Host relay — *"where a
credential and TLS can exist without asking agent-service to grow an auth model
it deliberately does not have."*

**Build this before authentication.** Authenticating an API that should not be
reachable is a second lock on a door standing in a field. If the relay lands,
this service may need no authentication at all for this client.

### 4.2 Authentication on `/v1` — necessary, and second

What it answers: *is the caller Studio?* What it does not answer: anything in
§2.1 or §2.2.

The asymmetry that decides the mechanism, and it is unusual enough to be worth
stating twice:

> **Studio's credential is safe here. This service's is not.**

Studio's client key never enters the agent's container. Anything *this service*
holds — bearer token, TLS private key — is readable by the agent it is
sandboxing (§3.3). Therefore:

| Mechanism | Verdict |
|---|---|
| One bearer token shared across instances | **No.** Any user who can take one turn reads it, and then holds the fleet |
| Per-instance bearer token | Workable. Blast radius one instance; rotation is a redeploy; must grant access to *nothing but* that instance |
| **mTLS, Studio as client** | **Best for the direction that matters.** Studio's private key is never in the agent's reach; revocation and expiry are real |
| Per-request caller identity | **Not wanted**, and Studio has said so: the owner is resolved from the Agent, so a caller claim would be a second, weaker source of truth |

### 4.3 Tenancy — Studio's, and now resting on data

One shared schema means every row belongs to somebody and, until 0.9.0, no column
said which. `agent_id` is provenance, not enforcement: agent-service still scopes
nothing. What changed is that Studio's scoping now stands on **data produced by
the thing that made the row** rather than on Studio's bookkeeping never having
missed one.

### 4.4 Blast-radius controls — the ones that work against §2.1

The only layer that touches prompt injection, because it assumes the agent is
already doing the attacker's bidding:

- **Mount only what the agent needs.** A2 is exactly the mount. The read-only
  reference mount is a **kernel** boundary, not a convention: measured `EROFS`
  from a shell redirect, a Python `open()`, and `mkdir` alike.
- **Per-instance, budget-capped model credentials**, since §3.3 says the agent
  will read whatever it holds and §3.4 says the service cannot cap spend.
- **Keep the real key out of the container**, which Studio's gateway already
  does — *"the key now never enters a container at all."*
- **`permission_enforcement=hook`** confines `Write`/`Edit`/`NotebookEdit` to the
  workspace, and is measured to actually block an out-of-workspace write. It does
  **not** confine `Bash`: `echo x > /etc/foo` walks straight past it. Useful, and
  not a boundary.

## 5. So what is "production ready"?

It depends on the deployment, and conflating the three is how this gets
mis-answered.

### One operator, one machine

**Today's posture is adequate**, and it is what the README documents: loopback
binding, the container boundary, mounts you chose. No authentication needed —
there is no second party to authenticate. This is the only shape Q6 was deferred
against, and the deferral was correct for it.

### Multi-user Studio on a shared host — the real target

In order, and the order is the point:

1. **ADR-0017: per-user network, no published port.** Studio's. Removes §3.1
   entirely. Nothing else is worth doing first.
2. **The per-Host relay**, with TLS and a credential. Studio's. This is where
   authentication naturally lives.
3. **Authentication on `/v1`** — mTLS with Studio as client, or per-instance
   bearer tokens as a first step. **Only if 1 and 2 leave a hop that needs it.**
4. **Per-instance model credentials with account-level budget.** Not optional:
   §3.3 plus §3.4 mean this is the only real spend control.
5. **Audit that mounts are minimal**, because after 1–4 the mount is the
   remaining path to A2.

**Items 1 and 2 are Studio's, 4 and 5 are the operator's, and only item 3 is
this service's.** That is the honest shape of the answer, and it is why Q6 stayed
deferred while other things shipped.

### Internet-exposed

**Don't.** Not "harden it first" — the capability being exposed is arbitrary
shell execution as a service, and no authentication makes that a sensible thing
to put on a public address. If it must be reachable across a network, terminate
that somewhere else and let the relay of item 2 be the only thing that talks to
the container.

## 6. What authentication cannot fix, ever

**Authentication answers "who is calling". It says nothing about what the agent
does once it is running**, and §2.1 is an attacker who arrives through a
perfectly authorised call.

A correctly authenticated, correctly networked, correctly provisioned deployment,
running exactly the user who is supposed to be running it, will still do whatever
a README in the workspace tells it to. Every control in §4.1–4.3 is intact and
none of them is engaged.

That is why §4.4 is not a footnote. **Against the most likely adversary, the only
controls that work are the ones that assume the attack has already succeeded:**
what is mounted, what the credential can spend, and what the container can reach.

The honest framing for anyone deciding here: *authentication makes the system
safe to expose to more people; it does not make the agent safe.* Those are
different problems, and only the first has a standard answer.

## 7. The rule that keeps recurring

Three decisions in this repo turned out to be the same one:

- `ANTHROPIC_API_KEY` cannot be hidden from the agent (`config.py`);
- MCP secrets are readable by the agent (M2);
- a shared bearer token would be readable by the agent (§4.2).

> **A component that runs untrusted code on your behalf cannot hold a secret
> that matters. Give it credentials scoped to itself, and put anything else
> behind something it has to ask.**

Studio's gateway is that pattern already: the container gets a token that buys
model calls and nothing else, and the key that would buy everything never
arrives. Anything added later — a database credential, a registry token, a
signing key — should be measured against the same rule before it is put in the
container's environment.
