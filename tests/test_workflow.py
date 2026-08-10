from gha_watcher_tui.models import Job
from gha_watcher_tui.workflow import (
    build_edges,
    match_yaml_job,
    parse_needs,
    pending_jobs,
    transitive_reduction,
)

SIMPLE_YAML = """
name: CI
on: push
jobs:
  lint:
    runs-on: ubuntu-latest
  test:
    needs: lint
    runs-on: ubuntu-latest
  deploy:
    needs: [lint, test]
    runs-on: ubuntu-latest
"""

MATRIX_YAML = """
name: CI
on: push
jobs:
  lint:
    runs-on: ubuntu-latest
  test:
    needs: lint
    strategy:
      matrix:
        python: ["3.12", "3.13"]
    runs-on: ubuntu-latest
  deploy:
    name: Deploy to prod
    needs: test
    runs-on: ubuntu-latest
"""


TEMPLATED_YAML = """
name: ci
on: push
jobs:
  changes:
    name: images / detect changed components
    runs-on: ubuntu-latest
  build-image:
    name: images / ${{ matrix.component_name }}
    needs: changes
    strategy:
      matrix:
        component_name: [gateway, updater]
    runs-on: ubuntu-latest
  python:
    name: checks / python (${{ matrix.component }})
    strategy:
      matrix:
        component: [a, b]
    runs-on: ubuntu-latest
  release-bundle:
    name: release / build bundle
    needs: [changes, build-image]
    runs-on: ubuntu-latest
"""


def job(name: str) -> Job:
    return Job(id=hash(name) % 1000, name=name, status="queued", conclusion=None)


def test_parse_needs_string_and_list():
    assert parse_needs(SIMPLE_YAML) == {
        "lint": [],
        "test": ["lint"],
        "deploy": ["lint", "test"],
    }


def test_parse_needs_tolerates_garbage():
    assert parse_needs("not: [valid") == {}
    assert parse_needs("name: no jobs here") == {}


def test_match_exact_job_id():
    assert match_yaml_job("lint", MATRIX_YAML) == "lint"


def test_match_display_name():
    assert match_yaml_job("Deploy to prod", MATRIX_YAML) == "deploy"


def test_match_matrix_expansion():
    assert match_yaml_job("test (3.12)", MATRIX_YAML) == "test"
    assert match_yaml_job("test (3.13)", MATRIX_YAML) == "test"


def test_match_unknown_returns_none():
    assert match_yaml_job("mystery job", MATRIX_YAML) is None


def test_build_edges_simple():
    jobs = [job("lint"), job("test"), job("deploy")]
    assert set(build_edges(jobs, SIMPLE_YAML)) == {
        ("lint", "test"),
        ("lint", "deploy"),
        ("test", "deploy"),
    }


def test_build_edges_matrix_fan_out_and_in():
    jobs = [job("lint"), job("test (3.12)"), job("test (3.13)"), job("Deploy to prod")]
    assert set(build_edges(jobs, MATRIX_YAML)) == {
        ("lint", "test (3.12)"),
        ("lint", "test (3.13)"),
        ("test (3.12)", "Deploy to prod"),
        ("test (3.13)", "Deploy to prod"),
    }


def test_match_templated_name_expansion():
    assert match_yaml_job("images / gateway", TEMPLATED_YAML) == "build-image"
    assert match_yaml_job("images / updater", TEMPLATED_YAML) == "build-image"


def test_match_unexpanded_template_of_skipped_matrix_job():
    assert match_yaml_job("checks / python (${{ matrix.component }})", TEMPLATED_YAML) == "python"


def test_match_exact_name_wins_over_template_pattern():
    assert match_yaml_job("images / detect changed components", TEMPLATED_YAML) == "changes"


def test_build_edges_templated_fan_out_and_in():
    jobs = [
        job("images / detect changed components"),
        job("images / gateway"),
        job("images / updater"),
        job("release / build bundle"),
    ]
    assert set(build_edges(jobs, TEMPLATED_YAML)) == {
        ("images / detect changed components", "images / gateway"),
        ("images / detect changed components", "images / updater"),
        ("images / detect changed components", "release / build bundle"),
        ("images / gateway", "release / build bundle"),
        ("images / updater", "release / build bundle"),
    }


def test_build_edges_unmatched_jobs_are_isolated():
    jobs = [job("lint"), job("mystery")]
    edges = build_edges(jobs, SIMPLE_YAML)
    assert not any("mystery" in edge for edge in edges)


def test_match_reusable_workflow_job():
    reusable_yaml = """
jobs:
  images:
    uses: ./.github/workflows/images.yml
  publish:
    needs: images
    runs-on: ubuntu-latest
"""
    assert match_yaml_job("images / docker-controller", reusable_yaml) == "images"


def test_pending_jobs_lists_uncreated_yaml_jobs():
    assert pending_jobs([job("lint")], SIMPLE_YAML) == {"test": "test", "deploy": "deploy"}


def test_pending_jobs_empty_when_all_jobs_created():
    assert pending_jobs([job("lint"), job("test"), job("deploy")], SIMPLE_YAML) == {}


def test_pending_jobs_uses_display_names_verbatim():
    pending = pending_jobs([], TEMPLATED_YAML)
    assert pending["release-bundle"] == "release / build bundle"
    # Templated names stay unexpanded, as GitHub shows skipped matrix jobs.
    assert pending["python"] == "checks / python (${{ matrix.component }})"


def test_build_edges_includes_pending_jobs():
    # "lint" and "deploy" haven't been created by GitHub yet, but the DAG
    # around them is known from the YAML.
    assert set(build_edges([job("test")], SIMPLE_YAML)) == {
        ("lint", "test"),
        ("lint", "deploy"),
        ("test", "deploy"),
    }


def test_transitive_reduction_drops_implied_edge():
    edges = [("a", "b"), ("b", "c"), ("a", "c")]
    assert set(transitive_reduction(edges)) == {("a", "b"), ("b", "c")}


def test_transitive_reduction_keeps_independent_edges():
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    assert set(transitive_reduction(edges)) == set(edges)


def test_transitive_reduction_fan_with_shortcut():
    edges = [
        ("changes", "img1"),
        ("changes", "img2"),
        ("img1", "bundle"),
        ("img2", "bundle"),
        ("changes", "bundle"),
        ("bundle", "publish"),
    ]
    assert set(transitive_reduction(edges)) == {
        ("changes", "img1"),
        ("changes", "img2"),
        ("img1", "bundle"),
        ("img2", "bundle"),
        ("bundle", "publish"),
    }


def test_transitive_reduction_drops_multi_hop_implied_edge():
    edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
    assert set(transitive_reduction(edges)) == {("a", "b"), ("b", "c"), ("c", "d")}
