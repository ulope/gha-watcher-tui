# gha-watcher-tui

A terminal UI that watches the latest GitHub Actions run for a branch or tag and
renders its jobs as a live node graph — boxes connected by dependency edges,
colored by state — similar to GitHub's web workflow visualization.

## Usage

```sh
gha-watch <branch-or-tag> [--repo owner/name] [--poll SECONDS] [--no-exit]
```

- The repository defaults to the `origin` remote of the current directory;
  override with `--repo owner/name`.
- Authentication uses a token from `GITHUB_TOKEN` or `GH_TOKEN`
  (e.g. `GITHUB_TOKEN=$(gh auth token) gha-watch main`).
- The graph polls every 5 seconds (`--poll` to change) and updates node colors
  as jobs progress. Press `q` to quit.

When the run finishes the app exits automatically with a status code.
With `--no-exit` it stays open showing the final graph instead; pressing `q`
then exits with the run's status code.

| Code | Meaning |
| ---- | ------- |
| 0    | run concluded successfully |
| 1    | run failed or was cancelled |
| 2    | usage or API error (no token, unknown repo/ref, …) |
| 130  | quit manually before the run finished |

## Notes

- Dependency edges come from parsing the workflow YAML (`needs:`), since the
  REST jobs API doesn't expose them. Matrix jobs (`test (3.12)`) and
  reusable-workflow jobs (`images / build`) are matched back to their YAML job
  heuristically; unmatched jobs render as disconnected nodes.
- Jobs GitHub hasn't created yet (their `needs:` haven't resolved) are shown as
  dimmed `◌` placeholders taken from the YAML, so the full graph is visible
  from the start. A pending matrix job appears as a single placeholder until
  its legs are created.
- The UI uses the terminal's own ANSI palette and background.
- Only the single latest run for the ref is watched; a newer run starting
  mid-watch is ignored.

## Development

```sh
uv sync
uv run pytest
```
