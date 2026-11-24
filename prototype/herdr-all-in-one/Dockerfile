# PROTOTYPE, not a build: one image holding Herdr and four agent CLIs, on top
# of Agent Harness's toolchain image, with a thin HTTP shim that answers the
# calls Harness makes today using only Herdr's JSON socket API. Live output is
# watched by attaching a Herdr client over SSH instead of an SSE stream.
#
# Not in ci.py, not in images.py, never tagged for release.
ARG TOOLCHAIN=localhost:5000/agent-harness-toolchain:0.1.0
FROM ${TOOLCHAIN}

USER root

# sshd for the remote Herdr client; tini for PID 1; ripgrep for Claude's Grep.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server tini ripgrep \
 && rm -rf /var/lib/apt/lists/* \
 # uid 1000 is `ubuntu` in this base. A '!' password makes sshd treat the
 # account as locked even for key auth; '*' means "no password, not locked".
 && usermod -p '*' ubuntu \
 && mkdir -p /work && chown 1000:1000 /work

# --- Herdr, pinned by sha256 (the value https://herdr.dev/latest.json gives) ---
ARG HERDR_VERSION=0.9.5
ARG HERDR_SHA256=14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d
RUN curl -fsSL -o /usr/local/bin/herdr \
      "https://github.com/herdrdev/herdr/releases/download/v${HERDR_VERSION}/herdr-linux-x86_64" \
 && echo "${HERDR_SHA256}  /usr/local/bin/herdr" | sha256sum -c - \
 && chmod 755 /usr/local/bin/herdr \
 && herdr --version

# --- the four CLIs, at the versions the placement probe measured ---------------
ARG CLAUDE_CODE_VERSION=2.1.325
ARG CODEX_VERSION=0.146.0
ARG GEMINI_CLI_VERSION=0.66.0
ARG PI_VERSION=1.4.0
RUN npm install -g \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@openai/codex@${CODEX_VERSION}" \
      "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
 && npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
 && npm cache clean --force \
 && claude --version && codex --version && gemini --version && pi --version

# psycopg for writing into agent-service's database schema, in a venv of its own
# so the toolchain's system Python is untouched.
ARG PSYCOPG_VERSION=3.2.9
RUN uv venv /opt/proto/venv --python /usr/bin/python3  && uv pip install --python /opt/proto/venv/bin/python "psycopg[binary]==${PSYCOPG_VERSION}"  && /opt/proto/venv/bin/python -c "import psycopg; print('psycopg', psycopg.__version__)"

COPY --chmod=755 entrypoint.sh /usr/local/bin/proto-entrypoint
COPY shim.py usage.py store.py stub_llm.py gemini_session_hook.py openapi.json /opt/proto/

USER 1000
ENV HOME=/home/ubuntu \
    XDG_CONFIG_HOME=/home/ubuntu/.config \
    CLAUDE_CONFIG_DIR=/home/ubuntu/.claude \
    CODEX_HOME=/home/ubuntu/.codex \
    PI_CODING_AGENT_DIR=/home/ubuntu/.pi/agent \
    GEMINI_CLI_HOME=/home/ubuntu \
    GEMINI_CLI_TRUST_WORKSPACE=true \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    DISABLE_AUTOUPDATER=1

# Herdr's integrations report each pane's agent session to the socket. They write
# into the agents' own homes, so they are installed here, before any pane exists.
RUN mkdir -p "$CLAUDE_CONFIG_DIR" "$CODEX_HOME" "$PI_CODING_AGENT_DIR" "$HOME/.gemini" \
 && (herdr integration install claude || echo "integration claude: failed") \
 && (herdr integration install codex  || echo "integration codex: failed") \
 && (herdr integration install pi     || echo "integration pi: failed")

EXPOSE 2222 8080
WORKDIR /work
ENTRYPOINT ["tini", "--", "proto-entrypoint"]
