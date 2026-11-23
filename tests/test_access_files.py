"""Reading other projects' files: the counterparts of a handshake.

A file that cannot be read is an error naming the project and the URL, never
"no handshake": treating it as absent would revoke a consumer's access.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from jaws.access import (
    DirectoryProjectFiles,
    GitHubProjectFiles,
    RegistryIds,
    project_files_from_env,
    project_registry_ids,
    project_repositories,
)
from jaws.errors import ConfigError
from jaws.settings import load_settings
from tests.conftest import CONFIG_DIR, FIXTURES, REPO_ROOT

PROJECT_FILE = (FIXTURES / "registry" / "braveheart-selfplay.yaml").read_text()
URL = "https://api.github.com/repos/Braveheart-Chess/braveheart-selfplay/contents/jaws.yaml"


def _settings() -> Any:
    return load_settings(CONFIG_DIR, environ={})


def test_the_registry_is_read_like_the_workflows_read_it() -> None:
    """The workflows list projects with scripts/projects.sh, independently of Python."""
    repositories = project_repositories(_settings())
    assert repositories["braveheart-selfplay"] == "Braveheart-Chess/braveheart-selfplay"
    assert repositories["braveheart-databricks"] == "Braveheart-Chess/braveheart-databricks"
    listed = json.loads(
        subprocess.run(
            ["scripts/projects.sh", "bot", "research", "databricks"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert repositories == {entry["project"]: entry["repository"] for entry in listed}


class FakeOpener:
    """Stands in for urlopen: records each request and answers with `reply`."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return io.BytesIO(json.dumps(self.reply).encode())


def _contents(text: str, sha: str = "abc") -> dict[str, str]:
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64", "sha": sha}


def test_github_files_decode_and_send_the_token() -> None:
    opener = FakeOpener(_contents(PROJECT_FILE))
    files = GitHubProjectFiles(
        {"braveheart-selfplay": "Braveheart-Chess/braveheart-selfplay"}, "t", opener
    )
    config = files.load("braveheart-selfplay")
    assert config.project == "braveheart-selfplay"
    (request,) = opener.requests
    assert request.full_url == URL
    assert request.get_header("Authorization") == "Bearer t"
    assert files.shas == {"braveheart-selfplay": "abc"}


def test_without_a_token_no_authorization_is_sent() -> None:
    opener = FakeOpener(_contents(PROJECT_FILE))
    GitHubProjectFiles(
        {"braveheart-selfplay": "Braveheart-Chess/braveheart-selfplay"}, None, opener
    ).load("braveheart-selfplay")
    assert opener.requests[0].get_header("Authorization") is None


@pytest.mark.parametrize(
    "reply",
    [
        urllib.error.HTTPError(URL, 404, "Not Found", Message(), None),
        urllib.error.URLError("network is unreachable"),
        _contents("project: [unclosed\n"),
        _contents("project: braveheart-selfplay\n"),  # YAML, but not a valid project file
        {"message": "API rate limit exceeded"},  # no content
    ],
)
def test_a_fetch_failure_names_the_project_and_url(reply: Any) -> None:
    files = GitHubProjectFiles(
        {"braveheart-selfplay": "Braveheart-Chess/braveheart-selfplay"}, None, FakeOpener(reply)
    )
    with pytest.raises(ConfigError) as caught:
        files.load("braveheart-selfplay")
    assert "braveheart-selfplay" in str(caught.value) and URL in str(caught.value)


def test_an_unregistered_project_is_an_error() -> None:
    files = GitHubProjectFiles({}, None, FakeOpener(_contents(PROJECT_FILE)))
    with pytest.raises(ConfigError, match="not-a-project"):
        files.load("not-a-project")


def test_a_project_is_registered_when_its_file_can_be_asked_for(tmp_path: Path) -> None:
    """The reconcile tells a project that does not exist (a typo in a read) from
    a registered project whose file cannot be read, which stays an error."""
    github = GitHubProjectFiles(
        {"braveheart-selfplay": "Braveheart-Chess/braveheart-selfplay"},
        None,
        FakeOpener(_contents(PROJECT_FILE)),
    )
    assert github.registered("braveheart-selfplay")
    assert not github.registered("braveheart-selfply")
    (tmp_path / "braveheart-selfplay.yaml").write_text(PROJECT_FILE)
    directory = DirectoryProjectFiles(tmp_path)
    assert directory.registered("braveheart-selfplay")
    assert not directory.registered("braveheart-selfply")


def test_a_directory_holds_one_file_per_project(tmp_path: Path) -> None:
    (tmp_path / "braveheart-selfplay.yaml").write_text(PROJECT_FILE)
    files = DirectoryProjectFiles(tmp_path)
    assert files.load("braveheart-selfplay").project == "braveheart-selfplay"
    with pytest.raises(ConfigError, match="braveheart-databricks"):
        files.load("braveheart-databricks")


def test_the_environment_picks_a_directory_else_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JAWS_PROJECT_FILES_DIR", str(tmp_path))
    assert isinstance(project_files_from_env(_settings()), DirectoryProjectFiles)
    monkeypatch.delenv("JAWS_PROJECT_FILES_DIR")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "from-github-token")
    files = project_files_from_env(_settings())
    assert isinstance(files, GitHubProjectFiles) and files.token == "from-github-token"
    monkeypatch.setenv("GH_TOKEN", "from-gh-token")
    files = project_files_from_env(_settings())
    assert isinstance(files, GitHubProjectFiles) and files.token == "from-gh-token"
    assert files.repositories["braveheart-selfplay"] == "Braveheart-Chess/braveheart-selfplay"


def test_registry_ids_come_from_the_onboarding_registry() -> None:
    settings = _settings()
    ids = project_registry_ids(settings)
    assert ids["braveheart-databricks"] == RegistryIds(
        "Braveheart-Chess/braveheart-databricks", "20000009", "10000003"
    )
    assert ids["braveheart-selfplay"] == RegistryIds(
        "Braveheart-Chess/braveheart-selfplay", "20000007", "10000003"
    )
    assert ids["pi-prover"] == RegistryIds("Pi-Mathematical-Reasoning/pi", "20000011", "10000004")
    assert {key: i.repository for key, i in ids.items()} == project_repositories(settings)


def test_a_site_is_not_a_platform_project() -> None:
    """Sites own and read no datasets, so the platform never reads their files."""
    settings = _settings()
    sites = {key for key, p in settings.projects.items() if p.type == "site"}
    assert sites == {"main-site", "cs-survival-guide", "guitar-knowledge-base"}
    assert not sites & set(project_registry_ids(settings))
