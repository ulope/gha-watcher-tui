from gha_watcher_tui.cli import build_parser, parse_repo_url, resolve_token


def test_parse_repo_url_ssh():
    assert parse_repo_url("git@github.com:octo/hello.git") == "octo/hello"
    assert parse_repo_url("git@github.com:octo/hello") == "octo/hello"


def test_parse_repo_url_https():
    assert parse_repo_url("https://github.com/octo/hello.git") == "octo/hello"
    assert parse_repo_url("https://github.com/octo/hello") == "octo/hello"


def test_parse_repo_url_ssh_scheme():
    assert parse_repo_url("ssh://git@github.com/octo/hello.git") == "octo/hello"


def test_parse_repo_url_non_github_returns_none():
    assert parse_repo_url("git@gitlab.com:octo/hello.git") is None
    assert parse_repo_url("not a url") is None


def test_parser_defaults():
    args = build_parser().parse_args(["main"])
    assert args.ref == "main"
    assert args.repo is None
    assert args.poll == 5.0


def test_parser_overrides():
    args = build_parser().parse_args(["v1.2.3", "--repo", "o/r", "--poll", "2"])
    assert args.ref == "v1.2.3"
    assert args.repo == "o/r"
    assert args.poll == 2.0


def test_resolve_token_prefers_github_token():
    assert resolve_token({"GITHUB_TOKEN": "a", "GH_TOKEN": "b"}) == "a"
    assert resolve_token({"GH_TOKEN": "b"}) == "b"
    assert resolve_token({}) is None
