from claude_agent_sdk import ProcessError

from agent_service.errors import RunTimeout
from agent_service.options import LimitExceeded


async def test_query_returns_result_and_all_events(client) -> None:
    response = await client.post("/v1/query", json={"prompt": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "sess-test"
    assert body["result"] == "done"
    assert body["is_error"] is False
    assert body["total_cost_usd"] == 0.09
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]
    assert body["events"][1]["content"][0]["name"] == "Read"


async def test_prompt_is_required(client) -> None:
    response = await client.post("/v1/query", json={})
    assert response.status_code == 422


async def test_agent_reported_failure_is_still_http_200(client, fake_factory) -> None:
    _, state = fake_factory
    state["outcome"].is_error = True
    try:
        response = await client.post("/v1/query", json={"prompt": "hello"})
        assert response.status_code == 200
        assert response.json()["is_error"] is True
    finally:
        state["outcome"].is_error = False


async def test_limit_exceeded_is_400_problem(client, fake_factory) -> None:
    _, state = fake_factory
    state["raise"] = LimitExceeded("max_turns", 9999, 200)
    try:
        response = await client.post("/v1/query", json={"prompt": "hi"})
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        assert "max_turns" in response.json()["detail"]
    finally:
        state["raise"] = None


async def test_process_error_is_502_problem(client, fake_factory) -> None:
    _, state = fake_factory
    state["raise"] = ProcessError("agent died", exit_code=1)
    try:
        response = await client.post("/v1/query", json={"prompt": "hi"})
        assert response.status_code == 502
    finally:
        state["raise"] = None


async def test_timeout_is_504_problem(client, fake_factory) -> None:
    _, state = fake_factory
    state["raise"] = RunTimeout("exceeded 600s")
    try:
        response = await client.post("/v1/query", json={"prompt": "hi"})
        assert response.status_code == 504
    finally:
        state["raise"] = None


async def test_outcome_none_reports_outcome_recorded_false(client, fake_factory) -> None:
    # If the SDK stream ends without a ResultMessage (CLI crash, early exit),
    # run.outcome stays None. The response must say so explicitly rather than
    # looking like a clean, output-free success.
    _, state = fake_factory
    state["outcome"] = None
    response = await client.post("/v1/query", json={"prompt": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome_recorded"] is False
    assert body["result"] is None
    assert body["is_error"] is False
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]


async def test_outcome_recorded_true_on_normal_completion(client) -> None:
    response = await client.post("/v1/query", json={"prompt": "hello"})
    assert response.json()["outcome_recorded"] is True


async def test_one_shot_turn_cost_equals_the_total(client) -> None:
    """Item 14, on the endpoint where the distinction collapses. `/v1/query`'s
    connection lasts exactly one run, so the SDK's cumulative figure IS that
    run's cost -- `turn_cost_usd` reports it rather than being null, so a
    client reading one field gets an answer on both endpoints instead of
    having to know which surface it is talking to."""
    body = (await client.post("/v1/query", json={"prompt": "hello"})).json()
    assert body["total_cost_usd"] == 0.09
    assert body["turn_cost_usd"] == 0.09


async def test_one_shot_with_no_outcome_prices_nothing(client, fake_factory) -> None:
    _, state = fake_factory
    state["outcome"] = None
    body = (await client.post("/v1/query", json={"prompt": "hello"})).json()
    assert body["turn_cost_usd"] is None


async def test_openapi_documents_the_query_route(client) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert "/v1/query" in spec["paths"]
    assert "RunResponse" in spec["components"]["schemas"]
    assert "AgentEvent" in spec["components"]["schemas"]
