"""An interrupt and a close stop every process the session's tools started (CX-73).

No app-server: the turn is a stand-in, and `stop_tagged` is recorded rather
than run, so this needs no Linux and no agent.
"""

from __future__ import annotations

import pytest

from agent_service import sessions as sessions_module
from agent_service.processes import TAG_ENV_VAR
from agent_service.sessions import CodexSession

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Turn:
    def __init__(self) -> None:
        self.interrupts = 0

    async def interrupt(self) -> None:
        self.interrupts += 1


@pytest.fixture
def sweeps(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, frozenset[int]]]:
    recorded: list[tuple[str, frozenset[int]]] = []
    monkeypatch.setattr(
        sessions_module, "stop_tagged",
        lambda tag, *, spare_sessions=frozenset(): recorded.append((tag, spare_sessions)) or 0,
    )
    return recorded


def test_every_session_tags_its_app_server_and_no_two_share_a_tag(tmp_path) -> None:
    a = CodexSession(cwd=str(tmp_path / "ws"), codex_home=str(tmp_path / "home"))
    b = CodexSession(cwd=str(tmp_path / "ws"))
    assert a._config.env[TAG_ENV_VAR] == a._process_tag
    assert b._config.env[TAG_ENV_VAR] == b._process_tag
    assert a._process_tag != b._process_tag
    # The home still reaches the app-server beside the tag.
    assert a._config.env["CODEX_HOME"]


async def test_an_interrupt_stops_the_tools_and_spares_the_app_server(tmp_path, sweeps) -> None:
    session = CodexSession(cwd=str(tmp_path / "ws"))
    session._agent_sessions = frozenset({7})
    session._turn = turn = _Turn()
    assert await session.interrupt() is True
    assert turn.interrupts == 1
    assert sweeps == [(session._process_tag, frozenset({7}))]


async def test_no_turn_stops_nothing(tmp_path, sweeps) -> None:
    session = CodexSession(cwd=str(tmp_path / "ws"))
    assert await session.interrupt() is False
    assert sweeps == []


async def test_a_close_stops_every_process_of_the_session(tmp_path, sweeps) -> None:
    session = CodexSession(cwd=str(tmp_path / "ws"))
    await session.close()
    assert sweeps == [(session._process_tag, frozenset())]
