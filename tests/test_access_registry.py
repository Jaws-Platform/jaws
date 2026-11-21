"""The dataset registry: one file per onboarded dataset, datasets/<owner>/<name>.yaml.

The path is the id; the bucket, the location URL and the platform name (role,
credential and location) are derived from it. A misplaced or malformed file is
refused with its path, never skipped: onboarding is what the platform creates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jaws.access import infra_root, load_registry
from jaws.errors import ConfigError
from tests.conftest import FIXTURES

GOOD = "description: Braveheart self-play positions and label sets\nprefix: data/\n"


def write(path: Path, text: str = GOOD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_a_registry_file_is_its_id(tmp_path: Path) -> None:
    write(tmp_path / "braveheart-selfplay" / "positions.yaml", "description: d\nprefix: data/\n")
    (d,) = load_registry(tmp_path)
    assert (d.id, d.key) == ("braveheart-selfplay/positions", "braveheart-selfplay-positions")
    assert d.platform_name("jaws") == "jaws-ds-braveheart-selfplay-positions"
    assert d.bucket("jaws") == "jaws-braveheart-selfplay-positions"
    assert d.url("jaws") == "s3://jaws-braveheart-selfplay-positions/data"
    assert d.role_arn("570327089884", "jaws") == (
        "arn:aws:iam::570327089884:role/jaws-ds-braveheart-selfplay-positions"
    )
    assert (d.prefix, d.description) == ("data/", "d")


def test_as_dict_is_what_the_foundation_derives(tmp_path: Path) -> None:
    write(tmp_path / "braveheart-selfplay" / "positions.yaml", "description: d\nprefix: data/v1/\n")
    (d,) = load_registry(tmp_path)
    assert d.as_dict("jaws") == {
        "id": "braveheart-selfplay/positions",
        "owner": "braveheart-selfplay",
        "name": "positions",
        "prefix": "data/v1/",
        "description": "d",
        "platform_name": "jaws-ds-braveheart-selfplay-positions",
        "bucket": "jaws-braveheart-selfplay-positions",
        "url": "s3://jaws-braveheart-selfplay-positions/data/v1",
        "catalog": "braveheart_selfplay",
        "schema": "positions",
        "volume": "files",
    }


def test_datasets_come_back_sorted_by_id(tmp_path: Path) -> None:
    write(tmp_path / "zeta" / "a.yaml")
    write(tmp_path / "alpha" / "z.yaml")
    write(tmp_path / "alpha" / "b.yaml")
    assert [d.id for d in load_registry(tmp_path)] == ["alpha/b", "alpha/z", "zeta/a"]


@pytest.mark.parametrize(
    "rel",
    [
        "Braveheart/positions.yaml",
        "a/Positions.yaml",
        "a/positions.yml",
        "a/v1/positions.yaml",
        "notes.txt",
        "a/notes.txt",
    ],
)
def test_a_misplaced_file_is_refused(tmp_path: Path, rel: str) -> None:
    write(tmp_path / rel)
    with pytest.raises(ConfigError, match=re.escape(rel)):
        load_registry(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        "prefix: data/\n",  # no description
        "description: d\n",  # no prefix
        "description: d\nprefix: data/\nowner: x\n",  # an extra key
        'description: ""\nprefix: data/\n',  # an empty description
        "description: '   '\nprefix: data/\n",  # a blank description
        "description: d\nprefix: data\n",  # a prefix without its trailing slash
        "description: d\nprefix: /data/\n",  # a leading slash
        "- description: d\n",  # not a mapping
        "description: [unclosed\n",  # not YAML
    ],
)
def test_keys_must_be_exactly_description_and_prefix(tmp_path: Path, text: str) -> None:
    write(tmp_path / "a" / "b.yaml", text)
    with pytest.raises(ConfigError, match=re.escape("a/b.yaml")):
        load_registry(tmp_path)


def test_a_key_over_40_characters_is_refused(tmp_path: Path) -> None:
    owner, name = "o" * 20, "n" * 20  # "<owner>-<name>" is 41 characters
    write(tmp_path / owner / f"{name}.yaml")
    with pytest.raises(ConfigError, match="41"):
        load_registry(tmp_path)


def test_a_key_of_exactly_40_characters_is_accepted(tmp_path: Path) -> None:
    owner, name = "o" * 20, "n" * 19  # 40 characters
    write(tmp_path / owner / f"{name}.yaml")
    (d,) = load_registry(tmp_path)
    assert len(d.key) == 40


def test_two_ids_with_one_key_are_refused(tmp_path: Path) -> None:
    write(tmp_path / "a-b" / "c.yaml")
    write(tmp_path / "a" / "b-c.yaml")
    with pytest.raises(ConfigError) as caught:
        load_registry(tmp_path)
    assert "a-b/c" in str(caught.value) and "a/b-c" in str(caught.value)


def test_the_readme_is_allowed_and_a_missing_directory_is_empty(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "# Onboarded datasets\n")
    write(tmp_path / "braveheart-selfplay" / "positions.yaml")
    assert [d.id for d in load_registry(tmp_path)] == ["braveheart-selfplay/positions"]
    assert load_registry(tmp_path / "nothing-here") == ()


def test_infra_root_is_the_env_override_else_the_configs_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(tmp_path / "checkout"))
    assert infra_root() == tmp_path / "checkout"
    monkeypatch.delenv("JAWS_INFRA_ROOT")
    monkeypatch.setenv("JAWS_CONFIG", str(tmp_path / "elsewhere" / "config.yaml"))
    assert infra_root() == tmp_path / "elsewhere"


def test_python_and_terraform_derive_the_same_registry() -> None:
    """foundation/registry's terraform test asserts the same file for the same fixtures."""
    expected = json.loads((FIXTURES / "datasets-expected.json").read_text())
    derived = {d.key: d.as_dict("jaws") for d in load_registry(FIXTURES / "datasets")}
    assert derived == expected
