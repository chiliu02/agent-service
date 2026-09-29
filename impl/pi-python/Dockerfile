# The pi-python image: a Python service and the Node agent it drives.
#
# **A NODE base, as in the gemini build and for the same reason.** Pi is a Node
# program -- `bin: {pi: …}`, `engines: {node: ">=22.19.0"}` -- and the Python
# distribution does not exist. So the runtime with the hard version constraint
# picks the base image, and uv provides the interpreter on top.
#
# **24 rather than 22**, because the package requires >= 22.19.0 and 24 is the
# active LTS line. Pinned by digest for the reason every base image here is: a
# floating tag makes "the same image" unprovable.
FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e

# curl for the healthcheck, and nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# --- the agent ---------------------------------------------------------------
#
# **Pinned to the version every measured fact in this build was taken against**
# (`PI-15`, `PI-16`, `PI-17`, and the whole references file). There is no
# semantic-versioning promise over this CLI's flags or its event names, so a
# floating version would silently move the ground under all of it. An upgrade
# re-runs `spike/probe_pi_cli.py` first, which is free.
ARG PI_VERSION=0.85.1
RUN npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
 && npm cache clean --force \
 # **Verified, not assumed.** An `npm install` that resolves but produces a
 # broken shim fails the build here rather than at the first turn.
 && test -x "$(command -v pi)" \
 && test "$(pi --version | tail -1)" = "${PI_VERSION}"

# --- the MCP adapter ---------------------------------------------------------
#
# **Installed ONCE into a fixed path, never per session** (`PI-43`). It is 42
# packages; installing it when a session opens would put that cost on every
# `POST /v1/sessions`.
#
# The service names this path with `--extension`, which the agent honours even
# under `--no-extensions` -- its own help says *"explicit -e paths still
# work"* -- so the adapter loads and nothing in the caller's mounted workspace
# does.
#
# `pi install` writes into whatever agent directory it is given, so it is
# pointed at a tools directory rather than at any session's.
ARG PI_MCP_ADAPTER_VERSION=2.32.1
ENV AGENT_SERVICE_MCP_ADAPTER_PATH=/opt/pi-mcp-adapter
RUN PI_CODING_AGENT_DIR=/opt/pi-agent-tools \
      pi install "npm:pi-mcp-adapter@${PI_MCP_ADAPTER_VERSION}" \
 # **Verified, not assumed**: an install that resolves but leaves no loadable
 # extension fails the build here rather than the first request carrying a
 # server.
 && test -f /opt/pi-agent-tools/npm/node_modules/pi-mcp-adapter/package.json \
 && ln -s /opt/pi-agent-tools/npm/node_modules/pi-mcp-adapter /opt/pi-mcp-adapter \
 && chmod -R a+rX /opt/pi-agent-tools

# --- the service -------------------------------------------------------------

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python
WORKDIR /app

# The manifest first, so a source edit does not cost a dependency re-resolve.
COPY pi-python/pyproject.toml pi-python/uv.lock ./
COPY common/agent-spec/ ../common/agent-spec/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv python install 3.13 \
 && uv sync --frozen --no-dev --no-install-project

COPY pi-python/src/ ./src/
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
#
# **RENAMED, not created.** This base image already has a `node` user at uid
# 1000, so `useradd --uid 1000 agent` fails with exit 4. Keeping **uid 1000**
# matters more than the name -- a host bind mount owned by 1000 stays writable,
# as on every other build -- and renaming to `agent` keeps one name across four.
RUN usermod --login agent --home /home/agent --move-home node \
 && groupmod --new-name agent node \
 && mkdir -p /workspace \
      /var/lib/agent-service/agent-dirs /var/lib/agent-service/sessions \
 && chown agent:agent /workspace \
      /var/lib/agent-service/agent-dirs /var/lib/agent-service/sessions
USER agent

# **HOME must be writable even though every turn relocates the agent's own
# directory** (`PI-05`). `PI_CODING_AGENT_DIR` covers the agent's state; Node
# itself and anything run outside a turn still want a home, and a read-only one
# turns that into a failure nobody expects.
#
# **`~/.agents` is masked deliberately.** Pi loads skills from there -- outside
# the relocatable agent directory -- so an empty read-only directory is what
# stops a stray skill on a mounted home reaching a turn. This build also passes
# `--no-skills` on every invocation (`PI-19`); the two together are belt and
# braces, and the flag alone was judged not enough because it is one edit away
# from being dropped.
ENV HOME=/home/agent
RUN mkdir -p /home/agent/.agents && chmod 0555 /home/agent/.agents

ENV AGENT_SERVICE_WORKSPACE_DIR=/workspace \
    AGENT_SERVICE_AGENT_DIR_ROOT=/var/lib/agent-service/agent-dirs \
    AGENT_SERVICE_SESSION_STORE=/var/lib/agent-service/sessions \
    AGENT_SERVICE_PI_BINARY=pi \
    # ON by default so a container gets the mount check without anyone
    # remembering a flag; a plain checkout turns it off in `.env.example`.
    AGENT_SERVICE_REQUIRE_MOUNTS=true

# **The two artifacts this image was built against, readable WITHOUT running
# it.** `docker inspect` answers from image metadata, so it works on an image
# that cannot start and in tooling that never executes one.
#
# **These are the KEY to the published document.** `impl` and `document-version`
# together name the one document that states which credential variables this
# image reads, which variable moves its traffic (`PI-07`) and which one delivers
# a private certificate authority (`PI-08`). A consumer reads metadata and then
# an artifact it already depends on, and executes nothing.
#
# Hand-written on purpose: a build arg would leave the label EMPTY for anyone
# running a plain `docker build`, and the drift a constant risks is caught by
# the CI check that compares these labels against the published document.
#
# Deliberately NOT the implementation version: the tag already carries it, and a
# third copy of a value that moves every build is maintenance with no reader.
LABEL org.opencontainers.image.title="agent-service-pi-python"
LABEL com.npf.agent-service.impl="pi-python"
LABEL com.npf.agent-service.document-version="0.22.0"
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
