"""Derive job dependency edges from a workflow YAML file.

The GitHub REST jobs API does not expose `needs:`, so edges come from parsing
the workflow definition and matching API job names back to YAML job ids
(matrix jobs appear expanded, e.g. "test (3.12)" for YAML job "test").
"""

import re

import yaml

from .models import Job

_TEMPLATE_RE = re.compile(r"\$\{\{.*?\}\}")


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
    patterns: list[tuple[re.Pattern[str], str]] = []
    for job_id, spec in jobs.items():
        candidates[job_id] = job_id
        name = spec.get("name")
        if not isinstance(name, str):
            continue
        # Skipped matrix jobs come back from the API with the template
        # unexpanded, so even templated names are valid literal candidates.
        candidates[name] = job_id
        if "${{" in name:
            patterns.append((_name_pattern(name), job_id))

    if api_name in candidates:
        return candidates[api_name]
    # Matrix jobs expand to "<base name> (<matrix values>)".
    base = api_name.split(" (")[0]
    if base in candidates:
        return candidates[base]
    # Templated names match as patterns; prefer the most literal one.
    patterns.sort(key=lambda item: len(_TEMPLATE_RE.sub("", item[0].pattern)), reverse=True)
    for pattern, job_id in patterns:
        if pattern.match(api_name):
            return job_id
    return None


def transitive_reduction(edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop edges already implied by a longer path (for display decluttering)."""
    successors: dict[str, set[str]] = {}
    for u, v in edges:
        successors.setdefault(u, set()).add(v)

    reachable: dict[str, set[str]] = {}

    def reach(node: str) -> set[str]:
        if node not in reachable:
            reachable[node] = set()  # guard against cycles in malformed input
            result = set()
            for succ in successors.get(node, ()):
                result.add(succ)
                result |= reach(succ)
            reachable[node] = result
        return reachable[node]

    return [
        (u, v)
        for u, v in edges
        if not any(v in reach(w) for w in successors[u] if w != v)
    ]


def _name_pattern(name: str) -> re.Pattern[str]:
    """Turn a templated display name into a regex, `${{ … }}` becoming a wildcard."""
    literals = _TEMPLATE_RE.split(name)
    return re.compile(".+?".join(re.escape(part) for part in literals) + "$")


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
