"""Derive job dependency edges from a workflow YAML file.

The GitHub REST jobs API does not expose `needs:`, so edges come from parsing
the workflow definition and matching API job names back to YAML job ids
(matrix jobs appear expanded, e.g. "test (3.12)" for YAML job "test").
"""

import yaml

from .models import Job


def _yaml_jobs(yaml_text: str) -> dict[str, dict]:
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}
    if not isinstance(doc, dict):
        return {}
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return {}
    return {job_id: spec for job_id, spec in jobs.items() if isinstance(spec, dict)}


def parse_needs(yaml_text: str) -> dict[str, list[str]]:
    """Map each YAML job id to the list of job ids it needs."""
    result = {}
    for job_id, spec in _yaml_jobs(yaml_text).items():
        needs = spec.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        elif not isinstance(needs, list):
            needs = []
        result[job_id] = needs
    return result


def match_yaml_job(api_name: str, yaml_text: str) -> str | None:
    """Match an API job name to its YAML job id, or None if no candidate fits."""
    jobs = _yaml_jobs(yaml_text)
    candidates: dict[str, str] = {}
    for job_id, spec in jobs.items():
        candidates[job_id] = job_id
        name = spec.get("name")
        # Templated names (`${{ ... }}`) can't be matched literally.
        if isinstance(name, str) and "${{" not in name:
            candidates[name] = job_id

    if api_name in candidates:
        return candidates[api_name]
    # Matrix jobs expand to "<base name> (<matrix values>)".
    base = api_name.split(" (")[0]
    return candidates.get(base)


def build_edges(api_jobs: list[Job], yaml_text: str) -> list[tuple[str, str]]:
    """Dependency edges between API job names, fanning matrix jobs out/in."""
    needs = parse_needs(yaml_text)
    by_yaml_id: dict[str, list[str]] = {}
    yaml_id_of: dict[str, str] = {}
    for job in api_jobs:
        yaml_id = match_yaml_job(job.name, yaml_text)
        if yaml_id is not None:
            by_yaml_id.setdefault(yaml_id, []).append(job.name)
            yaml_id_of[job.name] = yaml_id

    edges = []
    for job_name, yaml_id in yaml_id_of.items():
        for needed in needs.get(yaml_id, []):
            for upstream in by_yaml_id.get(needed, []):
                edges.append((upstream, job_name))
    return edges
