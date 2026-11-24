"""The gateway map and the MCP grant, both built for Agent Harness.

**Every test here covers a defect the unit suite did not catch the first time.**
The features were written, 129 tests passed, and three things were still broken:
compose never forwarded the gateway variable, `check_provider` ignored the
deployment's default model, and the MCP proxy tool was never granted. Two of the
three are reachable from here and are pinned below; the third is a compose file
and belongs to the container tier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.config import (
    GATEWAY_MAP_SOURCE,
    BootRefused,
    Settings,
    _gateways,
)
from agent_service.mcp import (
    SERVER_NAME_PATTERN,
    McpUnsupported,
    adapter_config,
    validate,
)
from agent_service.pi import PiRunner
from agent_service.registry import ProviderNotFronted, check_provider, provider_of
from agent_service.spec import specification


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(workspace_dir=tmp_path, agent_dir_root=tmp_path / "a",
                    session_store=tmp_path / "s", pi_binary=Path("pi"), **kwargs)


def _runner(tmp_path: Path, **kwargs) -> PiRunner:
    return PiRunner(binary=Path("pi"), workspace=tmp_path,
                    agent_dir=tmp_path / "agent",
                    session_dir=tmp_path / "sessions", **kwargs)


# --- the gateway map --------------------------------------------------------


def test_a_malformed_gateway_map_refuses_to_BOOT() -> None:
    """`PI-44`: falling back to "unfronted" would send credentials to the vendor.

    An operator who set this expects every turn behind their gateway, so the
    failure has to be loud and at boot rather than quiet and per turn.
    """
    with pytest.raises(BootRefused):
        _gateways("{not json")
    with pytest.raises(BootRefused):
        _gateways('["a list, not an object"]')
    with pytest.raises(BootRefused):
        _gateways('{"anthropic": {"headers": {}}}')  # no base_url


def test_an_empty_map_means_unfronted_and_has_no_opinion(tmp_path: Path) -> None:
    """No map, no refusals: an unfronted deployment is a real deployment."""
    assert _gateways(None) == {}
    check_provider("openai/gpt-5-nano", _settings(tmp_path), {})


def test_the_PUBLISHED_variable_is_the_one_actually_read(monkeypatch) -> None:
    """`PI-56`: a name published pre-boot that nothing reads is worse than none.

    The whole value of the field is that a consumer sets this variable before
    any container exists and never gets to ask whether it landed. So the name in
    the document and the name `Settings.from_env` pops are pinned to each other
    here rather than being kept in step by hand.
    """
    published = GATEWAY_MAP_SOURCE["variable"]
    monkeypatch.setenv(published, '{"anthropic": {"base_url": "https://gw"}}')
    assert Settings.from_env().provider_gateways == {
        "anthropic": {"base_url": "https://gw", "headers": {}}
    }
    assert specification()["gateway_map_source"] == GATEWAY_MAP_SOURCE


def test_the_published_provider_ids_are_what_check_provider_COMPARES() -> None:
    """`PI-57`: a map keyed on the wrong vocabulary refuses every turn.

    Nothing validates a key, so the only thing standing between a consumer and a
    container that boots and then refuses everything is this published list
    being the same strings `provider_of` produces. `google` is the one that
    bites -- the credential variable is `GEMINI_API_KEY` and the id is not
    `gemini`.
    """
    ids = GATEWAY_MAP_SOURCE["provider_ids"]
    assert "gemini" not in ids and "google" in ids
    gateways = {name: {"base_url": "https://gw"} for name in ids}
    for name in ids:
        assert provider_of(f"{name}/some-model", None) == name
        check_provider(f"{name}/some-model", _settings(Path(".")), gateways)


def test_the_proxy_and_the_map_are_BOTH_published_and_differ() -> None:
    """`PI-56`: `endpoint_source` did not move, and it should not have.

    The proxy is still the one variable that redirects every turn. What it
    cannot be is a gateway, which is why there are two fields and not one.
    """
    published = specification()
    assert published["endpoint_source"] == "HTTPS_PROXY"
    assert published["gateway_map_source"]["variable"] != published["endpoint_source"]
    assert published["gateway_map_source"]["unconfigured_provider"] == "refused"
    assert published["gateway_map_source"]["agent_appends_api_suffix"] is True


def test_the_api_suffix_is_stripped_from_a_base_url() -> None:
    """`PI-42`: the agent appends its own, so a trailing slash would double it."""
    parsed = _gateways('{"a": {"base_url": "https://gw/x/"}}')
    assert parsed["a"]["base_url"] == "https://gw/x"


def test_a_provider_with_no_entry_is_refused(tmp_path: Path) -> None:
    """`PI-44`, and it is the hazard Agent Harness asked us to close.

    A gateway holding credentials for three providers of thirty must have three
    doors rather than twenty-seven holes.
    """
    with pytest.raises(ProviderNotFronted):
        check_provider("openai/gpt-5-nano", _settings(tmp_path),
                       {"anthropic": {"base_url": "https://gw"}})


def test_the_deployments_DEFAULT_MODEL_supplies_the_provider(tmp_path: Path) -> None:
    """`PI-44`: reading only the provider setting refused a fronted deployment's
    own default.

    `AGENT_SERVICE_MODEL` is `provider/id` here (`PI-10`), so the provider is
    inside it. A container configured with a qualified default and a matching
    gateway answered 400 to every request that named no model, and no unit test
    saw it because they configure a model and a gateway together.
    """
    settings = _settings(tmp_path, model="anthropic/claude-haiku-4-5")
    check_provider(None, settings, {"anthropic": {"base_url": "https://gw"}})


def test_provider_of_prefers_the_qualified_model() -> None:
    assert provider_of("anthropic/claude-haiku-4-5", "openai") == "anthropic"
    assert provider_of("gpt-5-nano", "openai") == "openai"
    assert provider_of(None, None) is None


def test_the_gateway_map_becomes_a_models_json(tmp_path: Path) -> None:
    """`PI-42`: `baseUrl` plus `headers` -- what a gateway needs to strip a
    credential and count a turn."""
    runner = _runner(tmp_path, provider_gateways={"anthropic": {
        "base_url": "https://gw/harness/anthropic",
        "headers": {"x-tenant-token": "t"},
    }})
    runner.write_config()
    written = json.loads((tmp_path / "agent" / "models.json").read_text())
    assert written == {"providers": {"anthropic": {
        "baseUrl": "https://gw/harness/anthropic",
        "headers": {"x-tenant-token": "t"},
    }}}


def test_no_gateway_writes_no_models_json(tmp_path: Path) -> None:
    """An unfronted deployment leaves the agent its own defaults."""
    _runner(tmp_path).write_config()
    assert not (tmp_path / "agent" / "models.json").exists()


# --- MCP --------------------------------------------------------------------


def test_granting_mcp_grants_the_PROXY_TOOL_by_name(tmp_path: Path) -> None:
    """`PI-48`, and forgetting it is silent.

    The adapter presents every server through one tool called `mcp`. An
    allowlist that does not name it leaves the servers registered, the adapter
    loaded, and the model unable to see any of it -- measured as a turn that
    answered helpfully that no such tool existed, exit 0, no tool events.
    """
    runner = _runner(tmp_path, allowed_tools=("read", "write"),
                     mcp_adapter_path=Path("/opt/pi-mcp-adapter"),
                     mcp_servers={"srv": {"command": "node", "args": ["s.js"]}})
    argv = runner.argv("hi", sdk_session_id=None, resume=None)
    assert "mcp" in argv[argv.index("--tools") + 1].split(",")


def test_no_servers_means_no_mcp_tool_and_no_extension(tmp_path: Path) -> None:
    """The grant is whole-or-nothing in both directions."""
    argv = _runner(tmp_path, allowed_tools=("read",),
                   mcp_adapter_path=Path("/opt/pi-mcp-adapter"),
                   ).argv("hi", sdk_session_id=None, resume=None)
    assert "mcp" not in argv[argv.index("--tools") + 1].split(",")
    assert "--extension" not in argv


def test_the_extension_is_named_by_PATH_so_no_extensions_can_stay(
    tmp_path: Path,
) -> None:
    """`PI-43`: the agent honours `-e` even under `--no-extensions`.

    That is what lets MCP load while the caller's mounted workspace stays locked
    out -- the reproducibility guarantee `PI-19` rests on.
    """
    argv = _runner(tmp_path, allowed_tools=("read",),
                   mcp_adapter_path=Path("/opt/pi-mcp-adapter"),
                   mcp_servers={"srv": {"command": "node"}},
                   ).argv("hi", sdk_session_id=None, resume=None)
    assert "--no-extensions" in argv
    assert argv[argv.index("--extension") + 1] == str(Path("/opt/pi-mcp-adapter"))
    assert argv[argv.index("--mcp-config") + 1].endswith("mcp.json")


def test_a_pydantic_server_survives_being_written(tmp_path: Path) -> None:
    """The 500 the unit suite missed: the registry holds models, not dicts.

    `json.dumps` on an `McpStdioServer` raised `TypeError` at the first real MCP
    turn. Every test passed because they all built sessions from plain dicts, so
    this one uses an object carrying `model_dump` on purpose.
    """
    class _Server:
        def model_dump(self, **_: object) -> dict[str, object]:
            return {"command": "node", "args": ["s.js"], "type": "stdio"}

    runner = _runner(tmp_path, mcp_adapter_path=Path("/opt/x"),
                     mcp_servers={"srv": _Server()})
    runner.write_config()
    written = json.loads((tmp_path / "agent" / "mcp.json").read_text())
    # `type` is dropped: the adapter keys on shape, and a stray key would be one
    # more dialect to keep in step with the first.
    assert written == {"mcpServers": {"srv": {"command": "node", "args": ["s.js"]}}}


def test_an_underscore_in_a_server_name_is_refused() -> None:
    """`PI-45`: the proxy addresses a tool as `<server>_<tool>`, so `a_b_c` is
    ambiguous. The published pattern IS this check rather than a copy of it."""
    with pytest.raises(McpUnsupported):
        validate({"my_server": {"command": "node"}})
    validate({"my-server": {"command": "node"}})
    assert SERVER_NAME_PATTERN.startswith("^")


def test_an_unknown_transport_is_refused_per_server() -> None:
    """Per SERVER, not per field: the field is supported and one entry is not."""
    with pytest.raises(McpUnsupported):
        validate({"srv": {"socket": "/tmp/x"}})
    validate({"srv": {"command": "node"}})
    validate({"srv": {"url": "https://example/mcp"}})


def test_adapter_config_passes_the_shape_through() -> None:
    """Not translated: the adapter's schema is the one `McpServer` already carries."""
    assert adapter_config({"a": {"url": "https://x", "headers": {"k": "v"}}}) == {
        "a": {"url": "https://x", "headers": {"k": "v"}}
    }


def test_the_published_agent_home_is_internally_consistent() -> None:
    """A `per_session_root` needs a seed; a `service` home must not have one.

    The pair is the whole content of the field: a consumer that reads `scope`
    and finds no lever, or finds one it cannot need, has been told something
    that does not add up. Pinned per build because the value is per build --
    nothing enumerates across them, by the same argument that made every other
    pre-boot value a `const`.
    """
    home = specification()["agent_home"]
    assert home["variable"] == "AGENT_SERVICE_AGENT_HOME"
    assert home["default_path"].startswith("/")
    assert home["scope"] in {"service", "per_session_root"}
    assert (home["seed_source"] is not None) == (home["scope"] == "per_session_root")
    conversations = home["conversations"]
    if conversations["in_home"]:
        assert conversations["path"]
    else:
        assert conversations["variable"] and conversations["default_path"]
