from httpx import ASGITransport, AsyncClient

from agent_spec.openapi.ordering import CANONICAL_PATHS
from agent_service.api import create_app
from agent_service.config import Settings


async def test_healthz(client, settings) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "credentials_configured" in body
    assert body["workspace_dir"] == str(settings.workspace_dir)


async def test_capabilities_reports_resolved_defaults(client) -> None:
    response = await client.get("/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["default_model"] == "claude-sonnet-5"
    # 0.19.0: objects, not strings -- this build declares what it honours.
    modes = body["permission_modes"]
    assert all({"id", "name", "description"} <= set(m) for m in modes)
    ids = [m["id"] for m in modes]
    assert "dontAsk" in ids
    # The two well-known ids, so one payload keeps working across builds.
    assert {"default", "plan"} <= set(ids)
    assert "xhigh" in body["effort_levels"]
    assert "AskUserQuestion" in body["always_disallowed_tools"]
    assert body["limits"]["max_allowed_budget_usd"] == 10.0
    assert body["sdk_version"]
    # 0.7.0: `sdk` supersedes `sdk_version`, which is deprecated and still
    # emitted. ONE source is read once in api.py, so the pair can never
    # disagree -- and if someone splits them, this is what says so.
    assert body["sdk"]["name"] == "claude-agent-sdk"
    assert body["sdk"]["version"] == body["sdk_version"]
    # 0.8.0: both published for the same reason require_credentials is --
    # a caller that provisions containers should be able to ask, not
    # discover it from a 400.
    assert body["allow_mcp_servers"] is True
    assert body["strict_mcp_config"] is True
    # Default is "none": no in-process control, container/mount is the only
    # boundary (CP-066).
    assert body["permission_enforcement"] == "none"


async def test_unsupported_options_is_empty_because_this_sdk_covers_the_surface(
    client,
) -> None:  # noqa: ANN001
    """**AS-32 (0.19.0), and empty is the interesting value.**

    The Claude Agent SDK has an equivalent for every `RunOptions` field, so
    nothing is refused on a default deployment -- and a client reading this can
    send whatever the document allows without a per-build branch. That is the
    point of publishing the list rather than leaving it to be discovered: the
    absence of a difference is itself a fact worth stating.
    """
    body = (await client.get("/v1/capabilities")).json()
    assert body["unsupported_options"] == []


async def test_forbidding_mcp_puts_it_in_unsupported_options(tmp_path) -> None:
    """The list is derived from the setting, so the two cannot disagree.

    A deployment with `allow_mcp_servers=false` refuses `mcp_servers` with a 400
    -- `options.py` has done that since 0.8.0 -- and this is what makes the
    refusal readable in advance rather than only from the error it produces.
    """
    settings = Settings(workspace_dir=tmp_path / "ws", allow_mcp_servers=False)
    transport = ASGITransport(app=create_app(settings=settings))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/v1/capabilities")).json()

    assert body["allow_mcp_servers"] is False
    # `values: None` is emitted rather than omitted, on the convention the whole
    # document follows: an absent key cannot be told apart from one a build is
    # too old to send. Null means the field is refused whatever it contains,
    # which is what a deployment forbidding MCP means.
    assert body["unsupported_options"] == [
        {"field": "mcp_servers", "types": None, "values": None}
    ]


async def test_the_published_list_and_the_refusal_agree_over_http(
    tmp_path,
) -> None:  # noqa: ANN001
    """**Through the route, not through `build_options`.**

    `test_options.py` already proves `McpServersNotAllowedError` is raised, and
    the Codex build learned the hard way what that kind of test cannot see: its
    `unsupported()` was covered six ways while nothing called it, so every field
    it named was silently dropped anyway (CP-139). What AS-32 asks is that
    a client reading the capability gets the behaviour the capability predicts,
    and only a request can show that.

    **The REAL run factory, deliberately, and it costs nothing.** A fake factory
    never reaches `build_options`, so a test using one would pass whether or not
    the refusal existed -- the same hole this test is here to close. The refusal
    is raised before the SDK client is constructed, so no CLI is spawned and no
    credential is needed; if it ever stops being raised there, this test starts
    trying to spawn one and fails loudly, which is the right failure.
    """
    settings = Settings(
        workspace_dir=tmp_path / "ws", require_credentials=False, allow_mcp_servers=False
    )
    transport = ASGITransport(app=create_app(settings=settings))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        published = (await ac.get("/v1/capabilities")).json()["unsupported_options"]
        r = await ac.post(
            "/v1/query",
            json={
                "prompt": "hi",
                "options": {"mcp_servers": {"acme": {"type": "http", "url": "https://e.com"}}},
            },
        )

    assert [entry["field"] for entry in published] == ["mcp_servers"]
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    # One URI for one condition, and the Codex build sets the same one.
    assert r.json()["type"] == "https://agent-service.invalid/problems/unsupported-options"


async def test_capabilities_reports_hook_enforcement_when_configured(tmp_path) -> None:
    custom_settings = Settings(workspace_dir=tmp_path / "ws", permission_enforcement="hook")
    app = create_app(settings=custom_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["permission_enforcement"] == "hook"


async def test_openapi_document_exposes_the_meta_routes(client) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "/healthz" in spec["paths"]
    assert "/v1/capabilities" in spec["paths"]


async def test_capabilities_reflects_injected_settings_not_hardcoded_values(
    tmp_path,
) -> None:
    """A regression guard against an endpoint that ignores its injected Settings.

    Uses non-default values for every field the endpoint reports, built with its
    own app/client rather than the shared `client` fixture (whose `settings`
    fixture happens to use plain defaults), so a hardcoded implementation cannot
    pass by accident.
    """
    custom_settings = Settings(
        workspace_dir=tmp_path / "custom-ws",
        default_model="claude-opus-5",
        max_allowed_budget_usd=42.0,
    )
    app = create_app(settings=custom_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["default_model"] == "claude-opus-5"
    assert body["limits"]["max_allowed_budget_usd"] == 42.0
    assert body["workspace_dir"] == str(custom_settings.workspace_dir)


# --- what the service REQUIRES, not just what it returns ---------------------
# The three additions asked for in CP-134.
# The argument behind them: this API documents what it returns and is silent
# about what it validates at boot, so the only way to discover a credential
# mismatch was to start a container and read `exit 3`.


async def test_capabilities_publishes_the_credential_specification(client) -> None:
    response = await client.get("/v1/capabilities")
    body = response.json()

    assert body["credential_sources"] == ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
    assert body["provider_selectors"] == [
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ]


async def test_the_provider_selectors_are_not_advertised_as_credentials(client) -> None:
    """The distinction is the whole point of publishing two lists.

    A single merged array would satisfy a naive reading -- all five DO pass the
    boot gate -- while telling a caller that injecting `CLAUDE_CODE_USE_BEDROCK`
    delivers a key. It does not: it selects a provider whose own credential
    chain this service never inspects. A container built on that reading boots
    green and fails on its first turn, which is the same failure the field
    exists to prevent, one variable along.
    """
    body = (await client.get("/v1/capabilities")).json()
    assert set(body["credential_sources"]).isdisjoint(body["provider_selectors"])
    assert not any(name.startswith("CLAUDE_CODE_USE_") for name in body["credential_sources"])


async def test_capabilities_publishes_max_sessions_and_the_boot_gates(tmp_path) -> None:
    """All three read from the injected Settings, not from constants.

    `max_sessions` was previously reachable only by scraping the prose of a 429,
    which left a caller wanting to show "3 of 8 sessions" with no denominator.
    """
    custom = Settings(
        workspace_dir=tmp_path / "ws",
        max_sessions=3,
        require_credentials=False,
        require_mounts=False,
    )
    app = create_app(settings=custom)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/v1/capabilities")).json()

    assert body["max_sessions"] == 3
    assert body["require_credentials"] is False
    assert body["require_mounts"] is False


def test_the_credential_specification_is_readable_without_booting() -> None:
    """`python -m agent_service.spec` answers the question a caller has to
    ask BEFORE it can start a container.

    The endpoint version of this is circular: `/v1/capabilities` needs a running
    service, and the service refuses to boot without a credential -- so the
    check needed the thing it was meant to validate. This path has no server and
    no environment override, and reads the same constants the endpoint does.
    """
    from agent_service.config import CREDENTIAL_ENV_VARS, PROVIDER_SELECTOR_ENV_VARS
    from agent_service.spec import specification

    published = specification()
    assert published["credential_sources"] == list(CREDENTIAL_ENV_VARS)
    assert published["provider_selectors"] == list(PROVIDER_SELECTOR_ENV_VARS)


def test_the_listen_specification_is_readable_without_booting() -> None:
    """0.13.0. The same pre-boot question, about the other half of provisioning.

    A caller that starts containers has to decide how to REACH one before it
    exists. Agent Studio's route is a container resolving another by name on a
    user-defined Docker network, so the bind address is load-bearing and the
    port was a hardcoded constant on their side with a comment and nothing
    backing it.

    Read from `config` rather than restated, exactly like the two credential
    lists above -- a second copy of a published value is a drift waiting to
    happen, and `test_config.py::test_the_published_listen_specification_is_the_image_command`
    is what ties `config`'s copy to the image's `CMD`.
    """
    from agent_service.config import LISTEN_ADDRESS, LISTEN_PORT
    from agent_service.spec import specification

    listen = specification()["listen"]
    assert listen == {"address": LISTEN_ADDRESS, "port": LISTEN_PORT}
    # The shape a consumer parses, pinned separately from the values so that a
    # rename cannot pass by agreeing with itself.
    assert isinstance(listen["port"], int), "a JSON string port would need parsing"
    assert listen["address"] == "0.0.0.0"


def test_the_no_boot_module_imports_no_sdk_and_no_web_stack() -> None:
    """It has to run in an image whose service cannot start, so it must not
    depend on anything the service needs at boot."""
    import subprocess
    import sys

    probe = (
        "import sys, agent_service.spec as c;"
        "print(c.specification()['credential_sources']);"
        "assert 'claude_agent_sdk' not in sys.modules, 'imported the SDK';"
        "assert 'fastapi' not in sys.modules, 'imported FastAPI'"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "ANTHROPIC_API_KEY" in result.stdout


async def test_the_published_spec_file_matches_this_version_of_the_app(client) -> None:
    """The version's own `openapi-<version>-<impl>.json` exists, is current, COMMITTED.

    Consumers read against a checked-in spec rather than a running service, and
    a stale one is worse than none: it reports a surface that no longer exists
    while looking authoritative. This fails when the version moves without the
    spec being regenerated, and when the spec drifts from what the app serves.

    **The document moved out of this implementation in Plan 8 step 4** and now
    lives at the platform root, because it is the specification's rather than this
    build's -- a second implementation in another language has to satisfy the
    same file. This test stays here, and it is the one place a test in this
    suite reaches outside the implementation: what it asserts is precisely that
    THIS app agrees with THAT document.

    Not `docs/` deliberately, and that has not changed: code, tests included,
    does not read anything under `docs/`. A comment may cite a document; an
    assertion may not depend on one. `scripts/dump-schema.py` writes where this
    reads, so publishing a version is committing what it wrote.

    The tracked-by-git assertion is not belt-and-braces. Until 2026-08-06 these
    lived in `docs/schema/`, which `.gitignore`'s unanchored `schema/` pattern
    matched at every depth -- so no released version's document had ever been
    committed, this test passed on the author's machine, and AS-24 ("every
    released version publishes its document") was false in a way neither side's
    conformance suite could see. Existence on disk is not publication.

    Regenerate with:
        uv run python scripts/dump-schema.py --openapi-only
    """
    import json
    import subprocess
    from pathlib import Path

    impl = Path(__file__).resolve().parents[1]
    repo = impl.parents[1]
    served = (await client.get("/openapi.json")).json()
    version = served["info"]["version"]
    # **One document per implementation, in `spec/` itself.** The filename
    # carries the IMPLEMENTATION since Plan 8 step 6: two builds serve two
    # documents for one document version, because a document that documents
    # behaviour cannot be byte-identical across implementations -- and AS-24
    # keeps byte equality per build rather than being relaxed to containment,
    # which is what lets the document tier prove clauses with no service running.
    from agent_service.versions import IMPLEMENTATION_NAME

    # **ONE DIRECTORY since 2026-08-19** (user): `spec/` carries the current
    # version and nothing else, and every version before it lives in its
    # `release-<version>` git tag. Main is always a `-snapshot`, so what the app
    # serves and what `spec/` publishes move together in one commit.
    directory = repo / "spec" / "openapi"
    published = directory / f"{IMPLEMENTATION_NAME}-{version}.json"

    assert published.exists(), (
        f"no published spec for version {version}: expected {published.name} in "
        f"{directory.relative_to(repo).as_posix()}/. Regenerate it -- see this "
        f"test's docstring."
    )
    assert json.loads(published.read_text(encoding="utf-8")) == served, (
        f"{published.name} has drifted from what the app serves. Regenerate it."
    )

    # **The tracked-by-git assertion is about PUBLICATION, so a snapshot is
    # exempt** (2026-08-09). A `-snapshot` version is the internal document a
    # release is iterated into: regenerated whenever a build changes, never
    # frozen, and deleted once the release it became is published. Requiring it
    # to be tracked *before* it can be committed is a circularity -- the
    # pre-commit hook runs this suite, so a newly generated snapshot could never
    # be committed at all. The same reason `ci.py`'s `freeze` stage skips
    # snapshot directories.
    #
    # **It still has to be committed**, and that is a different rule enforced at
    # a different time: the suite reads the document, so a fresh clone without it
    # cannot run. CP-140 makes verifying it part of the
    # cut rather than of every run.
    if "-snapshot" in version:
        return

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(published.relative_to(repo).as_posix())],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, (
        f"{published.name} exists but is NOT tracked by git, so a fresh clone does not "
        "have it and AS-24 is false. Check `git check-ignore -v` on the path: an "
        "unanchored .gitignore pattern is what caused this before."
    )


async def test_the_served_version_is_the_specification_document_version(client) -> None:
    """`/openapi.json`'s `info.version` is the DOCUMENT's, not this build's.

    **This replaced `test_the_advertised_version_matches_the_package_version`
    in Plan 8 step 5**, and the replacement is the point rather than a
    refactor: that test pinned `info.version` to `pyproject.toml`, which is
    exactly the pun the step broke. Keeping it would have made the split
    unrepresentable.

    Two edges here, and the second is the one a container cannot check for
    itself. `spec/VERSION` at the platform root is the source of truth;
    `agent_service/versions.py` repeats it because the image has no access to
    that file, and this is what stops the copy drifting.
    """
    from pathlib import Path

    from agent_service.versions import DOCUMENT_VERSION

    spec = (await client.get("/openapi.json")).json()
    assert spec["info"]["version"] == DOCUMENT_VERSION

    spec_version = (
        (Path(__file__).resolve().parents[3] / "spec" / "VERSION")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert DOCUMENT_VERSION == spec_version, (
        f"agent_service.versions.DOCUMENT_VERSION is {DOCUMENT_VERSION} but "
        f"spec/VERSION says {spec_version}. The specification owns that "
        "number; this build only repeats it."
    )


async def test_the_implementation_version_matches_the_package_version(client) -> None:
    """`/v1/capabilities`'s `impl.version` is this build's number.

    The other half of what the old single-number test covered. It moved from
    `info.version` to here in 0.12.0 because that field now carries the
    document's version -- without this there would be no way to ask a running
    service which build it is. The field was `implementation` until 0.14.0.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    caps = (await client.get("/v1/capabilities")).json()
    assert caps["impl"]["version"] == declared


async def test_the_two_halves_of_the_join_are_named_as_a_pair(client) -> None:
    """`spec` and `impl` -- 0.14.0's rename, asserted as the pair it is.

    They answer "what does this build promise" and "what is it", and they are
    only useful together. `specification` beside `implementation` said that badly in
    two ways at once: one word for the document that did not match the directory
    publishing it, and two words in different registers for a matched pair.

    Both names now match the platform's own two product directories, `spec/` and
    `impl/`, which is what decided the direction -- `specification` +
    `implementation` would have been equally consistent and matched neither.

    The OLD names are asserted absent, not merely the new ones present. 0.14.0
    removed them rather than deprecating them, and a test that only checked the
    new names would pass just as happily if both spellings were emitted, which
    is the thing this release deliberately did not do.
    """
    caps = (await client.get("/v1/capabilities")).json()

    assert "spec" in caps and "impl" in caps
    assert "specification" not in caps, "0.14.0 removed `specification`; it must not return"
    assert "implementation" not in caps, "0.14.0 removed `implementation`"
    # The third member of the group, and the reason `impl` beats `implementation`
    # on register: nothing here is a long word.
    assert set(caps["spec"]) == {"document_version"}
    assert set(caps["impl"]) == {"name", "version"}
    assert set(caps["sdk"]) == {"name", "version"}


# --- AS-33: declared responses vs what `errors.py` can actually produce ------
#
# **Generalised from the Codex build, where the defect that motivated it was
# measured** (CP-139). That build could
# produce three statuses its document did not declare, and one of them -- 503 --
# was declared by *neither* implementation, so the document-to-document comparison
# that found the others was structurally incapable of finding it.
#
# This build has no such gap and these tests are what keep it that way. The rule
# is the proposed AS-33: a build declares every status its own error mapping can
# produce on that route, and **absence means unreachable**.


def _declared_statuses(document: dict) -> set[str]:
    out: set[str] = set()
    for item in document["paths"].values():
        for method, operation in item.items():
            if method in {"get", "post", "patch", "delete"}:
                out |= set(operation.get("responses", {}))
    return out


async def test_every_status_errors_py_can_produce_is_declared_somewhere(client) -> None:  # noqa: ANN001
    """The guard that would have caught the Codex build's undeclared 503 alone.

    **Read from `errors.py`'s source rather than from a list written here**, so
    adding a mapping forces a decision about which routes can reach it instead of
    silently producing a status no document mentions.

    A regex over `status=NNN` rather than a table, because this build maps
    exceptions with `if isinstance(...)` branches rather than a tuple -- the Codex
    build has a `_TABLE` and its equivalent test reads that. What matters is that
    the assertion is driven by the code that produces the statuses.
    """
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "agent_service" / "errors.py"
    ).read_text(encoding="utf-8")
    produced = set(re.findall(r"status=(\d{3})", source))
    assert produced, "found no status= literals in errors.py; the regex has rotted"

    declared = _declared_statuses((await client.get("/openapi.json")).json())
    missing = sorted(produced - declared)
    assert not missing, (
        f"AS-33: errors.py can produce {missing} and no route declares them. A "
        "status a client cannot see in the document is one it has no branch for -- "
        "see CP-139 for what that costs"
    )


async def test_the_turn_routes_declare_the_timeout_they_enforce(client) -> None:  # noqa: ANN001
    """A published timeout budget implies a reachable 504.

    **A capability the build publishes is evidence of reachability**, which is the
    half of AS-33 that catches the opposite defect: the Codex build published
    `default_request_timeout_s` and `max_allowed_timeout_s` while enforcing no turn
    deadline at all, so its 504 was undeclared because it was unbuilt.
    """
    document = (await client.get("/openapi.json")).json()
    for path in ("/v1/query", "/v1/sessions/{sid}/messages"):
        responses = document["paths"][path]["post"]["responses"]
        assert "504" in responses, (
            f"AS-33: {path} declares no 504, but this build enforces `timeout_s` "
            "and publishes both timeout figures on /v1/capabilities"
        )


# --- token_usage, against the payload this SDK actually produces -------------
#
# **The field shipped with no test on either build**, and on the Codex build
# that let it publish five nulls for a whole release while the numbers sat in
# the raw `usage` beside them (CP-139).
# This build's mapping was correct, which is luck rather than coverage, so the
# gap is closed here too.

#: The Claude SDK's `usage` shape: FLAT, snake_case, both cache counters, and no
#: separate reasoning count. Taken from the shape `test_runner.py` already drives
#: `build_outcome` with, which is what the SDK hands over verbatim.
_SDK_USAGE = {
    "input_tokens": 1200,
    "output_tokens": 340,
    "cache_creation_input_tokens": 900,
    "cache_read_input_tokens": 15488,
}


def test_the_named_counts_are_read_from_this_sdks_shape() -> None:
    """Four of five populated, and the fifth null for a real reason: this SDK
    does not separate reasoning tokens from `output_tokens`, so
    `reasoning_output_tokens` means *not reported* rather than *none*."""
    from agent_service.api import _token_usage

    usage = _token_usage(_SDK_USAGE)
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 340
    assert usage.cache_write_tokens == 900
    assert usage.cache_read_tokens == 15488
    assert usage.reasoning_output_tokens is None


def test_the_two_cache_counters_are_not_swapped() -> None:
    """**Read is the cheap half and write is the expensive one**, so swapping
    them understates a bill rather than failing anything. Distinct values above
    are the only reason this is checkable at all."""
    from agent_service.api import _token_usage

    usage = _token_usage(_SDK_USAGE)
    assert usage.cache_read_tokens == _SDK_USAGE["cache_read_input_tokens"]
    assert usage.cache_write_tokens == _SDK_USAGE["cache_creation_input_tokens"]


def test_no_usage_is_five_nulls_and_still_an_object() -> None:
    """`null` counts inside a present object, never a null object -- a consumer
    must never have to tell "no counts" from "no field"."""
    from agent_service.api import _token_usage

    assert _token_usage(None).input_tokens is None
    assert _token_usage({}).output_tokens is None



async def test_the_sandbox_capability_says_this_build_confines_nothing(client) -> None:  # noqa: ANN001
    """**Both `true`, and that is the warning rather than the boast.**

    This build's `Bash` is unconfined -- the container and its mount split are
    the only boundary, which `README.md` says in its opening paragraph. Nothing
    inside the container stops a command reaching the network or writing outside
    the workspace.

    The Codex build reports `network_access: false` because its agent runs under
    bubblewrap, measured. **Publishing the pair is what lets a client tell the
    two apart** instead of discovering it from an Agent that works on one image
    and not the other -- AS-32 applied to the difference a tool-using Agent
    notices first.
    """
    sandbox = (await client.get("/v1/capabilities")).json()["sandbox"]

    assert sandbox["network_access"] is True
    assert sandbox["confines_writes_to_workspace"] is False


def test_the_documents_paths_are_in_canonical_order(tmp_path) -> None:
    """**All three builds publish their operations in ONE order** (AS-31).

    FastAPI writes `paths` in route-registration order, so this is the only
    thing standing between the document and whatever order the decorators
    happen to run in -- and nothing else would notice: `freeze` hashes each
    document against its own copy, the core is a set intersection, and AS-24's
    check is a dict comparison, which in Python ignores key order.

    So the three documents drifted into two different orders and stayed green.
    Isomorphism that has to be established by inspection is not obvious, and
    the point of the core is that it should be.

    **A new route fails HERE**, which is where the fix is one line: add it to
    `CANONICAL_PATHS` in the place a reader would look for it. `canonical()`
    appends an unlisted path rather than raising, deliberately -- a 500 on
    `/openapi.json` in a running service is a worse failure than a
    late-sorted entry.
    """
    served = list(create_app(Settings(workspace_dir=tmp_path / 'ws')).openapi()["paths"])
    assert served == list(CANONICAL_PATHS), (
        "the served document's path order is not the canonical one; "
        f"got {served}"
    )


async def test_the_published_example_is_what_a_live_instance_actually_answers(
    client,
) -> None:
    """**The document shows VALUES, not just a shape** -- and they must be true.

    An OpenAPI document describes the shape of `/v1/capabilities` and says
    nothing about what this build answers, so a consumer holding all three
    builds' documents could not see how the builds differ without starting three
    containers. The example closes that; this test is what keeps it honest,
    because an example nothing checks is a comment.

    Deployment-dependent fields are excluded: the example is built from
    DEFAULTS, since AS-24 requires the service to serve exactly its published
    document and a live port or cap in the example would break that everywhere.
    """
    from agent_spec.openapi.examples import DEPLOYMENT_DEPENDENT, placeholdered

    document = (await client.get("/openapi.json")).json()
    live = (await client.get("/v1/capabilities")).json()
    published = (document["paths"]["/v1/capabilities"]["get"]["responses"]["200"]
                 ["content"]["application/json"]["example"])

    # Versions that move on the implementation stream are published as a
    # placeholder, so compare against a live payload with the same rule
    # applied rather than excluding whole objects: `sdk.name` stays checked,
    # and the rule is stated once, in the module that publishes it.
    expected = placeholdered(live)

    assert set(published) == set(live), "the example and the payload differ in SHAPE"
    differing = {
        field for field in live
        if field not in DEPLOYMENT_DEPENDENT and published[field] != expected[field]
    }
    assert not differing, (
        f"the published example no longer matches what this build answers: {differing}"
    )
    assert DEPLOYMENT_DEPENDENT <= set(live), "DEPLOYMENT_DEPENDENT names a field that is gone"


def test_the_ca_bundle_variable_is_published_with_its_shape() -> None:
    """CP-144: a consumer behind a private authority cannot infer this.

    **Nothing on this image's surface reveals it** -- there is no `node` on the
    PATH and no `node_modules`; the runtime is compiled into the bundled
    executable, which carries four plausible names and honours two. Pinned to
    the measured value so that changing it stays a deliberate act with evidence
    behind it.

    `replaces_default_trust` is asserted `False` for the reason it exists: this
    build reaches a public host and a privately-signed one at once, and the
    Codex build cannot. A consumer reads this field rather than discovering the
    difference when a turn fails.
    """
    from agent_service.config import CA_BUNDLE_SOURCE
    from agent_service.spec import specification

    published = specification()["ca_bundle_source"]
    assert published == CA_BUNDLE_SOURCE, "a second copy of a published value drifts"
    assert published == {
        "variable": "SSL_CERT_FILE",
        "shape": "file",
        "replaces_default_trust": False,
    }


def test_the_preboot_impl_matches_the_capabilities_one() -> None:
    """CP-145: the same object on both surfaces, from one constant.

    **A consumer keys its per-build table at `docker create` time**, before there
    is a service to ask -- the environment a container is created with, and any
    file written between create and start, are both decided then. A certificate
    authority is one of those files and cannot be added afterwards, because the
    runtime reads its trust store once at startup.

    Asserted against `/v1/capabilities` rather than against a literal, because
    two copies of one fact is the drift this test exists to prevent.
    """
    from agent_service.spec import specification
    from agent_service.versions import IMPLEMENTATION_NAME, IMPLEMENTATION_VERSION

    published = specification()
    assert published["impl"] == {
        "name": IMPLEMENTATION_NAME,
        "version": IMPLEMENTATION_VERSION,
    }
    # The top-level version is the same value from the same local, so a consumer
    # reading either can never be told two different things.
    assert published["impl"]["version"] == published["version"]

def test_the_model_api_names_the_target_family_not_the_language() -> None:
    """CP-146: the value is the target family, and the suffix is not in it.

    `impl.name` carries the implementation language and this does not, which
    is what keeps the two fields from being one. Asserted against a literal
    rather than derived from `IMPLEMENTATION_NAME`, because deriving it would
    pass even if the suffix leaked back in.

    The consumer maps this to a vendor API on their own side.
    """
    from agent_service.config import MODEL_API
    from agent_service.spec import specification
    from agent_service.versions import IMPLEMENTATION_NAME

    published = specification()["model_api"]
    assert published == MODEL_API, "a second copy of a published value drifts"
    assert published == "claude"
    assert published != IMPLEMENTATION_NAME, "the language suffix leaked in"


def test_the_published_document_embeds_no_version_that_moves_under_it() -> None:
    """The defect this rule exists for, checked against the FILE.

    A build bumps for any reason, several times between two documents. A
    published document is frozen -- by `freeze`, and by AS-24, which requires a
    running service to serve exactly the document published for its version. So
    a real implementation version inside the example means the first bump after
    a cut makes the served document differ from the published one, permanently,
    for a change that touched no route.

    It survived this long only because every version so far has been a
    `-snapshot` and a snapshot can be regenerated. Read from the file rather
    than from the app, because the file is the artifact that gets frozen.
    """
    import json  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    from agent_spec.openapi.examples import MOVING_VERSIONS, VERSION_PLACEHOLDER  # noqa: PLC0415

    from agent_service.versions import (  # noqa: PLC0415
        DOCUMENT_VERSION,
        IMPLEMENTATION_NAME,
        IMPLEMENTATION_VERSION,
    )

    root = _Path(__file__).resolve().parents[3]
    directory = root / "spec" / "openapi"
    document = json.loads(
        (directory / f"{IMPLEMENTATION_NAME}-{DOCUMENT_VERSION}.json")
        .read_text(encoding="utf-8")
    )
    example = (document["paths"]["/v1/capabilities"]["get"]["responses"]["200"]
               ["content"]["application/json"]["example"])

    for path in sorted(MOVING_VERSIONS):
        head, _, leaf = path.partition(".")
        value = example[head][leaf] if leaf else example[head]
        assert value == VERSION_PLACEHOLDER, (
            f"{path} is {value!r} in the published document. A version that "
            f"moves on the implementation stream cannot sit in an artifact "
            f"that gets frozen."
        )
    # **A BLANKET SUBSTRING SCAN, and it needs one exemption since 0.19.0.**
    # The loop above pins each field that must be a placeholder; this catches a
    # version that reached the example by some path nobody thought of.
    #
    # It cannot distinguish two versions that are the same STRING, and at 0.19.0
    # they are: all three implementations were set to the document's number, so
    # `spec.document_version` legitimately carries it. That field belongs in a
    # frozen document -- it is what the document IS -- so the scan runs over the
    # example with it removed rather than being deleted for being inconvenient.
    scanned = {k: v for k, v in example.items() if k != "spec"}
    assert IMPLEMENTATION_VERSION not in json.dumps(scanned), (
        "this build's version is somewhere in the published example"
    )
    # The one version that BELONGS there: it moves with the document itself.
    assert example["spec"]["document_version"] == DOCUMENT_VERSION


# --- the pre-boot facts, published in this build's OWN document --------------


def _preboot_component() -> dict:
    """This build's `PrebootSpec`, straight out of the document it serves."""
    from agent_spec.openapi.preboot import SCHEMA_NAME

    from agent_service.api import create_app

    document = create_app(_preboot_settings()).openapi()
    component = document.get("components", {}).get("schemas", {}).get(SCHEMA_NAME)
    assert isinstance(component, dict), (
        "the document publishes no PrebootSpec, so a consumer holding the "
        "specification must pull an image to learn what this build reads"
    )
    return component


def test_the_document_publishes_this_builds_preboot_facts() -> None:
    """The document must say exactly what this build's constants hold.

    **The consumer depends on the specification at build time and loads images at
    runtime**, and several decisions these facts inform -- which credential
    variable to inject, which variable carries a private certificate authority,
    which database revision to migrate to -- are made before any container
    exists. Publishing them only on the image put a runtime dependency in front
    of a build-time question.

    So the document carries them, and this is what stops it carrying them
    WRONGLY: a published value nothing compares against goes stale silently,
    which is the failure the pre-boot surface had in the first place.
    """
    from agent_spec.openapi.preboot import mismatches

    from agent_service.api import create_app
    from agent_service.spec import specification

    document = create_app(_preboot_settings()).openapi()
    found = mismatches(document, specification())
    assert not found, "the document and the binary disagree: " + "; ".join(found)


def test_the_preboot_component_pins_what_a_consumer_provisions_with() -> None:
    """Every provisioning fact is a `const`, not a free string.

    **This is the whole reason it is in the document rather than only on the
    image.** A shape that says `model_api` is "any non-empty string" tells a
    consumer nothing it can act on; `{"const": "gemini"}` is a constraint a
    validator enforces and a generator emits as a literal type.

    **No enum anywhere**, and that is deliberate: each build states its own
    value, so nothing has to predict how many builds will exist. A closed set in
    a shared file would carry the half we know and imply the half we do not, and
    a fourth build breaking no rule would falsify it.
    """
    properties = _preboot_component()["properties"]
    for field in (
        "document_version",
        "schema_revision",
        "model_api",
        "credential_sources",
        "provider_selectors",
        "auth_enforced",
        "endpoint_source",
    ):
        assert "const" in properties[field], (
            f"{field} is published open, so a consumer reading the specification "
            "still has to start a container to learn it"
        )
    assert "const" in properties["impl"]["properties"]["name"]
    assert "const" in properties["listen"]["properties"]["port"]


def test_the_versions_that_move_are_not_pinned() -> None:
    """`version` and `impl.version` must stay open, or AS-24 breaks on a bump.

    A build bumps for any reason at all, several times between two documents,
    and the document is frozen at a release. A real version pinned here means the
    served document stops matching the published one the first time that happens
    -- AS-24 broken by a change that touched no route. The capabilities example
    beside it learned this the same way.
    """
    properties = _preboot_component()["properties"]
    assert "const" not in properties["version"]
    assert "const" not in properties["impl"]["properties"]["version"]


def _preboot_settings():
    """Declared defaults only -- the same rule the capabilities example follows."""
    from agent_service.config import Settings

    return Settings.model_construct()


async def test_the_mcp_tool_call_bounds_are_what_the_bundled_cli_imposes(client) -> None:
    """AS-32 for a LONG tool call, and the numbers are the CLI's (CP-149).

    All four were read out of the bundled CLI rather than stopwatched. The two
    that are easy to get wrong are asserted for their reasons rather than their
    values: the idle figure is the `sse`/`http` one because a published value is
    never more generous than the strictest transport this build lists, and
    `progress_resets_idle` is what makes a keepalive-only stream different from
    one emitting `notifications/progress`.
    """
    tool_call = (await client.get("/v1/capabilities")).json()["mcp"]["tool_call"]

    assert tool_call == {
        "request_timeout_s": 60,
        "idle_timeout_s": 300,
        "total_timeout_s": 100000,
        "progress_resets_idle": True,
    }
    assert tool_call["idle_timeout_s"] < 1800, (
        "1800 is the `stdio` figure; publishing it would promise a network "
        "server six times the patience it actually gets"
    )
    assert tool_call["idle_timeout_s"] < tool_call["total_timeout_s"], (
        "the idle timer is what a live call is actually held by; a total cap "
        "below it would mean the published idle figure is unreachable"
    )
