"""`jaws platform check`: a hub's pins and identity agree with its configuration."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from jaws import cli
from jaws.platform import check_hub
from jaws.settings import Settings, load_settings
from tests.conftest import fixture_config
from tests.test_foundation_fixtures import HUB, HUB_REPOSITORY

runner = CliRunner()
DIGEST = "sha256:" + "a" * 64
CALLER = """on: {workflow_call: {}}
jobs:
  plan:
    uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@%(ref)s
    with:
      platform-image: %(image)s
      account-id: "%(account)s"
      name-root: jaws
      check-prefix: jaws
"""
WORKFLOW = ".github/workflows/site-plan.yml"


def _hub(tmp_path: Path, ref: str = "v0.81.0", **values: str) -> Path:
    """A hub checkout: a Dockerfile pinning v0.81.0 and one caller of site-plan.yml."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Dockerfile").write_text(
        f"FROM public.ecr.aws/example-alias/jaws:v0.81.0@{DIGEST}\nRUN true\n"
    )
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    given = {"image": "jaws-platform", "account": "222222222222", **values}
    (workflows / "site-plan.yml").write_text(CALLER % {"ref": ref, **given})
    return tmp_path


def _config() -> dict[str, object]:
    raw = fixture_config()
    raw["platform"]["repositories"].append(dict(HUB_REPOSITORY))
    raw["platform"]["hub"] = dict(HUB)
    return raw


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_config(), sort_keys=False))
    return path


def _settings() -> Settings:
    return load_settings(_config_file(Path(tempfile.mkdtemp())), environ={})


def _problems(root: Path, version: str = "0.81.0") -> list[tuple[str, str]]:
    found = check_hub(root, _settings(), version, "Example-Hub/platform")
    return [(p.path, p.message) for p in found]


def test_a_hub_whose_pins_and_identity_agree_passes(tmp_path: Path) -> None:
    assert check_hub(_hub(tmp_path), _settings(), "0.81.0", "Example-Hub/platform") == []


def test_a_pin_that_disagrees_fails_the_check(tmp_path: Path) -> None:
    [(path, message)] = _problems(_hub(tmp_path / "hub", ref="v0.80.1"))
    assert path == WORKFLOW
    assert "v0.80.1" in message
    assert "v0.81.0" in message


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"image": "jaws-cli"}, "platform-image: 'jaws-cli'"),
        ({"account": "333333333333"}, "account-id: '333333333333'"),
        ({"image": "${{ vars.PLATFORM_IMAGE }}"}, "platform-image as an expression"),
    ],
)
def test_an_identity_that_disagrees_fails_the_check(
    tmp_path: Path, values: dict[str, str], expected: str
) -> None:
    [(path, message)] = _problems(_hub(tmp_path / "hub", **values))
    assert path == WORKFLOW
    assert expected in message


def test_an_unquoted_identity_fails_the_check(tmp_path: Path) -> None:
    root = _hub(tmp_path / "hub")
    file = root / WORKFLOW
    file.write_text(file.read_text().replace('"222222222222"', "222222222222"))
    [(_, message)] = _problems(root)
    assert "pass account-id as a quoted string" in message


def test_a_dockerfile_without_a_digest_fails_the_check(tmp_path: Path) -> None:
    root = _hub(tmp_path / "hub")
    (root / "Dockerfile").write_text("FROM public.ecr.aws/example-alias/jaws:v0.81.0\n")
    [(path, message)] = _problems(root)
    assert path == "Dockerfile"
    assert message.startswith("FROM must pin the Jaws image by tag and digest")
    assert "'FROM public.ecr.aws/example-alias/jaws:v0.81.0'" in message


def test_an_image_of_another_release_fails_the_check(tmp_path: Path) -> None:
    [(path, message)] = _problems(_hub(tmp_path / "hub"), version="0.80.1")
    assert path == "Dockerfile"
    assert message == (
        "the Dockerfile pins v0.81.0, but the image it built runs Jaws v0.80.1: "
        "its digest is another release's"
    )


def test_a_caller_without_its_identity_fails_the_check(tmp_path: Path) -> None:
    root = _hub(tmp_path / "hub")
    file = root / WORKFLOW
    file.write_text(file.read_text().replace("      name-root: jaws\n", ""))
    assert _problems(root) == [
        (
            WORKFLOW,
            "job plan calls site-plan.yml without name-root: "
            "it would run as one of Jaws's own projects, not this platform's",
        )
    ]


def test_a_hub_with_no_caller_fails_the_check(tmp_path: Path) -> None:
    root = _hub(tmp_path / "hub")
    (root / WORKFLOW).write_text("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n")
    assert _problems(root) == [(".github/workflows", "no job calls a Jaws-Platform/jaws workflow")]


def test_a_hub_configured_for_another_repository_fails_the_check(tmp_path: Path) -> None:
    found = check_hub(_hub(tmp_path), _settings(), "0.81.0", "Other-Org/platform")
    assert [p.message for p in found] == [
        "platform.hub.repository is Example-Hub/platform, but this check runs in Other-Org/platform"
    ]


def test_a_hub_that_is_not_set_fails_the_check(tmp_path: Path) -> None:
    raw = fixture_config()
    raw["platform"].pop("hub", None)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False))
    found = check_hub(_hub(tmp_path / "hub"), load_settings(config, environ={}), "0.81.0", None)
    assert [p.message for p in found] == ["platform.hub is not set (config/platform.yaml)"]


def test_platform_check_exits_1_and_annotates_each_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _hub(tmp_path / "hub", ref="v0.80.1", image="jaws-cli")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Example-Hub/platform")
    monkeypatch.setattr(cli, "tool_version", lambda: "0.81.0")
    result = runner.invoke(
        cli.app,
        ["--config", str(_config_file(tmp_path)), "platform", "check", "--root", str(root)],
    )
    assert result.exit_code == 1
    annotations = [line for line in result.output.splitlines() if line.startswith("::error")]
    assert len(annotations) == 2
    assert all("title=Jaws::" in line for line in annotations)
    assert f"{WORKFLOW}: job plan calls Jaws-Platform/jaws at v0.80.1" in annotations[0]


def test_platform_check_passes_when_the_hub_agrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Example-Hub/platform")
    monkeypatch.setattr(cli, "tool_version", lambda: "0.81.0")
    result = runner.invoke(
        cli.app,
        [
            "--config",
            str(_config_file(tmp_path)),
            "platform",
            "check",
            "--root",
            str(_hub(tmp_path / "hub")),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "the hub's pins and identity agree: Jaws v0.81.0" in result.output
