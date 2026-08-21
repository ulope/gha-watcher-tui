"""Left-to-right layered layout for a job DAG, in terminal cells.

grandalf does the graph theory — ranking, crossing reduction, coordinate
assignment, and dummy vertices to reserve a free lane for every edge that
spans more than one layer. This module turns its float coordinates into
integer rows and columns, and routes the edges: everything leaving a job
shares one vertical trunk and only splits off at its target's row.

grandalf lays out top to bottom, so every vertex is handed to it rotated (its
box height as the width) and the resulting coordinates are read back swapped:
grandalf's x is our row, its rank is our column.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from grandalf.graphs import Edge, Graph, Vertex
from grandalf.layouts import DummyVertex, SugiyamaLayout

BOX_HEIGHT = 3
"""Rows in a job box: top border, label, bottom border."""

ROW_PITCH = BOX_HEIGHT + 1
"""Rows between the centres of two boxes stacked in one layer."""

COMPONENT_GAP = 2
"""Blank rows between two disconnected parts of the graph."""

_LEAD_IN = 2
"""Columns of edge line between a box and the first trunk column."""

_LEAD_OUT = 2
"""Columns for the "─▶" that lands on a box."""


@dataclass(frozen=True)
class Box:
    """A job box, by its centre row and its leftmost column."""

    row: int
    col: int
    width: int

    @property
    def right(self) -> int:
        return self.col + self.width - 1


@dataclass(frozen=True)
class Route:
    """An edge, as the corner points of an orthogonal path."""

    target: str
    points: list[tuple[int, int]]


@dataclass(frozen=True)
class Layout:
    boxes: dict[str, Box]
    routes: list[Route]
    height: int
    width: int


class _View:
    """The geometry grandalf expects on a vertex, rotated for a left-to-right
    layout: what grandalf spaces out as width is our row extent."""

    def __init__(self, width: int, height: int):
        self.w = height
        self.h = width
        self.xy = (0.0, 0.0)


def layout(widths: dict[str, int], edges: Iterable[tuple[str, str]]) -> Layout:
    """Place every job box and route every edge.

    `widths` maps job name to the rendered width of its box, in columns.
    """
    if not widths:
        return Layout(boxes={}, routes=[], height=0, width=0)

    # A pair repeated (or pointing at a job that is not on screen) would throw
    # the channel bookkeeping off, and neither says anything a single edge
    # between two visible boxes doesn't.
    pairs = list(dict.fromkeys((u, v) for u, v in edges if u in widths and v in widths))
    ranks, rows = _place_vertices(widths, pairs)
    columns, channels = _place_columns(widths, ranks, rows, pairs)
    boxes = {
        name: Box(row=rows[name], col=columns[ranks[name]], width=widths[name])
        for name in widths
    }
    routes = _route_edges(pairs, boxes, ranks, rows, columns, channels)
    cells = [(box.row + BOX_HEIGHT // 2, box.right) for box in boxes.values()]
    cells += [point for route in routes for point in route.points]
    height = max(row for row, _ in cells) + 1
    width = max(column for _, column in cells) + 1
    return Layout(boxes=boxes, routes=routes, height=height, width=width)


def _place_vertices(
    widths: dict[str, int], edges: list[tuple[str, str]]
) -> tuple[dict[str, int], dict[str | tuple[str, str, int], int]]:
    """Rank and row for every job, plus a row for each edge's dummy lanes.

    Dummy lanes are keyed `(u, v, rank)`: the row an edge from `u` to `v` may
    cross the layer at `rank` on, kept clear of boxes by grandalf.
    """
    vertices = {name: Vertex(name) for name in widths}
    for name, vertex in vertices.items():
        vertex.view = _View(widths[name], BOX_HEIGHT)
    graph = Graph(list(vertices.values()), [Edge(vertices[u], vertices[v]) for u, v in edges])

    ranks: dict[str, int] = {}
    coords: dict[str | tuple[str, str, int], float] = {}
    layers: dict[int, list[str | tuple[str, str, int]]] = {}
    row_offset = 0.0
    for component in graph.C:
        sugiyama = SugiyamaLayout(component)
        # A dummy vertex only has to keep one row clear, not a whole box.
        sugiyama.dw, sugiyama.dh = 1, 1
        sugiyama.xspace = ROW_PITCH - BOX_HEIGHT  # within a layer: our rows
        sugiyama.yspace = 1  # between layers: replaced by our own columns
        sugiyama.init_all(optimize=True)
        sugiyama.draw()

        placed: dict[str | tuple[str, str, int], tuple[int, float]] = {}
        for vertex in component.sV:
            placed[vertex.data] = (sugiyama.grx[vertex].rank, vertex.view.xy[0])
        for edge, dummies in sugiyama.ctrls.items():
            u, v = edge.v[0].data, edge.v[1].data
            for rank, dummy in dummies.items():
                if isinstance(dummy, DummyVertex):  # the endpoints are in here too
                    placed[(u, v, rank)] = (rank, dummy.view.xy[0])

        lowest = min(coord for _, coord in placed.values())
        for key, (rank, coord) in placed.items():
            coords[key] = coord - lowest + row_offset
            layers.setdefault(rank, []).append(key)
            if isinstance(key, str):
                ranks[key] = rank
        row_offset = max(coords.values()) + BOX_HEIGHT - 1 + COMPONENT_GAP

    rows = _snap_rows(coords, layers, set(widths))
    # The topmost vertex sits on row 0, which leaves its top border nowhere to
    # go, so the whole graph starts half a box down.
    return ranks, {key: row + BOX_HEIGHT // 2 for key, row in rows.items()}


def _snap_rows(
    coords: dict[str | tuple[str, str, int], float],
    layers: dict[int, list[str | tuple[str, str, int]]],
    jobs: set[str],
) -> dict[str | tuple[str, str, int], int]:
    """Round the layout onto whole rows, keeping every layer collision-free.

    Rounding can pull two boxes a row closer together, so walk each layer in
    order and push anything that ends up too close back down. A box takes its
    half-height on each side and a dummy lane only its own row, plus a blank
    row between the two — which is the spacing grandalf was asked for, so the
    push is a floor that rarely has to move anything.
    """
    rows: dict[str | tuple[str, str, int], int] = {}
    for rank in sorted(layers):
        previous: str | tuple[str, str, int] | None = None
        for key in sorted(layers[rank], key=lambda key: coords[key]):
            row = round(coords[key])
            if previous is not None:
                half = BOX_HEIGHT // 2
                needed = (half if previous in jobs else 0) + (half if key in jobs else 0) + 2
                row = max(row, rows[previous] + needed)
            rows[key] = row
            previous = key
    return rows


def _place_columns(
    widths: dict[str, int],
    ranks: dict[str, int],
    rows: dict[str | tuple[str, str, int], int],
    edges: list[tuple[str, str]],
) -> tuple[dict[int, int], dict[int, dict[object, int]]]:
    """Left column of every layer, and the trunk column of every vertical run.

    Each gap between two layers holds the vertical runs that cross it. Runs
    that never share a row can share a column, so they are packed greedily by
    row span, and how many columns a gap ends up needing is what sets the
    distance between its two layers.
    """
    spans: dict[int, dict[object, tuple[int, int]]] = {}
    for key, hops in _hops(edges, ranks, rows).items():
        for gap, (start, end) in hops:
            span = spans.setdefault(gap, {})
            low, high = span.get(key, (start, start))
            span[key] = (min(low, end, start), max(high, end, start))

    channels: dict[int, dict[object, int]] = {}
    for gap, span in spans.items():
        taken: list[list[tuple[int, int]]] = []
        for key, (low, high) in sorted(span.items(), key=lambda item: item[1]):
            for column, used in enumerate(taken):
                if all(high < other_low or low > other_high for other_low, other_high in used):
                    used.append((low, high))
                    channels.setdefault(gap, {})[key] = column
                    break
            else:
                taken.append([(low, high)])
                channels.setdefault(gap, {})[key] = len(taken) - 1

    columns: dict[int, int] = {}
    left = 0
    for rank in sorted(set(ranks.values())):
        columns[rank] = left
        widest = max(
            (widths[name] for name, name_rank in ranks.items() if name_rank == rank), default=0
        )
        used = len(set(channels.get(rank, {}).values()))
        left += widest + _LEAD_IN + max(used, 1) + _LEAD_OUT
    return columns, channels


def _channel_key(u: str, v: str, hop: int, rank: int, fan_out: Counter[str]) -> object:
    """Which vertical run this hop of an edge belongs on.

    Everything leaving a job with several dependants shares that job's trunk.
    A job with a single dependant needs no trunk of its own, so its edge joins
    the target's incoming spine instead — which collapses a fan-in of ten test
    jobs into one line rather than ten parallel ones. Hops after the first
    belong to their own edge; nothing else is going the same way.
    """
    if hop > 0:
        return (u, v, rank)
    return u if fan_out[u] > 1 else ("into", v)


def _hops(
    edges: list[tuple[str, str]],
    ranks: dict[str, int],
    rows: dict[str | tuple[str, str, int], int],
) -> dict[object, list[tuple[int, tuple[int, int]]]]:
    """Vertical runs per channel key: which gap, and the rows it has to span."""
    fan_out = Counter(u for u, _ in edges)
    result: dict[object, list[tuple[int, tuple[int, int]]]] = {}
    for u, v in edges:
        waypoints = _waypoints(u, v, ranks, rows)
        for hop, ((rank, row), (_, next_row)) in enumerate(zip(waypoints, waypoints[1:])):
            key = _channel_key(u, v, hop, rank, fan_out)
            result.setdefault(key, []).append((rank, (row, next_row)))
    return result


def _waypoints(
    u: str,
    v: str,
    ranks: dict[str, int],
    rows: dict[str | tuple[str, str, int], int],
) -> list[tuple[int, int]]:
    """(rank, row) for the source, every layer the edge crosses, and the target."""
    points = [(ranks[u], rows[u])]
    for rank in range(ranks[u] + 1, ranks[v]):
        lane = rows.get((u, v, rank))
        if lane is not None:
            points.append((rank, lane))
    points.append((ranks[v], rows[v]))
    return points


def _route_edges(
    edges: list[tuple[str, str]],
    boxes: dict[str, Box],
    ranks: dict[str, int],
    rows: dict[str | tuple[str, str, int], int],
    columns: dict[int, int],
    channels: dict[int, dict[object, int]],
) -> list[Route]:
    fan_out = Counter(u for u, _ in edges)
    routes = []
    for u, v in edges:
        if ranks[v] <= ranks[u]:  # not produced by `needs:`, but never crash on one
            continue
        waypoints = _waypoints(u, v, ranks, rows)
        points = [(rows[u], boxes[u].right + 1)]
        for hop, ((rank, row), (_, next_row)) in enumerate(zip(waypoints, waypoints[1:])):
            key = _channel_key(u, v, hop, rank, fan_out)
            trunk = _trunk_column(rank, key, boxes, ranks, columns, channels)
            points.append((row, trunk))
            points.append((next_row, trunk))
        points.append((rows[v], boxes[v].col - _LEAD_OUT))
        routes.append(Route(target=v, points=_prune(points)))
    return routes


def _trunk_column(
    rank: int,
    key: object,
    boxes: dict[str, Box],
    ranks: dict[str, int],
    columns: dict[int, int],
    channels: dict[int, dict[object, int]],
) -> int:
    widest = max(
        (boxes[name].right for name, name_rank in ranks.items() if name_rank == rank),
        default=columns[rank],
    )
    return widest + _LEAD_IN + channels[rank][key]


def _prune(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop points that don't turn, so a straight run stays one segment."""
    pruned = [points[0]]
    for point in points[1:]:
        if point != pruned[-1]:
            pruned.append(point)
    return pruned
