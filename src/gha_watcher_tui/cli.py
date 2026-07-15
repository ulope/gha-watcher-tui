"""CLI entry point: resolve repo/token, run the watcher app, map to exit code."""

import argparse
import re
import subprocess
import sys

_REPO_URL_RE = re.compile(
    r"^(?:https://github\.com/|(?:ssh://)?git@github\.com[:/])([^/]+/[^/]+?)(?:\.git)?/?$"
)


def parse_repo_url(url: str) -> str | None:
    match = _REPO_URL_RE.match(url.strip())
    return match.group(1) if match else None


def resolve_token(env: dict[str, str]) -> str | None:
    return env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gha-watch",
        description="Watch the latest GitHub Actions run for a branch or tag as a live job graph.",
    )
    parser.add_argument("ref", help="branch or tag name to watch")
    parser.add_argument(
        "--repo",
        help="repository as owner/name (default: derived from the origin remote)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=5.0,
        help="poll interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--no-exit",
        action="store_true",
        help="stay open after the run finishes instead of exiting; "
        "q then exits with the run's status code",
    )
    return parser


def repo_from_origin() -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return parse_repo_url(result.stdout)


def main() -> None:
    import os

    args = build_parser().parse_args()

    token = resolve_token(dict(os.environ))
    if token is None:
        print("error: no GitHub token found; set GITHUB_TOKEN or GH_TOKEN", file=sys.stderr)
        sys.exit(2)

    repo = args.repo or repo_from_origin()
    if repo is None:
        print(
            "error: could not determine repository; pass --repo owner/name "
            "or run inside a clone with a github.com origin remote",
            file=sys.stderr,
        )
        sys.exit(2)

    from .app import WatcherApp
    from .github import GitHubClient

    app = WatcherApp(
        client=GitHubClient(repo=repo, token=token),
        ref=args.ref,
        poll=args.poll,
        exit_on_complete=not args.no_exit,
    )
    exit_code = app.run()
    sys.exit(exit_code if isinstance(exit_code, int) else 2)


if __name__ == "__main__":
    main()
