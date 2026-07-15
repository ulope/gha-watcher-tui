"""Thin async client for the GitHub Actions REST endpoints we poll."""

import httpx

from .models import Job, WorkflowRun, job_from_api, run_from_api

API_BASE = "https://api.github.com"


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
