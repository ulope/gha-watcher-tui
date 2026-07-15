import httpx
import pytest
import respx

from gha_watcher_tui.github import GitHubClient

RUN_PAYLOAD = {
    "id": 7,
    "run_number": 123,
    "name": "CI",
    "workflow_id": 99,
    "head_sha": "abc123",
    "head_branch": "main",
    "path": ".github/workflows/ci.yml",
    "status": "in_progress",
    "conclusion": None,
    "html_url": "https://github.com/o/r/actions/runs/7",
}


@pytest.fixture
def client():
    return GitHubClient(repo="o/r", token="tok-123")


@respx.mock
async def test_latest_run_queries_branch_filter(client):
    route = respx.get(
        "https://api.github.com/repos/o/r/actions/runs",
        params={"branch": "main", "per_page": 1},
    ).mock(return_value=httpx.Response(200, json={"workflow_runs": [RUN_PAYLOAD]}))

    run = await client.latest_run("main")

    assert run is not None
    assert run.id == 7
    assert run.workflow_name == "CI"
    auth = route.calls.last.request.headers["Authorization"]
    assert auth == "Bearer tok-123"


@respx.mock
async def test_latest_run_returns_none_when_no_runs(client):
    respx.get("https://api.github.com/repos/o/r/actions/runs").mock(
        return_value=httpx.Response(200, json={"workflow_runs": []})
    )
    assert await client.latest_run("ghost-branch") is None


@respx.mock
async def test_run_fetches_single_run(client):
    respx.get("https://api.github.com/repos/o/r/actions/runs/7").mock(
        return_value=httpx.Response(200, json=RUN_PAYLOAD)
    )
    run = await client.run(7)
    assert run.run_number == 123


@respx.mock
async def test_jobs_returns_parsed_jobs(client):
    respx.get("https://api.github.com/repos/o/r/actions/runs/7/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {"id": 1, "name": "lint", "status": "completed", "conclusion": "success"},
                    {"id": 2, "name": "test (3.13)", "status": "in_progress", "conclusion": None},
                ]
            },
        )
    )
    jobs = await client.jobs(7)
    assert [j.name for j in jobs] == ["lint", "test (3.13)"]
    assert jobs[0].state == "success"


@respx.mock
async def test_workflow_yaml_fetches_raw_file_at_head_sha(client):
    from gha_watcher_tui.models import run_from_api

    route = respx.get(
        "https://api.github.com/repos/o/r/contents/.github/workflows/ci.yml",
        params={"ref": "abc123"},
    ).mock(return_value=httpx.Response(200, text="name: CI\njobs: {}\n"))

    text = await client.workflow_yaml(run_from_api(RUN_PAYLOAD))

    assert text == "name: CI\njobs: {}\n"
    accept = route.calls.last.request.headers["Accept"]
    assert accept == "application/vnd.github.raw+json"


@respx.mock
async def test_http_errors_raise(client):
    respx.get("https://api.github.com/repos/o/r/actions/runs/7").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.run(7)
