from gha_watcher_tui.models import Job
from gha_watcher_tui.workflow import build_edges, match_yaml_job, parse_needs

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


def test_build_edges_unmatched_jobs_are_isolated():
    jobs = [job("lint"), job("mystery")]
    assert build_edges(jobs, SIMPLE_YAML) == []
