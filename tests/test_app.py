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


async def test_small_graph_keeps_zoom_one():
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("in_progress", None)],
        job_states=[jobs(("completed", "success"), ("in_progress", None))],
    )
    app = WatcherApp(client=client, ref="main", poll=60)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        graph = app.query_one(GraphView)
        assert graph._console_graph.zoom_x == 1.0
        assert graph._console_graph.zoom_y == 1.0


async def test_large_graph_scrolls_instead_of_zooming():
    many = [
        Job(id=i, name=f"very-long-job-name-number-{i:02}", status="queued", conclusion=None)
        for i in range(30)
    ]
    yaml_text = "jobs:\n" + "".join(
        f"  very-long-job-name-number-{i:02}:\n    runs-on: x\n"
        + (f"    needs: very-long-job-name-number-{i - 1:02}\n" if i else "")
        for i in range(30)
    )
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("in_progress", None)],
        job_states=[many],
        yaml_text=yaml_text,
    )
    app = WatcherApp(client=client, ref="main", poll=60)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        graph = app.query_one(GraphView)
        # A graph too big for the window is scrolled, never zoomed: netext
        # closes the gaps between nodes without shrinking the nodes, so zooming
        # out only piles the boxes on top of each other.
        assert graph._console_graph.zoom_x == 1.0
        assert graph._console_graph.zoom_y == 1.0
        # The chain lays out left to right, so it overflows horizontally.
        assert graph.virtual_size.width > graph.size.width


async def test_pending_jobs_render_as_placeholders():
    # GitHub hasn't created "test" yet (its `needs:` haven't resolved), but it
    # must still appear in the graph, as a pending placeholder.
    lint_only = [Job(id=1, name="lint", status="in_progress", conclusion=None)]
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("in_progress", None)],
        job_states=[lint_only, jobs(("completed", "success"), ("queued", None))],
    )
    app = WatcherApp(client=client, ref="main", poll=60)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert set(app.jobs_by_name) == {"lint", "test"}
        assert app.jobs_by_name["test"].state == "pending"
        core = app.query_one(GraphView)._console_graph._core_graph
        assert set(core.all_nodes()) == {"lint", "test"}
        assert list(core.all_edges()) == [("lint", "test")]
        # Once the real job is created it takes the placeholder's spot.
        await app._tick()
        await pilot.pause()
        assert app.jobs_by_name["test"].state == "queued"
        assert set(core.all_nodes()) == {"lint", "test"}


async def test_no_exit_keeps_app_open_until_quit():
    client = FakeClient(
        first_run=make_run("completed", "failure"),
        run_states=[make_run("completed", "failure")],
        job_states=[jobs(("completed", "success"), ("completed", "failure"))],
    )
    app = WatcherApp(client=client, ref="main", poll=0.05, exit_on_complete=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        # run is complete but the app stays open
        assert app.return_value is None
        # quitting after completion exits with the run's status code
        await pilot.press("q")
    assert app.return_value == 1


async def test_quit_before_completion_exits_130():
    client = FakeClient(
        first_run=make_run("in_progress", None),
        run_states=[make_run("in_progress", None)],
        job_states=[jobs(("completed", "success"), ("in_progress", None))],
    )
    app = WatcherApp(client=client, ref="main", poll=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
    assert app.return_value == 130


async def test_app_exits_two_when_no_run_found():
    client = FakeClient(first_run=None, run_states=[], job_states=[])
    app = WatcherApp(client=client, ref="ghost", poll=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
    assert app.return_value == 2
