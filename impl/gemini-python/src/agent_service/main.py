"""Uvicorn entrypoint: `uv run uvicorn agent_service.main:app`."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from agent_service.api import create_app
from agent_service.config import Settings

# `override=False`: a real environment variable always beats a file, which is
# what makes the same image work in a container where there is no `.env` at all.
load_dotenv(override=False)


def configure_logging(level: str) -> None:
    """Give this service's own records somewhere to go.

    **Uvicorn does not do this for anyone**: its logging config names only the
    `uvicorn*` loggers and leaves the root logger without a handler, so every
    record from `agent_service.*` reaches Python's last-resort handler, which
    emits WARNING and above and drops the rest. The Codex build lost every INFO
    line it wrote for exactly this reason.

    **`basicConfig`, not `dictConfig`**: it adds a root handler only when there
    is none, so it defers to any configuration that already exists, where
    `dictConfig` would close every handler in the process including uvicorn's.

    **The entrypoint and not `create_app()`**, because process-wide logging is
    the entrypoint's business and the test suite builds apps many times per run.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


_settings = Settings.from_env()
configure_logging(_settings.log_level)
app = create_app(_settings)
