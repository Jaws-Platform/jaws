"""scripts/retire_management.py: the checks that stand between the owner and a
deleted bucket. Everything here is pure; the AWS calls are the owner's run."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from tests.conftest import REPO_ROOT


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "retire_management", REPO_ROOT / "scripts" / "retire_management.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["retire_management"] = module
    spec.loader.exec_module(module)
    return module


rm = _script()
Obj = rm.Obj
NNUE = {"data/selfplay/": "positions", "data/nets/": "nets"}


def test_a_full_copy_has_no_problem() -> None:
    source = {"data/selfplay/a": Obj(3, "e1"), "data/nets/n": Obj(5, "e2")}
    destinations = {
        "positions": {"data/selfplay/a": Obj(3, "e1"), "data/selfplay/new": Obj(9, "e9")},
        "nets": {"data/nets/n": Obj(5, "e2")},
    }
    assert rm.compare(source, NNUE, destinations) == []


def test_a_missing_or_different_object_is_a_problem() -> None:
    source = {"data/selfplay/a": Obj(3, "e1"), "data/selfplay/b": Obj(4, "e2")}
    destinations = {"positions": {"data/selfplay/a": Obj(3, "other")}, "nets": {}}
    problems = rm.compare(source, NNUE, destinations)
    assert len(problems) == 2
    assert "data/selfplay/a" in problems[0] and "data/selfplay/b: missing" in problems[1]


def test_a_key_under_no_copied_prefix_is_a_problem() -> None:
    """Data the copies never covered must stop the run, not be deleted."""
    problems = rm.compare({"logs/x": Obj(1, "e")}, NNUE, {"positions": {}, "nets": {}})
    assert problems == ["logs/x: under no copied prefix"]


def test_every_old_data_bucket_has_a_route_for_each_prefix() -> None:
    for bucket, prefixes in rm.DATA_COPIES.items():
        assert bucket.startswith("jwall-engineering-")
        assert prefixes and all(d.startswith("jaws-") for d in prefixes.values())


def test_the_state_bucket_and_owner_access_are_never_deleted() -> None:
    doomed = (*rm.DATA_COPIES, *rm.DISCARDED_BUCKETS, *rm.SITE_BUCKETS)
    assert "jwall-engineering-tfstate" not in doomed
    assert rm.KEPT_STATE_PREFIX == "project=owner-access/"
    assert len(set(doomed)) == len(doomed)


def test_batches_are_at_most_a_thousand() -> None:
    items = [{"Key": str(i), "VersionId": "v"} for i in range(2500)]
    assert [len(b) for b in rm.batches(items)] == [1000, 1000, 500]


def test_the_foundation_is_retired_from_the_last_release_that_managed_it() -> None:
    assert rm.LAST_MANAGEMENT_RELEASE == "v0.69.0"
    assert rm.RELEASED_FROM_STATE == (
        "module.state_bucket",
        "module.zone",
        "module.spot_service_linked_role",
    )
