import httpx

from gha_watcher_tui.github import describe_api_error


def status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/repos/o/r/actions/runs")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_404_explains_private_repo_access():
    message = describe_api_error(status_error(404), repo="o/r")
    assert "'o/r'" in message
    assert "not found" in message
    assert "private" in message
    assert "token" in message


def test_401_explains_bad_credentials():
    message = describe_api_error(status_error(401), repo="o/r")
    assert "token" in message
    assert "invalid" in message or "expired" in message


def test_other_errors_pass_through():
    message = describe_api_error(status_error(500), repo="o/r")
    assert "GitHub API error" in message
    request = httpx.Request("GET", "https://api.github.com/x")
    network = httpx.ConnectError("no route", request=request)
    assert "GitHub API error" in describe_api_error(network, repo="o/r")
