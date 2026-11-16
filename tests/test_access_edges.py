"""Edges: a dataset is read only when its registry file, the producer's
`consumers` and the consumer's `reads` all agree. Anything less is pending."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from jwall_engineering_sites.access import Access, Edge, OnboardedDataset, Pending, compute_access
from jwall_engineering_sites.errors import ConfigError
from jwall_engineering_sites.site import SiteConfig, site_config_from_text
from tests.conftest import FIXTURES

POSITIONS = OnboardedDataset(
    owner="braveheart-selfplay", name="positions", prefix="data/", description="positions"
)
PURPOSE = "generation-over-generation self-play analysis"
PRODUCER_MISSING = "the producer does not list the consumer"
CONSUMER_MISSING = "the consumer does not read the dataset"
NOT_ONBOARDED = "the dataset is not onboarded"


def _file(project: str, change: Callable[[dict[str, Any]], None] | None = None) -> SiteConfig:
    data: dict[str, Any] = yaml.safe_load((FIXTURES / "registry" / f"{project}.yaml").read_text())
    if change is not None:
        change(data)
    return site_config_from_text(yaml.safe_dump(data), project)


def _producer(listed: bool) -> SiteConfig:
    def change(data: dict[str, Any]) -> None:
        dataset = next(c for c in data["components"] if c["kind"] == "dataset")
        dataset["consumers"] = ["braveheart-databricks"] if listed else []

    return _file("braveheart-selfplay", change)


def _consumer(reads: bool) -> SiteConfig:
    def change(data: dict[str, Any]) -> None:
        workspace = next(c for c in data["components"] if c["kind"] == "databricks-workspace")
        if not reads:
            workspace.pop("reads", None)

    return _file("braveheart-databricks", change)


@pytest.mark.parametrize(
    ("onboarded", "listed", "reads", "edges", "reason"),
    [
        (True, True, True, 1, None),
        (True, False, True, 0, PRODUCER_MISSING),
        (True, True, False, 0, CONSUMER_MISSING),
        (False, True, True, 0, NOT_ONBOARDED),
    ],
)
def test_edges_need_all_three_halves(
    onboarded: bool, listed: bool, reads: bool, edges: int, reason: str | None
) -> None:
    access = compute_access(
        [POSITIONS] if onboarded else [],
        {"braveheart-selfplay": _producer(listed), "braveheart-databricks": _consumer(reads)},
    )
    if edges:
        assert access.edges == (Edge(POSITIONS, "braveheart-databricks", PURPOSE),)
        assert access.pending == ()
    else:
        assert access.edges == ()
        assert access.pending == (
            Pending(
                "braveheart-selfplay/positions",
                "braveheart-selfplay",
                "braveheart-databricks",
                str(reason),
            ),
        )


def test_a_pair_whose_other_file_was_not_read_is_not_judged() -> None:
    # A consumer's own plan reads only its producers' files; another workspace
    # the producer lists is not this plan's to judge, so it is neither an edge
    # nor pending here (the platform-wide reconcile reads every file).
    access = compute_access([POSITIONS], {"braveheart-selfplay": _producer(True)})
    assert access == Access(edges=(), pending=())


def test_an_onboarded_dataset_the_owner_does_not_declare_is_an_error() -> None:
    nets = OnboardedDataset(
        owner="braveheart-selfplay", name="nets", prefix="data/", description="d"
    )
    with pytest.raises(ConfigError, match=re.escape("datasets/braveheart-selfplay/nets.yaml")):
        compute_access([nets], {"braveheart-selfplay": _producer(True)})


@pytest.mark.parametrize(
    ("prefix", "ok"), [("other/", False), ("data/selfplay/", True), ("data/", True)]
)
def test_a_registry_prefix_outside_the_component_is_an_error(prefix: str, ok: bool) -> None:
    dataset = OnboardedDataset(
        owner="braveheart-selfplay", name="positions", prefix=prefix, description="d"
    )
    files = {"braveheart-selfplay": _producer(True), "braveheart-databricks": _consumer(True)}
    if ok:
        assert len(compute_access([dataset], files).edges) == 1
    else:
        with pytest.raises(
            ConfigError, match=re.escape("datasets/braveheart-selfplay/positions.yaml")
        ):
            compute_access([dataset], files)


def test_access_answers_who_shares_and_who_consumes() -> None:
    access = compute_access(
        [POSITIONS],
        {"braveheart-selfplay": _producer(True), "braveheart-databricks": _consumer(True)},
    )
    assert access.shared("braveheart-selfplay", "positions")
    assert not access.shared("braveheart-selfplay", "nets")
    assert not access.shared("braveheart-trainer", "positions")
    assert access.consumed_by("braveheart-databricks") == access.edges
    assert access.consumed_by("databricks-poc") == ()
