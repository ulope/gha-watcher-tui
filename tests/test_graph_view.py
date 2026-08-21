from rich.style import Style

from gha_watcher_tui.graph_view import EDGE_STYLE, GraphNode, draw


def nodes(*names, style=Style(color="green")):
    return {name: GraphNode(label=name, style=style) for name in names}


def text(rows):
    return "\n".join("".join(segment.text for segment in row) for row in rows)


def test_boxes_and_arrows_are_drawn():
    rendered = text(draw(nodes("lint", "test"), [("lint", "test")]))
    assert "│ lint │" in rendered
    assert "╭──────╮" in rendered
    assert "▶│ test │" in rendered


def test_fan_out_shares_one_trunk():
    # Every edge out of "a" leaves on a single column and only splits off at
    # its target's row, so the trunk reads as branches off one line.
    targets = ["b", "c", "d", "e", "f"]
    rendered = text(draw(nodes("a", *targets), [("a", target) for target in targets]))
    junctions = {
        column
        for line in rendered.splitlines()
        for column, char in enumerate(line)
        if char in "├┼"  # a branch (or a crossing) off the trunk
    }
    assert len(junctions) == 1
    assert "├" in rendered


def test_fan_in_merges_into_one_arrow():
    rendered = text(draw(nodes("a", "b", "c"), [("a", "c"), ("b", "c")]))
    # the two edges meet before the target instead of arriving separately
    assert rendered.count("▶") == 1


def test_nodes_keep_their_own_style():
    styles = {"a": Style(color="red"), "b": Style(color="yellow")}
    rows = draw(
        {name: GraphNode(label=name, style=style) for name, style in styles.items()},
        [("a", "b")],
    )
    drawn = [(segment.style, segment.text) for row in rows for segment in row]
    assert (styles["a"], "│ a │") in drawn
    assert (styles["b"], "│ b │") in drawn
    assert any(style == EDGE_STYLE for style, _ in drawn)


def test_empty_graph_draws_nothing():
    assert draw({}, []) == []
