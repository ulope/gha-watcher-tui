from gha_watcher_tui.layout import BOX_HEIGHT, ROW_PITCH, layout

SHAPES = {
    "chain": (["a", "b", "c"], [("a", "b"), ("b", "c")]),
    "fan out": (["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("a", "d")]),
    "fan in": (["a", "b", "c", "d"], [("a", "d"), ("b", "d"), ("c", "d")]),
    "diamond": (["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]),
    "skip layer": (["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]),
    "disconnected": (["a", "b", "c"], [("a", "b")]),
    "single": (["a"], []),
}


def place(names, edges, width=12):
    return layout({name: width for name in names}, edges)


def cells(route):
    """Every cell an edge is drawn through."""
    for (row, col), (end_row, end_col) in zip(route.points, route.points[1:]):
        if row == end_row:
            yield from ((row, c) for c in range(min(col, end_col), max(col, end_col) + 1))
        else:
            yield from ((r, col) for r in range(min(row, end_row), max(row, end_row) + 1))


def test_parallel_jobs_stack_at_row_pitch():
    placement = place(["a", "b", "c"], [("a", "b"), ("a", "c")])
    assert abs(placement.boxes["b"].row - placement.boxes["c"].row) == ROW_PITCH


def test_layers_run_left_to_right():
    placement = place(["a", "b", "c"], [("a", "b"), ("b", "c")])
    assert placement.boxes["a"].right < placement.boxes["b"].col
    assert placement.boxes["b"].right < placement.boxes["c"].col


def test_edges_out_of_one_job_share_a_trunk():
    placement = place(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("a", "d")])
    trunks = {
        # the first turn out of the source is the trunk column
        route.points[1][1]
        for route in placement.routes
    }
    assert len(trunks) == 1


def test_edges_into_one_job_share_a_spine():
    # Mirror of the fan-out: jobs with a single dependant converge on one line
    # into their target instead of arriving on parallel ones.
    placement = place(["a", "b", "c", "d"], [("a", "d"), ("b", "d"), ("c", "d")])
    spines = {route.points[1][1] for route in placement.routes}
    assert len(spines) == 1


def test_edges_out_of_different_jobs_get_their_own_trunk():
    # Two fans crossing the same gap must stay apart, or the graph would claim
    # dependencies that aren't there.
    placement = place(["a", "b", "c", "d"], [("a", "c"), ("a", "d"), ("b", "c"), ("b", "d")])
    trunks = {route.points[0][0]: route.points[1][1] for route in placement.routes}
    assert len(set(trunks.values())) == 2


def test_boxes_never_overlap():
    for names, edges in SHAPES.values():
        placement = place(names, edges)
        boxes = list(placement.boxes.values())
        for index, box in enumerate(boxes):
            for other in boxes[index + 1 :]:
                rows_clash = abs(box.row - other.row) < BOX_HEIGHT
                columns_clash = box.col <= other.right and other.col <= box.right
                assert not (rows_clash and columns_clash)


def test_edges_never_cross_a_box():
    for names, edges in SHAPES.values():
        placement = place(names, edges)
        drawn = {cell for route in placement.routes for cell in cells(route)}
        for box in placement.boxes.values():
            covered = {
                (row, col)
                for row in range(box.row - BOX_HEIGHT // 2, box.row + BOX_HEIGHT // 2 + 1)
                # the column in front of a box belongs to its arrow head
                for col in range(box.col - 1, box.right + 1)
            }
            assert not drawn & covered


def test_edge_spanning_layers_routes_through_a_clear_lane():
    names, edges = SHAPES["skip layer"]
    placement = place(names, edges)
    long_edge = next(route for route in placement.routes if route.target == "d")
    # it turns more than once: out of the source, along a lane, and into "d"
    assert len(long_edge.points) > 3


def test_disconnected_jobs_are_stacked_not_dropped():
    placement = place(*SHAPES["disconnected"])
    assert set(placement.boxes) == {"a", "b", "c"}
    assert placement.boxes["c"].row > placement.boxes["a"].row


def test_empty_graph():
    placement = layout({}, [])
    assert placement.boxes == {} and placement.routes == []
