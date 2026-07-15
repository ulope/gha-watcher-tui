"""Textual app: live job graph for a single workflow run."""

import asyncio
from typing import Any

import httpx
from netext import ArrowTip, EdgeRoutingMode, EdgeSegmentDrawingMode
from netext.layout_engines import LayoutDirection, SugiyamaLayout
from netext.textual_widget.widget import GraphView
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static

from .models import Job, WorkflowRun
from .workflow import build_edges

EDGE_DATA: dict[str, Any] = {
    "$edge-routing-mode": EdgeRoutingMode.ORTHOGONAL,
    "$edge-segment-drawing-mode": EdgeSegmentDrawingMode.BOX,
    "$end-arrow-tip": ArrowTip.ARROW,
    "$style": Style(color="grey50"),
}


def _render_job(node: str, data: dict[str, Any], style: Style) -> Text:
    return Text(f"{data.get('glyph', '?')} {node}", style=style)


def node_data(job: Job) -> dict[str, Any]:
    style = Style(color=job.color, bold=job.state == "in_progress")
    return {
        "glyph": job.glyph,
        "$style": style,
        "$content-style": style,
        "$content-renderer": _render_job,
    }


class WatcherApp(App[int]):
    CSS = """
    #status {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    """

    BINDINGS = [Binding("q", "abort", "Quit")]

    def __init__(self, client, ref: str, poll: float = 5.0):
        super().__init__()
        self.client = client
        self.ref = ref
        self.poll = poll
        self.watched_run: WorkflowRun | None = None
        self.jobs_by_name: dict[str, Job] = {}
        self._yaml_text = ""

    def compose(self) -> ComposeResult:
        yield Static(f"Looking for the latest run of {self.ref!r}…", id="status")
        yield GraphView(
            layout_engine=SugiyamaLayout(direction=LayoutDirection.LEFT_RIGHT),
            id="graph",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._start(), exclusive=True)

    async def _start(self) -> None:
        try:
            run = await self.client.latest_run(self.ref)
        except httpx.HTTPError as error:
            self.exit(2, message=f"GitHub API error: {error}")
            return
        if run is None:
            self.exit(2, message=f"No workflow runs found for ref {self.ref!r}")
            return
        self.watched_run = run
        try:
            self._yaml_text = await self.client.workflow_yaml(run)
        except httpx.HTTPError:
            self._yaml_text = ""  # degrade to a graph without edges
        try:
            jobs = await self.client.jobs(run.id)
        except httpx.HTTPError as error:
            self.exit(2, message=f"GitHub API error: {error}")
            return
        # GraphView.set_graph is a no-op while the widget is unsized; wait for
        # layout before the first apply.
        graph = self.query_one(GraphView)
        while graph.size.width == 0:
            await asyncio.sleep(0.01)
        self._apply(run, jobs)
        if self._maybe_finish(run):
            return
        self.set_interval(self.poll, self._tick)

    async def _tick(self) -> None:
        assert self.watched_run is not None
        try:
            run = await self.client.run(self.watched_run.id)
            jobs = await self.client.jobs(self.watched_run.id)
        except httpx.HTTPError as error:
            self._set_status(warning=f"API error, retrying: {error}")
            return
        self._apply(run, jobs)
        self._maybe_finish(run)

    def _maybe_finish(self, run: WorkflowRun) -> bool:
        if not run.is_complete:
            return False
        self.exit(
            run.exit_code,
            message=f"Run #{run.run_number} ({run.workflow_name}) "
            f"finished: {run.conclusion}\n{run.html_url}",
        )
        return True

    def _apply(self, run: WorkflowRun, jobs: list[Job]) -> None:
        graph = self.query_one(GraphView)
        new = {job.name: job for job in jobs}
        if set(new) != set(self.jobs_by_name):
            edges = build_edges(jobs, self._yaml_text)
            graph.set_graph(
                {name: node_data(job) for name, job in new.items()},
                [(u, v, EDGE_DATA) for u, v in edges],
            )
        else:
            try:
                for name, job in new.items():
                    if self.jobs_by_name[name].state != job.state:
                        graph.update_node(name, data=node_data(job))
            except KeyError:
                # Console graph lost the node (e.g. rebuilt while unsized).
                graph.set_graph(
                    {name: node_data(job) for name, job in new.items()},
                    [(u, v, EDGE_DATA) for u, v in build_edges(jobs, self._yaml_text)],
                )
        self.jobs_by_name = new
        self.watched_run = run
        self._set_status()

    def _set_status(self, warning: str | None = None) -> None:
        run = self.watched_run
        if run is None:
            return
        state = run.conclusion or run.status
        text = Text.assemble(
            (f"{run.workflow_name} ", "bold"),
            f"run #{run.run_number} · {self.ref} · ",
            (state.replace("_", " "), "yellow" if not run.is_complete else ""),
        )
        if warning:
            text.append(f"  ⚠ {warning}", style="red")
        self.query_one("#status", Static).update(text)

    def action_abort(self) -> None:
        self.exit(130)
