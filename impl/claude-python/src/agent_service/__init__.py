"""Agent Service: the Claude Agent SDK behind a FastAPI/OpenAPI interface.

Deliberately empty of runtime code. Importing this package must not pull in
FastAPI, uvicorn or claude_agent_sdk -- `tests/test_errors.py` imports
individual submodules in isolation to keep the import graph acyclic, and a
side-effecting package __init__ would defeat that.

The ASGI application lives in `agent_service.main:app`; run it with
`uv run uvicorn agent_service.main:app` (see README.md). There is no console
script: uvicorn's own CLI already provides --host/--port/--reload, and a
hand-rolled launcher beside it is a second way to start the service that can
silently drift from the documented one.
"""
