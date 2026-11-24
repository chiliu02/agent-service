"""Uvicorn entrypoint: `uv run uvicorn agent_service.main:app`."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from agent_service.api import create_app
from agent_service.config import get_settings

# Must run before create_app(): the documented quick start (README.md) has
# users `cp .env.example .env` and set ANTHROPIC_API_KEY there. Nothing else
# in this codebase loads .env -- Settings' env_prefix="AGENT_SERVICE_" means
# pydantic-settings' own .env support never sees an unprefixed
# ANTHROPIC_API_KEY (extra="ignore" swallows it silently), and `uv run` does
# not load .env on its own. Without this call, credentials_configured()
# reads only os.environ, .env's key never reaches it, and every run fails
# (I2, final review). override=False (the default) is explicit here: a real
# key already exported in the shell environment must win over whatever the
# gitignored .env happens to contain.
load_dotenv(override=False)


def configure_logging(level: str) -> None:
    """Give this service's own log records somewhere to go.

    WHY THIS EXISTS. Nothing under `src/` configured logging at all, and
    neither does uvicorn on our behalf: uvicorn's `LOGGING_CONFIG` names only
    the `uvicorn*` loggers and leaves the root logger without a handler. Every
    record from `agent_service.*` therefore propagated to an unhandled root and
    met Python's LAST-RESORT handler, which emits WARNING and above to stderr
    and DROPS THE REST. Task 6 measured the consequence in a container: a
    shutdown whose `close_all: swept N session(s)...` summary -- added
    deliberately, so that a clean sweep and a sweep that never ran would stop
    being indistinguishable -- produced ZERO matches in `docker compose logs`.
    The reaper's `closed N idle session(s)` line was invisible for the same
    reason. Both are INFO.

    WHY basicConfig AND NOT dictConfig. `basicConfig` adds a root handler only
    when root has none, so it defers to any configuration that already exists
    instead of replacing it; `logging.config.dictConfig` would close every
    handler in the process on the way past, including uvicorn's. Nothing here
    touches the `uvicorn` logger, which carries `propagate=False`, so uvicorn's
    own lines pass through its handler exactly once and are NOT duplicated by
    ours. stderr for the same reason uvicorn's default handler uses it: one
    stream, so the two sources interleave in the order they were written.

    WHY THE ENTRYPOINT AND NOT `create_app`. Process-wide logging config is the
    entrypoint's business -- the same place `load_dotenv` already sits. The
    test suite builds the app directly with `create_app(...)`, dozens of times
    per run, and configuring logging in there would reconfigure the root logger
    under pytest's own capture on every one of them.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


# After load_dotenv, so AGENT_SERVICE_LOG_LEVEL may live in `.env` alongside
# the credential; before create_app, so anything the app logs while being
# built is already going somewhere.
configure_logging(get_settings().log_level)

app = create_app()
