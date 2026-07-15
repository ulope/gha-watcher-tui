import asyncio

from netext.textual_widget.widget import GraphView

from gha_watcher_tui.app import WatcherApp
from gha_watcher_tui.models import Job, WorkflowRun

YAML = """
jobs:
  lint:
    runs-on: ubuntu-latest
  test:
    needs: lint
    runs-on: ubuntu-latest
"""


def make_run(status: str, conclusion: str | None) -> WorkflowRun:
    return WorkflowRun(
        id=7,
        run_number=1,
        workflow_name="CI",
        workflow_id=9,
        head_sha="abc",
        head_branch="main",
        path="wf.yml",
        status=status,
        conclusion=conclusion,
        html_url="",
    )


class FakeClient:
    """Scripted client: successive run() / jobs() calls pop from these lists."""

    def __init__(self, first_run, run_states, job_states, yaml_text=YAML):
        self.first_run = first_run
        self.run_states = list(run_states)
        self.job_states = list(job_states)
        self.yaml_text = yaml_text

    async def latest_run(self, ref):
        return self.first_run

    async def run(self, run_id):
        return self.run_states.pop(0) if len(self.run_states) > 1 else self.run_states[0]

    async def jobs(self, run_id):
        return self.job_states.pop(0) if len(self.job_states) > 1 else self.job_states[0]

    async def workflow_yaml(self, run):
        return self.yaml_text

    async def close(self):
        pass


def jobs(lint_state, test_state):
    lint_status, lint_concl = lint_state
    test_status, test_concl = test_state
    return [
        Job(id=1, name="lint", status=lint_status, conclusion=lint_concl),
        Job(id=2, name="test", status=test_status, conclusion=test_concl),
    ]


async def test_app_shows_graph_while_run_in_progress():
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("in_progress", None)],
        job_states=[jobs(("completed", "success"), ("in_progress", None))],
    )
    app = WatcherApp(client=client, ref="main", poll=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(GraphView) is not None
        assert set(app.jobs_by_name) == {"lint", "test"}
        assert app.jobs_by_name["test"].state == "in_progress"


async def test_app_exits_zero_when_run_succeeds():
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("completed", "success")],
        job_states=[
            jobs(("completed", "success"), ("in_progress", None)),
            jobs(("completed", "success"), ("completed", "success")),
        ],
    )
    app = WatcherApp(client=client, ref="main", poll=0.05)
    async with app.run_test() as pilot:
        for _ in range(50):
            await pilot.pause()
            await asyncio.sleep(0.05)
            if app.return_value is not None:
                break
    assert app.return_value == 0


async def test_app_exits_one_when_run_fails():
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("completed", "failure")],
        job_states=[jobs(("completed", "success"), ("completed", "failure"))],
    )
    app = WatcherApp(client=client, ref="main", poll=0.05)
    async with app.run_test() as pilot:
        for _ in range(50):
            await pilot.pause()
            await asyncio.sleep(0.05)
            if app.return_value is not None:
                break
    assert app.return_value == 1


async def test_app_exits_two_when_no_run_found():
    client = FakeClient(first_run=None, run_states=[], job_states=[])
    app = WatcherApp(client=client, ref="ghost", poll=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
    assert app.return_value == 2
