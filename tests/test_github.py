from __future__ import annotations

import pytest

from jaws import github


def test_commit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    assert github.commit_url("abc") == "https://github.com/o/r/commit/abc"


def test_commit_url_outside_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert github.commit_url("abc") is None
    assert github.commit_url(None) is None


def test_provenance_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    monkeypatch.setenv("JAWS_HEAD_SHA", "abc")
    provenance = github.provenance("1.2.3")
    assert provenance.version == "1.2.3"
    assert provenance.sha == "abc"
    assert provenance.commit_url == "https://github.com/o/r/commit/abc"
    assert provenance.run_url == "https://github.com/o/r/actions/runs/7"


HUB_COMMIT = "0123456789abcdef0123456789abcdef01234567"
HUB_SOURCE = "https://github.com/Example-Hub/platform"


@pytest.mark.parametrize(
    ("commit", "source", "sha", "url"),
    [
        (HUB_COMMIT, HUB_SOURCE, HUB_COMMIT, f"{HUB_SOURCE}/commit/{HUB_COMMIT}"),
        ("abc123", HUB_SOURCE, None, None),
        (HUB_COMMIT, "http://example.com/x", HUB_COMMIT, None),
    ],
)
def test_provenance_reads_the_platform_s_commit(
    monkeypatch: pytest.MonkeyPatch, commit: str, source: str, sha: str | None, url: str | None
) -> None:
    monkeypatch.setenv(github.ENV_PLATFORM_COMMIT, commit)
    monkeypatch.setenv(github.ENV_PLATFORM_SOURCE, source)
    provenance = github.provenance("1.2.3")
    assert provenance.platform_sha == sha
    assert provenance.platform_url == url
