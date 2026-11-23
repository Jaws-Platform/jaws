"""The product holds no value that identifies the platform's owner.

The values come from config/ at run time, so this file holds none itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from jaws.settings import load_document
from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: Addresses the product's tests use as placeholders.
PLACEHOLDER_EMAIL = "owner@example.com"


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return [node] if isinstance(node, str) else []


def _ids(node: Any) -> set[str]:
    """Every owner_id and repository_id anywhere in the document."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("owner_id", "repository_id") and isinstance(value, str):
                found.add(value)
            found |= _ids(value)
    elif isinstance(node, list):
        for value in node:
            found |= _ids(value)
    return found


def owner_values() -> set[str]:
    """The values in config/ that identify the owner (not the vendor's own name,
    `context.organization`, which stays until the hub exists)."""
    document = load_document(PLATFORM_CONFIG_DIR)
    values: set[str] = set()
    for account in document["aws"]["accounts"].values():
        values.add(account["account_id"])
        if "admin_role_arn" in account:
            values.add(account["admin_role_arn"])
    values.add(document["context"]["owner"])
    values |= {document["dns"]["zone"], document["dns"]["zone_id"]}
    databricks = document["databricks"]
    values |= {databricks["account_id"], databricks["client_id"]}
    values.add(urlparse(databricks["shared_host_url"]).netloc)
    for text in _strings(document):
        values |= set(EMAIL.findall(text))
    values |= _ids(document)
    values.discard(PLACEHOLDER_EMAIL)
    return {v for v in values if v}


def _scanned_files() -> list[Path]:
    """Every text file the product ships or tests with, but this directory's."""
    roots = [REPO_ROOT / "src" / "jaws", REPO_ROOT / "tests", REPO_ROOT / "foundation" / "tests"]
    files: list[Path] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(REPO_ROOT).parts
            if (
                not path.is_file()
                or "__pycache__" in relative
                or relative[:2] == ("tests", "platform")
            ):
                continue
            try:
                path.read_text()
            except UnicodeDecodeError:
                continue
            files.append(path)
    return files


@pytest.mark.parametrize(
    "path", _scanned_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_no_product_file_holds_an_owner_value(path: Path) -> None:
    text = path.read_text()
    found = sorted(value for value in owner_values() if value in text)
    if found:
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)} holds {len(found)} values from config/ "
            "that identify the owner",
            pytrace=False,
        )
