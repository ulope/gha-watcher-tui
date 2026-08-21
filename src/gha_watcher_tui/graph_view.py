"""Draw a laid-out job graph into terminal cells, and scroll it in Textual.

Edges are painted as connection bits per cell (north/south/west/east) rather
than as finished characters, so wherever two edges run through the same cell
the glyph that comes out is the junction they actually form: a trunk shared by
three jobs reads `├`, a fan-in reads `┴`, a crossing reads `┼`.
"""

from dataclasses import dataclass

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .layout import BOX_HEIGHT, Box, Route, layout

EDGE_STYLE = Style(color="bright_black")

_NORTH, _SOUTH, _WEST, _EAST = 1, 2, 4, 8
_GLYPHS = {
    _NORTH: "│",
    _SOUTH: "│",
    _WEST: "─",
    _EAST: "─",
    _NORTH | _SOUTH: "│",
    _WEST | _EAST: "─",
    _NORTH | _EAST: "╰",
    _NORTH | _WEST: "╯",
    _SOUTH | _EAST: "╭",
    _SOUTH | _WEST: "╮",
    _NORTH | _SOUTH | _EAST: "├",
    _NORTH | _SOUTH | _WEST: "┤",
    _SOUTH | _WEST | _EAST: "┬",
    _NORTH | _WEST | _EAST: "┴",
    _NORTH | _SOUTH | _WEST | _EAST: "┼",
}


@dataclass(frozen=True)
class GraphNode:
    """A job box: what to write in it, and how to colour it."""

    label: str
    style: Style

    @property
    def width(self) -> int:
        return cell_len(self.label) + 4  # "│ " + label + " │"


class _Canvas:
    def __init__(self) -> None:
        self._bits: dict[tuple[int, int], int] = {}
        self._chars: dict[tuple[int, int], tuple[str, Style]] = {}

    def write(self, row: int, col: int, text: str, style: Style) -> None:
        for offset, char in enumerate(text):
            self._chars[(row, col + offset)] = (char, style)

    def line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        (row, col), (end_row, end_col) = start, end
        if row == end_row:
            low, high = sorted((col, end_col))
            for column in range(low, high + 1):
                self._bit(row, column, (_EAST if column < high else 0) | (_WEST if column > low else 0))
        else:
            low, high = sorted((row, end_row))
            for line in range(low, high + 1):
                self._bit(line, col, (_SOUTH if line < high else 0) | (_NORTH if line > low else 0))

    def _bit(self, row: int, col: int, bits: int) -> None:
        if bits:  # a run of one cell connects to nothing and draws nothing
            self._bits[(row, col)] = self._bits.get((row, col), 0) | bits

    def rows(self, height: int, width: int) -> list[list[Segment]]:
        """Flatten to one list of segments per row, runs of a style merged."""
        rendered = []
        for row in range(height):
            segments: list[Segment] = []
            text, style = "", None
            for col in range(width):
                char, cell_style = self._cell(row, col)
                if cell_style != style and text:
                    segments.append(Segment(text, style))
                    text = ""
                text, style = text + char, cell_style
            if text.strip():
                segments.append(Segment(text.rstrip(), style))
            rendered.append(segments)
        return rendered

    def _cell(self, row: int, col: int) -> tuple[str, Style | None]:
        if (row, col) in self._chars:
            return self._chars[(row, col)]
        bits = self._bits.get((row, col))
        if bits is None:
            return " ", None
        return _GLYPHS[bits], EDGE_STYLE


def draw(nodes: dict[str, GraphNode], edges: list[tuple[str, str]]) -> list[list[Segment]]:
    """Lay the graph out and rasterize it into styled rows."""
    if not nodes:
        return []
    placement = layout({name: node.width for name, node in nodes.items()}, edges)
    canvas = _Canvas()
    for route in placement.routes:
        _draw_route(canvas, route, placement.boxes[route.target])
    for name, node in nodes.items():
        _draw_box(canvas, placement.boxes[name], node)
    return canvas.rows(placement.height, placement.width)


def _draw_box(canvas: _Canvas, box: Box, node: GraphNode) -> None:
    inner = box.width - 2
    canvas.write(box.row - BOX_HEIGHT // 2, box.col, f"╭{'─' * inner}╮", node.style)
    canvas.write(box.row, box.col, f"│ {node.label} │", node.style)
    canvas.write(box.row + BOX_HEIGHT // 2, box.col, f"╰{'─' * inner}╯", node.style)


def _draw_route(canvas: _Canvas, route: Route, target: Box) -> None:
    for start, end in zip(route.points, route.points[1:]):
        canvas.line(start, end)
    canvas.write(target.row, target.col - 1, "▶", EDGE_STYLE)


class JobGraph(ScrollView):
    """Scrollable view of the job graph.

    The graph is drawn at its natural size and panned, never scaled: shrinking
    it would mean shrinking the job names, and a name you can't read is worse
    than one you have to scroll to.
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._rows: list[list[Segment]] = []

    def set_graph(self, nodes: dict[str, GraphNode], edges: list[tuple[str, str]]) -> None:
        self._rows = draw(nodes, edges)
        width = max(
            (sum(cell_len(segment.text) for segment in row) for row in self._rows), default=0
        )
        self.virtual_size = Size(width, len(self._rows))
        self.refresh()

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        row = y + scroll_y
        if row >= len(self._rows):
            return Strip.blank(self.size.width)
        strip = Strip(self._rows[row]).crop(scroll_x, scroll_x + self.size.width)
        return strip.extend_cell_length(self.size.width)
