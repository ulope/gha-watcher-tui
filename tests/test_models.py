from gha_watcher_tui.models import Job, WorkflowRun, job_from_api, run_from_api


def make_job(status: str, conclusion: str | None) -> Job:
    return Job(id=1, name="build", status=status, conclusion=conclusion)


def test_job_state_normalizes_status_and_conclusion():
    assert make_job("queued", None).state == "queued"
    assert make_job("waiting", None).state == "queued"
    assert make_job("pending", None).state == "queued"
    assert make_job("in_progress", None).state == "in_progress"
    assert make_job("completed", "success").state == "success"
    assert make_job("completed", "failure").state == "failure"
    assert make_job("completed", "timed_out").state == "failure"
    assert make_job("completed", "cancelled").state == "cancelled"
    assert make_job("completed", "skipped").state == "skipped"


def test_job_glyph_and_color_per_state():
    assert make_job("completed", "success").glyph == "✓"
    assert make_job("completed", "success").color == "green"
    assert make_job("completed", "failure").glyph == "✗"
    assert make_job("completed", "failure").color == "red"
    assert make_job("in_progress", None).color == "yellow"
    assert make_job("queued", None).color == "grey50"


def test_job_from_api_payload():
    job = job_from_api(
        {
            "id": 42,
            "name": "test (3.13)",
            "status": "completed",
            "conclusion": "success",
            "extra_field": "ignored",
        }
    )
    assert job == Job(id=42, name="test (3.13)", status="completed", conclusion="success")


def test_run_from_api_payload():
    run = run_from_api(
        {
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
    )
    assert run.id == 7
    assert run.run_number == 123
    assert run.workflow_name == "CI"
    assert run.path == ".github/workflows/ci.yml"
    assert run.head_sha == "abc123"
    assert run.is_complete is False


def test_run_is_complete_and_exit_code():
    done = WorkflowRun(
        id=1,
        run_number=1,
        workflow_name="CI",
        workflow_id=9,
        head_sha="abc",
        head_branch="main",
        path="wf.yml",
        status="completed",
        conclusion="success",
        html_url="",
    )
    assert done.is_complete is True
    assert done.exit_code == 0
    failed = WorkflowRun(**{**done.__dict__, "conclusion": "failure"})
    assert failed.exit_code == 1
