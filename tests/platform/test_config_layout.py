"""The owner's own configuration (config/): its file layout, and that it loads."""

from __future__ import annotations

import yaml

from jaws.settings import load_document, load_settings
from tests.conftest import CONFIG_DIR, PLATFORM_CONFIG_DIR

#: Which file of config/ holds each section. Workflows and scripts read some
#: sections from their file with yq, so a section moves only with its readers.
SECTION_FILES = {
    "aws": "aws.yaml",
    "projects": "projects.yaml",
    "state": "terraform.yaml",
    "context": "tool.yaml",
    "ecr": "tool.yaml",
    "dns": "sites.yaml",
    "platform": "platform.yaml",
    "bot": "bots.yaml",
    "tasks": "bots.yaml",
    "databricks": "databricks.yaml",
    "monitoring": "monitoring.yaml",
}


def test_every_section_is_in_its_file() -> None:
    found = {
        section: path.name
        for path in sorted(PLATFORM_CONFIG_DIR.glob("*.yaml"))
        for section in yaml.safe_load(path.read_text())
    }
    assert found == SECTION_FILES


def test_the_owner_s_configuration_loads() -> None:
    assert load_settings(PLATFORM_CONFIG_DIR, environ={}).projects


def test_the_fixture_has_every_section_the_owner_uses() -> None:
    assert set(load_document(CONFIG_DIR)) == set(load_document(PLATFORM_CONFIG_DIR))
