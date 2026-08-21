# Container image for agent-service (Plan 4, Task 2).
#
# The container is the security boundary this service's design assumes: the
# agent runs with `Bash` enabled and `permission_enforcement="none"`, so the
# only thing standing between it and the host is that the process cannot reach
# anything that was not mounted (CP-081).

# glibc, not musl — and the reason is not the one CP-083 first gave.
#
# The Agent SDK ships its native Claude Code binary (262.3 MiB, ELF x86-64,
# dynamically linked against glibc >= 2.17) inside a `manylinux_2_17_x86_64`
# wheel. uv.lock pins no `musllinux` wheel, so on Alpine uv silently falls back
# to the sdist and builds it — successfully, exit 0, no warning — producing an
# install whose `_bundled/` directory is EMPTY. Nothing fails to execute; there
# is nothing to execute. The service dies at the first turn with
# CLINotFoundError. Measured on python:3.13-alpine (CP-083). The guard after the
# dependency sync below turns that silent failure into a build failure.
#
# Pinned by digest, for the same reason uv is: a floating tag makes the image
# non-reproducible, and here it would also let the base's glibc/git/ripgrep
# versions drift without any change to this file. Resolved 2026-07-28 to
# Python 3.13.14, Debian trixie, glibc 2.41, git 2.47.3, ripgrep 14.1.1,
# curl 8.14.1. The apt packages below are deliberately NOT pinned — a rebuild
# should pick up Debian security updates; the base digest is what gets bumped
# on purpose.
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# ---------------------------------------------------------------------------
# System packages. Ordered first because they change least often; every layer
# below this one is cheaper to rebuild than the 262 MiB dependency layer.
#
#   git             the agent's git commands; nothing else provides it
#   ripgrep         the SDK's `Grep` tool is built on it
#   ca-certificates TLS to api.anthropic.com
#   curl            the compose healthcheck (Task 3) runs `curl` inside the
#                   container; there is no other HTTP client in this image
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
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
#                       LOAD-BEARING -- Task 5 removed it and reproduced that.
#                       '*' and not '/workspace': a nested repo (submodule,
#                       vendored checkout, a `git init` the agent makes) is a
#                       separate path and the tighter form misses it.
#
# This is the ONLY git setting baked in, and it is baked because it is
# host-independent -- every bind mount has synthesized ownership. `core.filemode
# false` USED TO BE HERE and was removed: it is host-dependent AND system scope
# is the wrong scope for it. `.git/config` is inside the mount and REPO SCOPE
# WINS, so on a Git-for-Windows checkout the baked value was shadowed by an
# identical repo-scope one (doing nothing), and on a Linux-cloned repo it was
# shadowed by `filemode = true` (doing nothing, wrongly). It now travels as
# GIT_CONFIG_KEY_1/VALUE_1 from compose.yaml, which git reads after all config
# files and which therefore actually wins. Same for core.autocrlf. See
# compose.yaml and CP-082.
RUN git config --system --add safe.directory '*'

# uv is pinned (`:latest` would make the image non-reproducible; the lock was
# produced by this version, cf. uv_build>=0.11.27,<0.12.0 in pyproject.toml) and
# is *bind-mounted* into the two RUN steps below rather than COPYed in. uv is a
# 63 MB static binary and is not needed at run time; COPYing it added a 63.1 MB
# layer to the final image for no runtime benefit, and deleting it in a later
# layer cannot reclaim that. Measured: 820 MB -> 730 MB, no caching cost.
#
# Those are PRE-BYTECODE figures -- they were taken before `UV_COMPILE_BYTECODE=1`
# below, which trades +23 MB for ~1.0 s off every container start. The image as
# it stands today is 753 MB (730 + 23); the ~90 MB this bind-mount saves is
# unaffected either way. Full table: CP-083.
#
# THAT 753 MB IS NOT THE IMAGE. It is Docker Desktop's containerd image store
# reporting DISK USAGE, which counts the unpacked snapshot AND the compressed
# blobs it was unpacked from:
#
#     570 MB  sum of `docker history` layer sizes (`du -sm /` agrees: 540 MiB)
#   + 182 MB  compressed blobs -- also what `docker image inspect .Size` prints,
#             and what actually crosses the wire on a push or pull
#   = 753 MB  `docker images` DISK USAGE
#
# So: 182 MB is the registry/transfer cost, 570 MB is what the container's
# filesystem occupies, and 753 MB is a local storage artefact that would not
# exist under the classic overlay2 image store. Every figure above and in
# CP-083 is the DISK USAGE number, so the deltas (820 -> 730 -> 753)
# are internally consistent -- just do not quote 753 MB as "the image size" to
# anyone sizing a registry or a pull.
#
# Of the 570 MB, 263 is the SDK's bundled `claude` binary and 112 is the apt
# layer below (git 49 MB, and the 49 MB of Perl git depends on). The base is
# 178 MB. Your own Python dependencies are ~40 MB. There is no meaningful
# trimming available here: measured 2026-07-29, left as is deliberately.
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
# because rebuilding it means re-downloading an 85 MB wheel that unpacks to
# 262 MiB. Measured: cold build 43 s, source-only rebuild 3 s.
# ---------------------------------------------------------------------------
# The build context is `impl/` (see compose.yaml), so these are prefixed.
#
# `common/agent-spec` is copied BEFORE the dependency sync because
# `pyproject.toml` names it as a path dependency: uv resolves it at sync
# time and fails outright if the directory is absent. It is tiny and changes
# only when the specification does, so it costs this layer nothing in
# practice.
# DESTINATION IS `/common`, NOT `/app/common`. `pyproject.toml` names the
# dependency as `../common/agent-spec`, and WORKDIR is `/app` -- so uv
# resolves it to `/common/agent-spec` and the path must match on both sides.
# Getting this wrong fails the build with
# "Distribution not found at: file:///common/agent-spec", which is at least
# a loud failure rather than a silent one.
COPY common/agent-spec/ /common/agent-spec/
COPY claude-python/pyproject.toml claude-python/uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# GUARD: fail the build if the SDK's native binary did not ship.
#
# This is the check that would have caught the Alpine trap described at the top,
# and it is not hypothetical or edit-triggered: `docker buildx build --platform
# linux/arm/v7` takes the same sdist path (uv.lock has manylinux_2_17_aarch64
# but nothing for armv7) and would otherwise produce a broken image with no
# warning. So would any SDK bump whose lock momentarily lacks a matching tag.
#
# Size and exec-bit are both checked because the SDK's own _find_bundled_cli()
# guards only on `exists() and is_file()` — it would accept a 0-byte file. The
# path is derived from the installed package rather than hardcoded so that a
# Python minor-version bump cannot silently turn this into a no-op.
#
# `--version` is a local exec: no API call, no cost. ~2 s, and it sits inside
# the cached dependency region, so it costs 0 s on a source-only rebuild.
# ---------------------------------------------------------------------------
RUN B="$(/app/.venv/bin/python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" \
    && test -x "$B" \
    && [ "$(stat -c %s "$B")" -gt 200000000 ] \
    && echo "bundled claude: $B size=$(stat -c %s "$B")" \
    && "$B" --version

# The source, and the project install on top of it. There is no README.md to
# copy since 2026-08-11: it was split into docs/claude-python-{operations,guide}.md
# and `pyproject.toml`'s `readme` field went with it, so the build backend no
# longer reads a file from this directory for package metadata.
COPY claude-python/src/ ./src/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.27,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run the installed console scripts directly rather than through `uv run`: uv
# would re-check the environment on every start (needing write access to /app
# as a non-root user) and would sit between PID 1 and uvicorn.
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Non-root. HOME must be writable: the bundled Claude Code binary and the SDK's
# session storage both write under it.
# ---------------------------------------------------------------------------
#
# The chmod drops the one world-writable file in the image: uv leaves
# /app/.venv/.lock at 0666. Nothing reads it at run time, but the whole point of
# a root-owned /app is that the service cannot modify its own installation.
RUN useradd --create-home --uid 1000 agent \
    && find /app/.venv -perm -0002 -exec chmod o-w {} + \
    && mkdir -p /workspace \
    && chown agent:agent /workspace
USER agent
ENV HOME=/home/agent

ENV AGENT_SERVICE_WORKSPACE_DIR=/workspace
# **The two artifacts this image was built against, readable WITHOUT running
# it** (CP-147). `docker inspect` answers from image metadata, so it works on
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
LABEL org.opencontainers.image.title="agent-service-claude-python"
LABEL com.npf.agent-service.impl="claude-python"
LABEL com.npf.agent-service.document-version="0.20.0-snapshot"
LABEL com.npf.agent-service.schema-revision="d3f9a0c15e27"

EXPOSE 8000

# exec form, so uvicorn is PID 1 and receives SIGTERM directly. Shell form would
# put /bin/sh at PID 1, which swallows the signal and skips the lifespan
# shutdown where close_all() disconnects live sessions. Task 4 tests this.
#
# --workers 1 is mandatory, not stylistic: SessionRegistry holds live
# ClaudeSDKClient objects in process memory, so a second worker would route a
# follow-up turn to a process that has never heard of the session.
CMD ["uvicorn", "agent_service.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "30"]
