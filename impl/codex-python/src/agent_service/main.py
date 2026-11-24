"""Uvicorn entrypoint: `uv run uvicorn agent_service.main:app`."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from agent_service.api import create_app
from agent_service.config import Settings

# Before create_app(), because the boot gate reads os.environ and `uv run` does
# not load `.env` on its own. `override=False` is explicit: a key already
# exported in the shell must win over whatever the gitignored `.env` holds.
load_dotenv(override=False)


def configure_logging(level: str) -> None:
    """Give this service's own log records somewhere to go.

    **WHY THIS EXISTS, and it is measured rather than inherited.** Nothing under
    `src/` configured logging at all and uvicorn does not do it on anyone's
    behalf: its `LOGGING_CONFIG` names only the `uvicorn*` loggers and leaves the
    root logger without a handler. Every record from `agent_service.*` therefore
    reached Python's LAST-RESORT handler, which emits WARNING and above to
    stderr and **drops the rest**. Measured in a container on 2026-08-10: the
    boot's capacity warning appeared and `close_all`'s one-line summary -- added
    the same day so that a clean sweep and a sweep that never ran would stop
    being indistinguishable -- produced nothing at all. The reaper's line was
    invisible for the same reason. Both are INFO.

    **`basicConfig` and not `dictConfig`.** `basicConfig` adds a root handler
    only when root has none, so it defers to any configuration that already
    exists; `logging.config.dictConfig` would close every handler in the process
    on its way past, including uvicorn's. Nothing here touches the `uvicorn`
    logger, which carries `propagate=False`, so its lines pass through its own
    handler exactly once and are not duplicated. stderr for the reason uvicorn
    uses it: one stream, so the two sources interleave in written order.

    **The entrypoint and not `create_app()`.** Process-wide logging config is
    the entrypoint's business -- the same place `load_dotenv` already sits. The
    test suite builds apps directly, many times per run, and configuring logging
    in there would reconfigure the root logger under pytest's capture on every
    one of them.

    (CX-47)
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


# After load_dotenv, so AGENT_SERVICE_LOG_LEVEL may live in `.env` beside the
# credential; before create_app, so anything logged while the app is built is
# already going somewhere.
#
# **RESOLVED ONCE AND PASSED IN, and that is not a style choice.**
# `Settings.from_env()` POPS `AGENT_SERVICE_DATABASE_URL` out of `os.environ` --
# a security requirement, since the agent inherits this process's environment
# and can run shell commands. So the second call in a process sees no database
# URL and returns `database_url=None`. Reading the log level from one `Settings`
# and letting `create_app()` build its own would therefore have switched
# persistence off in production while every test, which passes settings
# explicitly, went on passing.
_settings = Settings.from_env()
configure_logging(_settings.log_level)

app = create_app(_settings)
