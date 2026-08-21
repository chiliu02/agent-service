# Container image for agent-service, OpenAI Codex implementation.
#
# The container is the security boundary this service's design assumes -- the
# same posture the Claude build documents, arrived at from a different SDK.
# Codex additionally applies its own kernel-level sandbox per turn
# (`options.py` maps `permission_mode` onto it), so the boundary here is
# belt AND braces rather than the only line (CX-01, CX-02).
#
# **Same base digest as `impl/claude-python/Dockerfile`, deliberately.** Nothing
# about Codex asks for a different one, and two implementations drifting onto
# two Debian snapshots would make "is this the base or the build?" a question
# somebody has to answer at 2am. Resolved 2026-07-28 to Python 3.13.14, Debian
# trixie, glibc 2.41, git 2.47.3, curl 8.14.1. Pinned by digest because a
# floating tag makes the image non-reproducible and would let the base's
# glibc/git versions drift with no change to this file. The apt packages below
# are deliberately NOT pinned -- a rebuild should pick up Debian security
# updates; the base digest is what gets bumped on purpose.
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# ---------------------------------------------------------------------------
# System packages. Ordered first because they change least often; every layer
# below this one is cheaper to rebuild than the dependency layer that unpacks a
# 128 MB wheel.
#
#   git             the agent's git commands; nothing else provides it
#   ca-certificates TLS to the OpenAI API
#   curl            the compose healthcheck runs `curl` inside the container;
#                   there is no other HTTP client in this image
#
# **`ripgrep` is NOT installed, and that is the one difference from the Claude
# build's list.** The Codex runtime ships its own `rg` in `codex-path/` and
# `client.py` prepends that directory to the subprocess `PATH` (read from the
# installed SDK: `_installed_codex_path_dirs` / `_prepend_path_dirs`). Adding
# Debian's would put a second, older copy earlier or later on `PATH` depending
# on ordering, which is a difference nobody would think to look for. The guard
# below asserts the bundled one shipped.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Git behaviour for bind-mounted repos, at *system* scope so it applies to
# whatever HOME the container ends up running with, and to any mounted repo.
#
#   safe.directory '*'  bind-mounted files carry host ownership metadata
#                       (/workspace is uid=0, the service is uid=1000), and git
#                       otherwise refuses every command with "detected dubious
#                       ownership in repository at '/workspace'", exit 128.
#                       Measured by the Claude build, which removed it and
#                       reproduced that; the mechanism is the mount, not the SDK.
#                       '*' and not '/workspace': a nested repo (submodule,
#                       vendored checkout, a `git init` the agent makes) is a
#                       separate path and the tighter form misses it.
#
# This is the ONLY git setting baked in, and it is baked because it is
# host-independent. `core.autocrlf` and `core.filemode` are host-dependent AND
# would lose to the mounted repo's own `.git/config`, so they travel as
# GIT_CONFIG_KEY_n/VALUE_n from compose.yaml, which git reads after all config
# files. See compose.yaml.
RUN git config --system --add safe.directory '*'

# uv is pinned (`:latest` would make the image non-reproducible; the lock was
# produced by this version, cf. uv_build>=0.11.27,<0.12.0 in pyproject.toml) and
# is *bind-mounted* into the two RUN steps below rather than COPYed in. uv is a
# 63 MB static binary and is not needed at run time; COPYing it would add that
# to the final image for no runtime benefit, and deleting it in a later layer
# cannot reclaim it.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependencies, in their own layer.
#
# Only the manifest and the lock are copied here, and the project itself is
# deliberately NOT installed (`--no-install-project`). That is the whole point
# of the split: editing anything under src/ must not invalidate this layer,
# because rebuilding it means re-downloading a 128 MB wheel.
#
# The build context is `impl/` (see compose.yaml), so these are prefixed.
#
# `common/agent-spec` is copied BEFORE the dependency sync because
# `pyproject.toml` names it as a path dependency: uv resolves it at sync time
# and fails outright if the directory is absent.
# DESTINATION IS `/common`, NOT `/app/common`. `pyproject.toml` names the
# dependency as `../common/agent-spec`, and WORKDIR is `/app` -- so uv resolves
# it to `/common/agent-spec` and the path must match on both sides. Getting this
# wrong fails the build with "Distribution not found at:
# file:///common/agent-spec", which is at least a loud failure.
# ---------------------------------------------------------------------------
COPY common/agent-spec/ /common/agent-spec/
COPY codex-python/pyproject.toml codex-python/uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# GUARD: fail the build if the Codex runtime did not ship.
#
# `openai-codex` is a pure-Python wheel; the runtime lives in a SEPARATE
# platform-specific distribution, `openai-codex-cli-bin`, which publishes eight
# wheels and **no sdist**. That is a better failure mode than the Claude build's
# trap -- there is nothing to silently build from source, so a missing platform
# tag fails resolution rather than producing an empty install -- and it is not
# the only way this can go wrong: the lock currently carries manylinux_2_17 and
# musllinux_1_1 for x86_64 and aarch64 only, so `--platform linux/arm/v7` has no
# wheel, and any SDK bump whose lock momentarily lacks a matching tag is the
# same case.
#
# **The path is asked of the SDK's own resolver, never hardcoded.**
# `codex_cli_bin.bundled_codex_path()` is exactly what `client.py` calls at
# session open, so this guard cannot drift from what the service will actually
# execute -- and a Python minor-version bump cannot silently turn it into a
# no-op the way a hardcoded site-packages path would.
#
# Three checks, and each one has a failure it alone catches:
#   test -x       a file that is not executable -- what a mis-repacked wheel
#                 leaves behind
#   size          the resolver guards only on `is_file()`, so a 0-byte or
#                 truncated download passes it
#   --version     the binary actually runs on THIS libc. That is the check the
#                 other two cannot make, and glibc-vs-musl is precisely how the
#                 Claude build's equivalent trap presented.
#
# `rg` is checked because the service never sets `codex_bin`, so
# `_installed_codex_path_dirs()` will put `codex-path/` on the agent's PATH and
# the agent's search tool comes from there. A missing `rg` would surface as the
# agent reporting that it cannot find anything, which reads as a model problem.
#
# `--version` is a local exec: no API call, no cost, no credential. It sits
# inside the cached dependency region, so it costs nothing on a source rebuild.
# ---------------------------------------------------------------------------
RUN B="$(/app/.venv/bin/python -c 'import codex_cli_bin; print(codex_cli_bin.bundled_codex_path())')" \
    && P="$(/app/.venv/bin/python -c 'import codex_cli_bin; print(codex_cli_bin.bundled_path_dir())')" \
    && echo "bundled codex: $B size=$(stat -c %s "$B"); path dir: $P" \
    && test -x "$B" \
    && [ "$(stat -c %s "$B")" -gt 100000000 ] \
    && test -x "$P/rg" \
    && "$B" --version

# The source, and the project install on top of it.
COPY codex-python/src/ ./src/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run the installed console scripts directly rather than through `uv run`: uv
# would re-check the environment on every start (needing write access to /app as
# a non-root user) and would sit between PID 1 and uvicorn.
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Non-root, and two writable directories.
#
# The chmod drops the one world-writable file in the image: uv leaves
# /app/.venv/.lock at 0666. Nothing reads it at run time, but the whole point of
# a root-owned /app is that the service cannot modify its own installation.
#
# `/workspace` exists in the image AND is meant to be bind-mounted over. Its
# existence is exactly why the mounts gate checks `/proc` mount state rather
# than `exists()` -- see config.verify_mounts.
#
# `/codex-home` is this build's own, and has no equivalent in the Claude image.
# It is where the app-server keeps SQLite state (WAL mode), an installation id,
# its auth store and 65 unpacked skill files. Two things follow, both measured
# and written up in CX-34:
#   * it MUST exist and be writable, or the app-server exits immediately and
#     the SDK reports it as stdout closing -- an error naming nothing;
#   * it is set to a path CHOSEN here rather than left to default under $HOME,
#     because a path chosen on purpose can be mounted and one inherited from
#     $HOME gets mounted by accident or not at all.
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 agent \
    && find /app/.venv -perm -0002 -exec chmod o-w {} + \
    && mkdir -p /workspace /codex-home \
    && chown agent:agent /workspace /codex-home
USER agent
ENV HOME=/home/agent

ENV AGENT_SERVICE_WORKSPACE_DIR=/workspace \
    AGENT_SERVICE_CODEX_HOME=/codex-home
# **The two artifacts this image was built against, readable WITHOUT running
# it** (CX-58). `docker inspect` answers from image metadata, so it works on
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
LABEL org.opencontainers.image.title="agent-service-codex-python"
LABEL com.npf.agent-service.impl="codex-python"
LABEL com.npf.agent-service.document-version="0.19.0"
LABEL com.npf.agent-service.schema-revision="d3f9a0c15e27"

EXPOSE 8000

# exec form, so uvicorn is PID 1 and receives SIGTERM directly. Shell form would
# put /bin/sh at PID 1, which swallows the signal and skips the lifespan
# shutdown where close_all() stops every app-server subprocess.
#
# `--host 0.0.0.0` is AS-28 and is not a default to tidy away: a consumer
# reaches this container by name on a Docker network, and loopback would delete
# that route. `config.LISTEN_ADDRESS`/`LISTEN_PORT` publish these same two
# values as `listen` in the published document's PrebootSpec component, and
# `spec/conformance/test_boot_gates.py` reads the running container's
# /proc/net/tcp to check the socket agrees with what was published.
#
# --workers 1 is mandatory, not stylistic: SessionRegistry holds live
# CodexSession objects -- each owning an app-server subprocess -- in process
# memory, so a second worker would route a follow-up turn to a process that has
# never heard of the session.
CMD ["uvicorn", "agent_service.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "30"]
