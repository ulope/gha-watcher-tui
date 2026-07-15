"""Data models for workflow runs and jobs, plus the status→style mapping."""

from dataclasses import dataclass
from typing import Any

# Normalized job state -> (glyph, rich color)
STATE_STYLES: dict[str, tuple[str, str]] = {
    "queued": ("○", "grey50"),
    "in_progress": ("●", "yellow"),
    "success": ("✓", "green"),
    "failure": ("✗", "red"),
    "cancelled": ("⊘", "grey50"),
    "skipped": ("⊘", "grey35"),
}

_FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "stale", "action_required"}


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    status: str
    conclusion: str | None

    @property
    def state(self) -> str:
        if self.status == "completed":
            if self.conclusion in _FAILURE_CONCLUSIONS:
                return "failure"
            if self.conclusion in ("cancelled", "skipped"):
                return self.conclusion
            return "success"
        if self.status == "in_progress":
            return "in_progress"
        return "queued"

    @property
    def glyph(self) -> str:
        return STATE_STYLES[self.state][0]

    @property
    def color(self) -> str:
        return STATE_STYLES[self.state][1]


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    run_number: int
    workflow_name: str
    workflow_id: int
    head_sha: str
    head_branch: str
    path: str
    status: str
    conclusion: str | None
    html_url: str

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"

    @property
    def exit_code(self) -> int:
        return 0 if self.conclusion == "success" else 1


def job_from_api(data: dict[str, Any]) -> Job:
    return Job(
        id=data["id"],
        name=data["name"],
        status=data["status"],
        conclusion=data["conclusion"],
    )


def run_from_api(data: dict[str, Any]) -> WorkflowRun:
    return WorkflowRun(
        id=data["id"],
        run_number=data["run_number"],
        workflow_name=data["name"],
        workflow_id=data["workflow_id"],
        head_sha=data["head_sha"],
        head_branch=data["head_branch"],
        path=data["path"],
        status=data["status"],
        conclusion=data["conclusion"],
        html_url=data["html_url"],
    )
