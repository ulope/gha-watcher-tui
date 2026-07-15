"""Thin async client for the GitHub Actions REST endpoints we poll."""

import httpx

from .models import Job, WorkflowRun, job_from_api, run_from_api

API_BASE = "https://api.github.com"


def describe_api_error(error: httpx.HTTPError, repo: str) -> str:
    """Turn an httpx error into an actionable message for the user."""
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 404:
            return (
                f"Repository {repo!r} not found (HTTP 404).\n"
                "Check the owner/name spelling. GitHub also returns 404 for private\n"
                "repositories the token cannot access — make sure the token has the\n"
                "'repo' scope (classic PAT), is granted this repository (fine-grained\n"
                "PAT), and is authorized for the organization if it enforces SSO."
            )
        if status == 401:
            return "GitHub rejected the token (HTTP 401) — it is invalid or expired."
    return f"GitHub API error: {error}"


class GitHubClient:
    def __init__(self, repo: str, token: str, client: httpx.AsyncClient | None = None):
        self.repo = repo
        self._client = client or httpx.AsyncClient(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10.0,
        )

    async def latest_run(self, ref: str) -> WorkflowRun | None:
        resp = await self._client.get(
            f"/repos/{self.repo}/actions/runs",
            params={"branch": ref, "per_page": 1},
        )
        resp.raise_for_status()
        runs = resp.json()["workflow_runs"]
        return run_from_api(runs[0]) if runs else None

    async def run(self, run_id: int) -> WorkflowRun:
        resp = await self._client.get(f"/repos/{self.repo}/actions/runs/{run_id}")
        resp.raise_for_status()
        return run_from_api(resp.json())

    async def jobs(self, run_id: int) -> list[Job]:
        resp = await self._client.get(
            f"/repos/{self.repo}/actions/runs/{run_id}/jobs",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return [job_from_api(j) for j in resp.json()["jobs"]]

    async def workflow_yaml(self, run: WorkflowRun) -> str:
        resp = await self._client.get(
            f"/repos/{self.repo}/contents/{run.path}",
            params={"ref": run.head_sha},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        resp.raise_for_status()
        return resp.text

    async def close(self) -> None:
        await self._client.aclose()
