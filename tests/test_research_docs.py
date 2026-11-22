"""docs/research-projects.md shows the sample the tests load, not a drifted copy."""

from __future__ import annotations

import re
from typing import Any

import yaml

from jaws.settings import ProjectGuardrails
from tests.conftest import FIXTURES, MATH_PROVER_GUARDRAILS, REPO_ROOT


def _yaml_blocks() -> list[Any]:
    text = (REPO_ROOT / "docs" / "research-projects.md").read_text()
    return [yaml.safe_load(b) for b in re.findall(r"^```yaml\n(.*?)^```$", text, re.M | re.S)]


def test_the_docs_sample_is_the_fixture() -> None:
    fixture = yaml.safe_load((FIXTURES / "bots" / "math-prover.yaml").read_text())
    assert [b for b in _yaml_blocks() if b.get("project") == "math-prover"] == [fixture]


def test_the_docs_central_entry_is_the_one_the_tests_approve() -> None:
    """The sample's entry in config/projects.yaml, under its GitHub owner: its
    guardrails are the ones the tests approve, and it is a research project."""
    entries = [
        group["projects"]["math-prover"]
        for b in _yaml_blocks()
        for group in (b.get("projects") or {}).values()
        if isinstance(group, dict) and "math-prover" in (group.get("projects") or {})
    ]
    approved = [
        ProjectGuardrails.model_validate(
            {k: v for k, v in e.items() if k in ProjectGuardrails.model_fields}
        )
        for e in entries
    ]
    assert approved == [MATH_PROVER_GUARDRAILS]
    assert [e["type"] for e in entries] == ["research"]
