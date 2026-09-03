# The gemini-python image: a Python service and the Node agent it drives.
#
# **A NODE base, where the other two builds use a Python one, and that is the
# target rather than a preference.** `@google/gemini-cli` is a Node program --
# `bin: {gemini: "bundle/gemini.js"}`, `engines: {node: ">=20"}` -- and there is
# no Python distribution of it (GP-41). The other builds get their agent
# vendored inside a Python package; this one installs it with npm, so the
# runtime with the hard version constraint is the one that picks the base image.
#
# **22 rather than 20, chosen against the constraint rather than inherited.**
# The package requires >=20; 22 is the active LTS line, and the probe Dockerfile
# that first used it did so without checking. Pinned by digest for the reason
# every base image here is: a floating tag makes "the same image" unprovable.
FROM node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436

# curl for the healthcheck, and nothing else. `node -e fetch(...)` would avoid
# it, but a healthcheck that starts a Node runtime to answer costs more than the
# 3 MB it saves.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# --- the agent ---------------------------------------------------------------
#
# **Pinned to the version every measured fact in this build was taken against.**
# There is no SDK and no semantic-versioning promise over the CLI's flags or over
# which ACP methods it registers, so a floating version would silently move the
# ground under every measured fact this build rests on. GP-33 is the recheck
# order for an upgrade, cheapest first.
ARG GEMINI_CLI_VERSION=0.54.4
RUN npm install -g "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
 && npm cache clean --force \
 # **Verified, not assumed.** A `npm install` that resolves but produces a
 # broken shim fails the build here rather than the first turn -- the same
 # reason the Claude build checks its bundled binary's size and exec bit.
 && test -x "$(command -v gemini)" \
 && gemini --version \
 && test "$(gemini --version | tail -1)" = "${GEMINI_CLI_VERSION}"

# --- the service -------------------------------------------------------------

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python
WORKDIR /app

# The manifest first, so a source edit does not cost a dependency re-resolve.
COPY gemini-python/pyproject.toml gemini-python/uv.lock ./
COPY common/agent-spec/ ../common/agent-spec/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    # uv provides the interpreter: this base image ships Node, not Python 3.13,
    # and the agent is the runtime with the version constraint worth honouring.
    uv python install 3.13 \
 && uv sync --frozen --no-dev --no-install-project

COPY gemini-python/src/ ./src/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run the installed console scripts directly rather than through `uv run`, which
# would re-check the environment on every start -- needing write access to /app
# as a non-root user -- and would sit between PID 1 and uvicorn.
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

# --- the user, and the directories it must own -------------------------------
#
# **`/app` stays root-owned**: the service must not be able to modify its own
# code. Everything the agent writes goes somewhere else.
# **RENAMED, not created**, and that is a real difference from the other two
# builds' Dockerfiles. This base image already has a `node` user at uid 1000, so
# `useradd --uid 1000 agent` fails with exit 4. Keeping **uid 1000** matters more
# than the name: a host bind mount owned by 1000 stays writable, exactly as it is
# for `claude-python` and `codex-python`. Renaming to `agent` keeps one name
# across all three.
RUN usermod --login agent --home /home/agent --move-home node \
 && groupmod --new-name agent node \
 && mkdir -p /workspace /var/lib/agent-service/homes /var/lib/agent-service/transcripts \
 && chown agent:agent /workspace /var/lib/agent-service/homes /var/lib/agent-service/transcripts
USER agent

# **HOME must be writable even though the service overrides it per session.**
# Each session runs with HOME pointed at its own directory (GP-39), but the
# agent also writes outside a turn -- `gemini --version` in the healthcheck path,
# and its own first-run state -- and a read-only HOME turns that into a failure
# nobody expects.
ENV HOME=/home/agent

ENV AGENT_SERVICE_WORKSPACE_DIR=/workspace \
    AGENT_SERVICE_AGENT_HOME_ROOT=/var/lib/agent-service/homes \
    AGENT_SERVICE_TRANSCRIPT_STORE=/var/lib/agent-service/transcripts \
    AGENT_SERVICE_GEMINI_BINARY=gemini \
    # ON by default so a container gets the mount check without anyone
    # remembering a flag; a plain checkout turns it off in `.env.example`.
    AGENT_SERVICE_REQUIRE_MOUNTS=true

# **The two artifacts this image was built against, readable WITHOUT running
# it** (GP-62). `docker inspect` answers from image metadata, so it works on
# an image that cannot start and in tooling that never executes one.
#
# **These are the KEY to the published document, and since 0.19.0 that is
# their whole job.** The pre-boot command that used to print the same values
# is gone; `impl` and `document-version` together name the one document that
# states which credential variable this image reads, which variable moves its
# endpoint and which one delivers a private certificate authority. So a
# consumer reads metadata and then an artifact it already depends on, and
# executes nothing. Hand-written
# here on purpose: a build arg would leave the label EMPTY for anyone running a
# plain `docker build`, and the drift a constant risks is caught by the CI check
# that compares these labels against this image's own pre-boot output.
#
# Deliberately NOT the implementation version: the tag already carries it, and a
# third copy of a value that moves every build is maintenance with no reader.
LABEL org.opencontainers.image.title="agent-service-gemini-python"
LABEL com.npf.agent-service.impl="gemini-python"
LABEL com.npf.agent-service.document-version="0.21.0"
LABEL com.npf.agent-service.schema-revision="d3f9a0c15e27"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# AS-28: all interfaces INSIDE the container. A service bound to 127.0.0.1 here
# is reachable from nothing; the host publication is where an address is
# narrowed, and `compose.yaml` narrows it to loopback.
CMD ["uvicorn", "agent_service.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log"]
