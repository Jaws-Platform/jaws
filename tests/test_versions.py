"""The composite action pins the image tag; Release Please bumps it with the
package version. The reusable workflows carry no version at all: they check
this repository out at `job.workflow_sha`, the commit of the reusable
workflow itself, and use the action from that checkout, so a site's one pin
(the workflow ref) selects the action and the image together.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from jaws import __version__
from tests.conftest import REPO_ROOT

ANNOTATION = "# x-release-please-version"
WORKFLOWS = ("site-plan.yml", "site-preview.yml", "site-deploy.yml")
LOCAL_ACTION = "uses: ./.jaws-tool/.github/actions/jaws"


def _annotated_versions(path: Path) -> list[str]:
    versions = []
    for line in path.read_text().splitlines():
        if ANNOTATION in line:
            match = re.search(r"v?(\d+\.\d+\.\d+)", line.split(ANNOTATION)[0])
            assert match, f"{path}: annotated line has no version: {line!r}"
            versions.append(match.group(1))
    return versions


def _extra_file_paths() -> set[str]:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text())
    return {
        entry if isinstance(entry, str) else entry["path"]
        for entry in config["packages"]["."]["extra-files"]
    }


def test_release_please_tracks_every_annotated_file() -> None:
    annotated = {
        str(p.relative_to(REPO_ROOT))
        for p in [*REPO_ROOT.glob(".github/**/*.yml"), *REPO_ROOT.glob("src/**/*.py")]
        if ANNOTATION in p.read_text()
    }
    assert annotated == _extra_file_paths()


def test_no_workflow_carries_a_version_literal() -> None:
    """The release bot cannot commit under .github/workflows/, and must not need to."""
    for rel in _extra_file_paths():
        assert not rel.startswith(".github/workflows/"), rel


def test_annotated_versions_match_the_package_version() -> None:
    for rel in _extra_file_paths():
        versions = _annotated_versions(REPO_ROOT / rel)
        assert versions, f"{rel} has no annotated version"
        assert set(versions) == {__version__}, f"{rel}: {versions} != {__version__}"


def test_action_yml_uses_the_generic_updater() -> None:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text())
    yaml_entries = [
        e
        for e in config["packages"]["."]["extra-files"]
        if (e if isinstance(e, str) else e["path"]).endswith((".yml", ".yaml"))
    ]
    assert yaml_entries, "action.yml must be an extra-file"
    assert all(isinstance(e, dict) and e["type"] == "generic" for e in yaml_entries), (
        "a .yml extra-file given as a plain string gets the YAML ($.version) updater"
    )


def test_workflows_use_the_action_from_their_own_commit() -> None:
    for name in WORKFLOWS:
        text = (REPO_ROOT / ".github" / "workflows" / name).read_text()
        assert "ref: ${{ job.workflow_sha }}" in text, name
        assert LOCAL_ACTION in text, name
        assert "jaws@v" not in text, f"{name} pins the action by tag"


#: A module block's pin: the family's registry address, the submodule (none for a
#: family's root module) and the exact version.
_MODULE_PIN = re.compile(
    r'source\s*=\s*"(?P<family>jwallace145/[a-z0-9-]+/aws)(?://modules/(?P<module>[a-z0-9-]+))?"'
    r'\s*\n\s*version\s*=\s*"(?P<version>[^"]+)"'
)
#: The library the families were split from. Nothing may pin it any more.
_OLD_LIBRARY = "jwallace145/jwall-engineering/aws"


def _families() -> dict[str, str]:
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    families: dict[str, str] = config["library"]["families"]
    return families


def _pins(*paths: Path) -> list[tuple[str, str | None, str]]:
    return [
        (m.group("family"), m.group("module"), m.group("version"))
        for path in paths
        for m in _MODULE_PIN.finditer(path.read_text())
    ]


def _stack_files() -> list[Path]:
    """Every Terraform file that calls a registry module."""
    return [
        *(REPO_ROOT / "foundation").glob("*.tf"),
        *(REPO_ROOT / "stacks").glob("*/*.tf"),
        *(REPO_ROOT / "owner-access").glob("*.tf"),
        *(REPO_ROOT / "data-access").glob("*.tf"),
    ]


def test_site_stack_pins_the_static_site_family_root() -> None:
    """stacks/site is the root module of the static-site family, like any consumer's."""
    pins = _pins(REPO_ROOT / "stacks" / "site" / "main.tf")
    family = "jwallace145/jaws-static-site/aws"
    assert pins == [(family, None, _families()[family])], (
        "stacks/site/main.tf must pin the static-site family's root module, and nothing else"
    )


def test_bot_stack_pins_each_module_at_its_family_version() -> None:
    families = _families()
    pins = _pins(REPO_ROOT / "stacks" / "bot" / "main.tf")
    assert sorted((family, module) for family, module, _ in pins) == [
        ("jwallace145/jaws-foundation/aws", "private-bucket"),  # records
        ("jwallace145/jaws-foundation/aws", "private-bucket"),  # task results
        ("jwallace145/jaws-lichess-bot/aws", "container-instance"),
        ("jwallace145/jaws-lichess-bot/aws", "ecr-repository"),
        ("jwallace145/jaws-network/aws", "vpc"),
        ("jwallace145/jaws-research/aws", "dataset-bucket"),
        ("jwallace145/jaws-research/aws", "task-runner"),  # cpu
        ("jwallace145/jaws-research/aws", "task-runner"),  # the other profiles
    ]
    assert all(version == families[family] for family, _, version in pins)


def test_every_registry_pin_matches_config() -> None:
    """AGENTS.md: every pin of a module family moves together with its entry in
    library.families, and is an exact version."""
    families = _families()
    pins = _pins(*_stack_files())
    assert pins, "no registry module pins found"
    for family, module, version in pins:
        assert family in families, f"{family} (//modules/{module}) is not in library.families"
        assert version == families[family], (
            f"{family}//modules/{module} is pinned at {version}, "
            f"but library.families says {families[family]}"
        )


def test_every_configured_family_is_used() -> None:
    """A family nothing pins is a stale line in config.yaml."""
    used = {family for family, _, _ in _pins(*_stack_files())}
    assert used == set(_families())


def test_nothing_pins_the_library_the_families_were_split_from() -> None:
    for path in _stack_files():
        assert _OLD_LIBRARY not in path.read_text(), path
