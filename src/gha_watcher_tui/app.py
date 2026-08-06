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

from .github import describe_api_error
from .models import PLACEHOLDER_STATUS, Job, WorkflowRun
from .workflow import build_edges, pending_jobs, transitive_reduction

EDGE_DATA: dict[str, Any] = {
    "$edge-routing-mode": EdgeRoutingMode.ORTHOGONAL,
    "$edge-segment-drawing-mode": EdgeSegmentDrawingMode.BOX,
    "$end-arrow-tip": ArrowTip.ARROW,
    # Magnets stay on AUTO: explicit ones make netext 0.5.0's router wrap
    # edges all the way around their endpoint nodes.
    "$style": Style(color="bright_black"),
}


class FitGraphView(GraphView):
    def watch_zoom(self, old: Any, new: Any) -> None:
        # netext 0.5.0 declares watch_zoom(new, old) but Textual passes
        # (old, new), so the base watcher re-applies the stale zoom and
        # post-construction zoom changes are silently ignored.
        if new != old:
            self._console_graph.zoom = new
            self._graph_was_updated()


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

    def __init__(self, client, ref: str, poll: float = 5.0, exit_on_complete: bool = True):
        super().__init__()
        # ANSI passthrough with the terminal's own default background, so the
        # app matches the terminal's color scheme instead of a Textual theme.
        self.theme = "ansi-dark"
        self.client = client
        self.ref = ref
        self.poll = poll
        self.exit_on_complete = exit_on_complete
        self.watched_run: WorkflowRun | None = None
        self.jobs_by_name: dict[str, Job] = {}
        self._yaml_text = ""
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static(f"Looking for the latest run of {self.ref!r}…", id="status")
        yield FitGraphView(
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
            self.exit(2, message=describe_api_error(error, self.client.repo))
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
            self.exit(2, message=describe_api_error(error, self.client.repo))
            return
        # GraphView.set_graph is a no-op while the widget is unsized; wait for
        # layout before the first apply.
        graph = self.query_one(GraphView)
        while graph.size.width == 0:
            await asyncio.sleep(0.01)
        self._apply(run, jobs)
        if self._maybe_finish(run):
            return
        self._timer = self.set_interval(self.poll, self._tick)

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
        if self._timer is not None:
            self._timer.stop()
        if self.exit_on_complete:
            self.exit(
                run.exit_code,
                message=f"Run #{run.run_number} ({run.workflow_name}) "
                f"finished: {run.conclusion}\n{run.html_url}",
            )
        return True

    def _apply(self, run: WorkflowRun, jobs: list[Job]) -> None:
        graph = self.query_one(GraphView)
        new = {job.name: job for job in jobs}
        # YAML jobs GitHub hasn't created yet render as pending placeholders,
        # so the full DAG is visible (and the layout stable) from the start.
        for name in pending_jobs(jobs, self._yaml_text).values():
            new.setdefault(name, Job(id=-1, name=name, status=PLACEHOLDER_STATUS, conclusion=None))
        if set(new) != set(self.jobs_by_name):
            graph.zoom = 1.0
            graph.set_graph(
                {name: node_data(job) for name, job in new.items()},
                self._display_edges(jobs),
            )
            self._auto_fit(graph)
        else:
            try:
                for name, job in new.items():
                    if self.jobs_by_name[name].state != job.state:
                        graph.update_node(name, data=node_data(job))
            except KeyError:
                # Console graph lost the node (e.g. rebuilt while unsized).
                graph.set_graph(
                    {name: node_data(job) for name, job in new.items()},
                    self._display_edges(jobs),
                )
        self.jobs_by_name = new
        self.watched_run = run
        self._set_status()

    def _display_edges(self, jobs: list[Job]) -> list[tuple[str, str, dict[str, Any]]]:
        edges = transitive_reduction(build_edges(jobs, self._yaml_text))
        return [(u, v, EDGE_DATA) for u, v in edges]

    def _auto_fit(self, graph: GraphView) -> None:
        """Zoom out to fit graphs that overflow the widget; never zoom in.

        Uses a uniform scale factor rather than AutoZoom.FIT, which scales the
        axes independently and distorts routed edges into stair-steps (and
        would also scale small graphs *up*, scattering a handful of nodes
        across the whole screen).
        """
        full = graph._console_graph.full_viewport
        if full.width > graph.size.width or full.height > graph.size.height:
            graph.zoom = min(
                graph.size.width / full.width,
                graph.size.height / full.height,
            )

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
        # After the run finished (--no-exit), quitting reports its outcome;
        # before that, quitting is an abort.
        if self.watched_run is not None and self.watched_run.is_complete:
            self.exit(self.watched_run.exit_code)
        else:
            self.exit(130)
