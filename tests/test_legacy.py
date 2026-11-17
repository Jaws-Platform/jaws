"""The names the tool had before it was called Jaws keep working, and say so.

A consumer moves in its own pull request, so until the last one has, the old
project file name, the old `JES_*` variables and the old command are honoured.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from jaws import cli
from jaws.access import GitHubProjectFiles
from jaws.errors import ConfigError
from jaws.legacy import (
    LEGACY_SITE_FILE,
    adopt_legacy_environment,
    announce,
    notices,
    resolve_project_file,
)
from tests.conftest import FIXTURES

runner = CliRunner()
OLD_NAME = "jwall-engineering-sites.yaml"
API = "https://api.github.com/repos/Braveheart-Chess/braveheart-selfplay/contents"
PROJECT_FILE = (FIXTURES / "registry" / "braveheart-selfplay.yaml").read_text()


# -- the project file ---------------------------------------------------------------


def test_the_old_file_name_is_the_one_consumers_have_today() -> None:
    assert LEGACY_SITE_FILE.name == OLD_NAME


def test_jaws_yaml_is_read_when_it_is_the_only_file(tmp_path: Path) -> None:
    (tmp_path / "jaws.yaml").write_text("x")
    assert resolve_project_file(tmp_path / "jaws.yaml") == tmp_path / "jaws.yaml"


def test_the_old_name_is_read_when_jaws_yaml_is_absent(tmp_path: Path) -> None:
    (tmp_path / OLD_NAME).write_text("x")
    assert resolve_project_file(tmp_path / "jaws.yaml") == tmp_path / OLD_NAME


def test_both_names_together_are_refused(tmp_path: Path) -> None:
    (tmp_path / "jaws.yaml").write_text("x")
    (tmp_path / OLD_NAME).write_text("x")
    with pytest.raises(ConfigError, match=r"delete it and keep jaws\.yaml"):
        resolve_project_file(tmp_path / "jaws.yaml")


def test_with_neither_file_the_error_will_name_jaws_yaml(tmp_path: Path) -> None:
    assert resolve_project_file(tmp_path / "jaws.yaml") == tmp_path / "jaws.yaml"


def test_a_file_given_by_another_name_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / OLD_NAME).write_text("x")
    assert resolve_project_file(tmp_path / "braveheart.yaml") == tmp_path / "braveheart.yaml"


def test_a_command_runs_from_the_old_file_and_warns_on_stderr_only(workspace: Path) -> None:
    (workspace / "jaws.yaml").rename(workspace / OLD_NAME)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.output
    # stdout is still exactly the command's own output: callers parse it.
    assert json.loads(result.stdout)["context"]["organization"] == "jwall-engineering"
    assert f"warning: {OLD_NAME} is the project file's old name" in result.stderr
    assert "rename it to jaws.yaml" in result.stderr


def test_the_old_file_is_validated_like_the_new_one(workspace: Path, fake_terraform: Path) -> None:
    (workspace / "jaws.yaml").rename(workspace / OLD_NAME)
    result = runner.invoke(cli.app, ["validate"])
    assert result.exit_code == 0, result.output
    assert "stack validates" in result.stdout


def test_a_command_with_both_files_exits_2(workspace: Path) -> None:
    (workspace / OLD_NAME).write_text((workspace / "jaws.yaml").read_text())
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 2
    assert "delete it and keep jaws.yaml" in result.stderr


def test_a_current_consumer_gets_no_warning(workspace: Path) -> None:
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert result.stderr == ""


# -- environment variables ----------------------------------------------------------


def test_an_old_variable_is_adopted_under_its_new_name() -> None:
    env = {"JES_LOG_LEVEL": "debug", "PATH": "/bin"}
    assert adopt_legacy_environment(env) == ["JES_LOG_LEVEL"]
    assert env["JAWS_LOG_LEVEL"] == "debug"


def test_the_new_name_wins_when_both_are_set() -> None:
    env = {"JES_LOG_LEVEL": "debug", "JAWS_LOG_LEVEL": "error"}
    assert adopt_legacy_environment(env) == []
    assert env["JAWS_LOG_LEVEL"] == "error"


def test_a_command_honours_an_old_variable_and_says_so(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JES_CONFIG still chooses the configuration file: a missing one is exit 2."""
    monkeypatch.setenv("JES_CONFIG", str(workspace / "missing.yaml"))
    monkeypatch.delenv("JAWS_CONFIG", raising=False)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 2
    assert "missing.yaml" in result.stderr


def test_the_notice_names_each_variable_to_rename() -> None:
    (notice,) = notices(Path("jaws.yaml"), ["JES_HEAD_SHA", "JES_LOG_LEVEL"])
    assert "JES_HEAD_SHA to JAWS_HEAD_SHA" in notice
    assert "JES_LOG_LEVEL to JAWS_LOG_LEVEL" in notice


def test_notices_are_annotations_in_github_actions(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    announce(["rename the file"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "::warning title=Jaws::rename the file\n"


# -- another project's file, read from GitHub ---------------------------------------


class RoutedOpener:
    """Stands in for urlopen: answers each URL with its own reply, 404 otherwise."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        url = request.full_url
        self.urls.append(url)
        reply = self.replies.get(
            url, urllib.error.HTTPError(url, 404, "Not Found", Message(), None)
        )
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


def _contents(text: str, sha: str) -> dict[str, str]:
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64", "sha": sha}


def _files(opener: RoutedOpener) -> GitHubProjectFiles:
    return GitHubProjectFiles(
        {"braveheart-selfplay": "Braveheart-Chess/braveheart-selfplay"}, None, opener
    )


def test_a_counterpart_that_has_not_renamed_its_file_is_still_read() -> None:
    opener = RoutedOpener({f"{API}/{OLD_NAME}": _contents(PROJECT_FILE, "old")})
    files = _files(opener)
    assert files.load("braveheart-selfplay").project == "braveheart-selfplay"
    assert opener.urls == [f"{API}/jaws.yaml", f"{API}/{OLD_NAME}"]
    assert files.shas == {"braveheart-selfplay": "old"}


def test_a_counterpart_with_jaws_yaml_is_read_in_one_request() -> None:
    opener = RoutedOpener({f"{API}/jaws.yaml": _contents(PROJECT_FILE, "new")})
    files = _files(opener)
    files.load("braveheart-selfplay")
    assert opener.urls == [f"{API}/jaws.yaml"]
    assert files.shas == {"braveheart-selfplay": "new"}


def test_with_neither_file_the_error_names_jaws_yaml() -> None:
    with pytest.raises(ConfigError) as caught:
        _files(RoutedOpener({})).load("braveheart-selfplay")
    assert f"{API}/jaws.yaml" in str(caught.value)
    assert OLD_NAME not in str(caught.value)


@pytest.mark.parametrize(
    "reply",
    [
        urllib.error.HTTPError(f"{API}/{OLD_NAME}", 403, "Forbidden", Message(), None),
        urllib.error.URLError("network is unreachable"),
        {"message": "API rate limit exceeded"},  # no content
    ],
)
def test_an_old_file_that_cannot_be_read_is_an_error_not_an_absence(reply: Any) -> None:
    """Falling back must never turn an outage into "this project has no file"."""
    with pytest.raises(ConfigError) as caught:
        _files(RoutedOpener({f"{API}/{OLD_NAME}": reply})).load("braveheart-selfplay")
    assert f"{API}/{OLD_NAME}" in str(caught.value)


def test_a_failure_other_than_not_found_does_not_fall_back() -> None:
    opener = RoutedOpener(
        {
            f"{API}/jaws.yaml": urllib.error.HTTPError(
                f"{API}/jaws.yaml", 403, "Forbidden", Message(), None
            ),
            f"{API}/{OLD_NAME}": _contents(PROJECT_FILE, "old"),
        }
    )
    with pytest.raises(ConfigError, match=r"jaws\.yaml"):
        _files(opener).load("braveheart-selfplay")
    assert opener.urls == [f"{API}/jaws.yaml"]


# -- the command ----------------------------------------------------------------------


def test_both_command_names_run_the_same_cli() -> None:
    scripts = {
        e.name: e.value
        for e in entry_points(group="console_scripts")
        if e.dist is not None and e.dist.name == "jaws"
    }
    assert scripts == {"jaws": "jaws.cli:app", "jwall-engineering-sites": "jaws.cli:app"}
