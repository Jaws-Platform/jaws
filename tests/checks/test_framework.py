from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

import pytest

from jwall_engineering_sites.checks.framework import (
    CheckContext,
    CheckResult,
    Outcome,
    Severity,
    Stage,
    check,
    raise_on_errors,
    registered,
    run_stage,
)
from jwall_engineering_sites.checks.render import console_table, markdown_table, write_json
from jwall_engineering_sites.errors import PreflightError
from jwall_engineering_sites.project import Project
from jwall_engineering_sites.settings import Settings

ALL = frozenset({"site", "bot", "research", "databricks"})


def _ctx(project: Project, settings: Settings, logger: logging.Logger) -> CheckContext:
    return CheckContext(
        project=project, settings=settings, logger=logger, session=None, databricks=None
    )


def _result(
    check_id: str = "DBX-CFG-001",
    outcome: Outcome = Outcome.FAIL,
    severity: Severity = Severity.ERROR,
    remediation: str | None = "Fix it",
    runbook: str | None = "docs/databricks.md#fix",
    facts: dict[str, str] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        title="A title",
        outcome=outcome,
        severity=severity,
        facts=facts or {},
        remediation=remediation,
        runbook=runbook,
    )


def _passing(check_id: str, title: str = "t") -> CheckResult:
    return CheckResult(check_id, title, Outcome.PASS, Severity.ERROR, {}, None, None)


def test_registry_orders_by_id() -> None:
    for cid in ("DBX-NET-002", "DBX-CFG-009", "DBX-CFG-001"):

        @check(cid, "t", Stage.CONFIG, ALL)
        def _fn(ctx: CheckContext, cid: str = cid) -> Iterable[CheckResult]:
            return [_passing(cid)]

    assert [r.check_id for r in registered(Stage.CONFIG, "databricks")] == [
        "DBX-CFG-001",
        "DBX-CFG-009",
        "DBX-NET-002",
    ]


def test_duplicate_id_rejected() -> None:
    @check("DBX-CFG-001", "t", Stage.CONFIG, ALL)
    def first(ctx: CheckContext) -> Iterable[CheckResult]:
        return []

    with pytest.raises(ValueError, match="DBX-CFG-001"):

        @check("DBX-CFG-001", "again", Stage.LIVE, ALL)
        def second(ctx: CheckContext) -> Iterable[CheckResult]:
            return []


@pytest.mark.parametrize(
    "bad", ["dbx-cfg-001", "DBX-CFG-1", "D-CFG-001", "DBX_CFG_001", "DBXXXX-CFG-001"]
)
def test_malformed_id_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="check id"):
        check(bad, "t", Stage.CONFIG, ALL)


def test_isolated_registry_does_not_leak() -> None:
    @check("DBX-CFG-001", "t", Stage.CONFIG, ALL)
    def fn(ctx: CheckContext) -> Iterable[CheckResult]:
        return []

    from jwall_engineering_sites.checks.framework import isolated_registry

    with isolated_registry():
        assert registered(Stage.CONFIG, "databricks") == []
    assert len(registered(Stage.CONFIG, "databricks")) == 1


def test_check_exception_becomes_fail_not_crash(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    @check("DBX-CFG-001", "Boom", Stage.CONFIG, ALL, runbook="docs/databricks.md#boom")
    def boom(ctx: CheckContext) -> Iterable[CheckResult]:
        raise RuntimeError("kaboom | with pipe")

    @check("DBX-CFG-002", "Fine", Stage.CONFIG, ALL)
    def fine(ctx: CheckContext) -> Iterable[CheckResult]:
        return [_passing("DBX-CFG-002", "Fine")]

    results = run_stage(Stage.CONFIG, _ctx(bot, settings, logger))
    assert [r.check_id for r in results] == ["DBX-CFG-001", "DBX-CFG-002"]
    failed = results[0]
    assert failed.outcome is Outcome.FAIL
    assert failed.severity is Severity.ERROR
    assert failed.title == "Boom"
    assert failed.runbook == "docs/databricks.md#boom"
    assert failed.facts["error"] == "RuntimeError"  # the message may quote a credential
    assert results[1].outcome is Outcome.PASS


def test_warning_failure_does_not_raise() -> None:
    raise_on_errors([_result(severity=Severity.WARNING)])
    raise_on_errors([_result(outcome=Outcome.SKIP), _passing("DBX-CFG-002")])


def test_error_failure_raises_preflight_exit_3() -> None:
    with pytest.raises(PreflightError) as exc:
        raise_on_errors(
            [
                _result("DBX-CFG-001"),
                _result("DBX-CFG-002", severity=Severity.WARNING),
                _result("DBX-CFG-003"),
            ]
        )
    assert exc.value.exit_code == 3
    message = str(exc.value)
    assert "DBX-CFG-001" in message
    assert "DBX-CFG-003" in message
    assert "DBX-CFG-002" not in message


def test_kind_filtering(bot: Project, settings: Settings, logger: logging.Logger) -> None:
    ran: list[str] = []

    @check("SIT-CFG-001", "site only", Stage.CONFIG, frozenset({"site"}))
    def site_check(ctx: CheckContext) -> Iterable[CheckResult]:
        ran.append("site")
        return [_passing("SIT-CFG-001")]

    @check("DBX-CFG-001", "dbx", Stage.CONFIG, frozenset({"databricks"}))
    def dbx_check(ctx: CheckContext) -> Iterable[CheckResult]:
        ran.append("dbx")
        return [_passing("DBX-CFG-001")]

    assert [r.check_id for r in registered(Stage.CONFIG, "databricks")] == ["DBX-CFG-001"]
    assert [r.check_id for r in registered(Stage.CONFIG, "site")] == ["SIT-CFG-001"]
    assert registered(Stage.LIVE, "site") == []
    # the fixture project is a bot, so neither runs
    assert run_stage(Stage.CONFIG, _ctx(bot, settings, logger)) == []
    assert ran == []


def test_run_stage_runs_only_matching_kind(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    @check("BOT-CFG-001", "bot", Stage.CONFIG, frozenset({"bot"}))
    def bot_check(ctx: CheckContext) -> Iterable[CheckResult]:
        return [_passing("BOT-CFG-001")]

    assert [r.check_id for r in run_stage(Stage.CONFIG, _ctx(bot, settings, logger))] == [
        "BOT-CFG-001"
    ]


def test_markdown_table_has_remediation_and_link() -> None:
    md = markdown_table(
        [
            _result(remediation="Run `x` | then y\nand z", facts={"k": "a|b"}),
            _passing("DBX-CFG-002", "ok"),
        ]
    )
    lines = md.splitlines()
    assert lines[0].startswith("| ")
    assert "DBX-CFG-001" in md
    assert "Run `x` \\| then y and z" in md
    assert "docs/databricks.md#fix" in md
    assert "a\\|b" in md
    # every row has the same number of unescaped cells
    counts = {line.replace("\\|", "").count("|") for line in lines}
    assert len(counts) == 1


def test_console_table_lists_failures() -> None:
    out = console_table([_result(), _passing("DBX-CFG-002", "ok")])
    assert "DBX-CFG-001" in out and "FAIL" in out and "PASS" in out
    assert "Fix it" in out


def test_json_round_trip(tmp_path: Path) -> None:
    results = [
        _result(facts={"a": "1"}),
        _result("DBX-CFG-002", Outcome.SKIP, Severity.WARNING, None, None),
    ]
    path = tmp_path / ".jwall-engineering-sites" / "checks.json"
    write_json(results, path)
    data = json.loads(path.read_text())
    assert [
        CheckResult(**{**d, "outcome": Outcome(d["outcome"]), "severity": Severity(d["severity"])})
        for d in data
    ] == results


def test_partial_results_kept_before_crash(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    @check("BOT-CFG-001", "Partial", Stage.CONFIG, ALL)
    def partial(ctx: CheckContext) -> Iterable[CheckResult]:
        yield _passing("BOT-CFG-001", "first")
        raise RuntimeError("late")

    results = run_stage(Stage.CONFIG, _ctx(bot, settings, logger))
    assert [(r.title, r.outcome) for r in results] == [
        ("first", Outcome.PASS),
        ("Partial", Outcome.FAIL),
    ]
    assert results[1].facts["error"] == "RuntimeError"


def test_non_check_result_item_becomes_fail(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    @check("BOT-CFG-001", "Bad", Stage.CONFIG, ALL)
    def bad(ctx: CheckContext) -> Iterable[CheckResult]:
        yield _passing("BOT-CFG-001", "good")
        yield "oops"  # type: ignore[misc]

    results = run_stage(Stage.CONFIG, _ctx(bot, settings, logger))
    assert [r.outcome for r in results] == [Outcome.PASS, Outcome.FAIL]
    assert results[1].facts["error"] == "TypeError"
    markdown_table(results)  # renders without crashing


@pytest.mark.parametrize("kinds", [frozenset(), frozenset({"site", "bogus"})])
def test_bad_kinds_rejected(kinds: frozenset[str]) -> None:
    with pytest.raises(ValueError, match="kinds"):
        check("DBX-CFG-001", "t", Stage.CONFIG, kinds)


# -- requirements and the stage-scoped state ------------------------------------------


def _outcome(check_id: str, outcome: Outcome) -> CheckResult:
    return CheckResult(check_id, "t", outcome, Severity.ERROR, {}, None, None)


@pytest.mark.parametrize("first", [Outcome.FAIL, None], ids=["failed", "absent"])
def test_a_check_skips_when_its_requirement_did_not_pass(
    bot: Project, settings: Settings, logger: logging.Logger, first: Outcome | None
) -> None:
    ran: list[str] = []
    if first is not None:
        outcome = first

        @check("BOT-CFG-001", "Ready", Stage.CONFIG, ALL)
        def ready(ctx: CheckContext) -> Iterable[CheckResult]:
            yield _outcome("BOT-CFG-001", outcome)

    @check(
        "BOT-CFG-002",
        "Answers",
        Stage.CONFIG,
        ALL,
        runbook="docs/x.md#answers",
        requires={"BOT-CFG-001": "the thing never became ready"},
    )
    def answers(ctx: CheckContext) -> Iterable[CheckResult]:
        ran.append("BOT-CFG-002")
        yield _passing("BOT-CFG-002")

    results = run_stage(Stage.CONFIG, _ctx(bot, settings, logger))
    assert ran == []
    skipped = results[-1]
    assert (skipped.check_id, skipped.title, skipped.outcome) == (
        "BOT-CFG-002",
        "Answers",
        Outcome.SKIP,
    )
    assert skipped.remediation == "skipped: the thing never became ready (BOT-CFG-001)"
    assert skipped.runbook == "docs/x.md#answers"
    raise_on_errors(results[1:])  # a skip never fails the run


def test_a_crashed_requirement_skips_its_dependents(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    @check("BOT-CFG-001", "Ready", Stage.CONFIG, ALL)
    def ready(ctx: CheckContext) -> Iterable[CheckResult]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    @check("BOT-CFG-002", "Answers", Stage.CONFIG, ALL, requires={"BOT-CFG-001": "not ready"})
    def answers(ctx: CheckContext) -> Iterable[CheckResult]:
        yield _passing("BOT-CFG-002")

    outcomes = [r.outcome for r in run_stage(Stage.CONFIG, _ctx(bot, settings, logger))]
    assert outcomes == [Outcome.FAIL, Outcome.SKIP]


@pytest.mark.parametrize("first", [Outcome.PASS, Outcome.SKIP])
def test_a_check_runs_when_its_requirement_passed_or_skipped(
    bot: Project, settings: Settings, logger: logging.Logger, first: Outcome
) -> None:
    """A skipped requirement (not applicable yet) leaves the dependent to its own gates."""

    @check("BOT-CFG-001", "Ready", Stage.CONFIG, ALL)
    def ready(ctx: CheckContext) -> Iterable[CheckResult]:
        yield _outcome("BOT-CFG-001", first)

    @check("BOT-CFG-002", "Answers", Stage.CONFIG, ALL, requires={"BOT-CFG-001": "not ready"})
    def answers(ctx: CheckContext) -> Iterable[CheckResult]:
        yield _passing("BOT-CFG-002")

    results = run_stage(Stage.CONFIG, _ctx(bot, settings, logger))
    assert results[-1].outcome is Outcome.PASS


def test_a_requirement_must_be_a_well_formed_check_id() -> None:
    with pytest.raises(ValueError, match="requires"):
        check("BOT-CFG-002", "t", Stage.CONFIG, ALL, requires={"nope": "x"})


def test_a_requirement_must_sort_before_the_check() -> None:
    with pytest.raises(ValueError, match="requires"):
        check("BOT-CFG-002", "t", Stage.CONFIG, ALL, requires={"BOT-CFG-003": "x"})


def test_stage_state_is_shared_within_one_run_and_fresh_for_the_next(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    seen: list[dict[str, object]] = []

    @check("BOT-CFG-001", "First", Stage.CONFIG, ALL)
    def first(ctx: CheckContext) -> Iterable[CheckResult]:
        ctx.stage_state.setdefault("runs", 0)
        seen.append(ctx.stage_state)
        yield _passing("BOT-CFG-001")

    @check("BOT-CFG-002", "Second", Stage.CONFIG, ALL)
    def second(ctx: CheckContext) -> Iterable[CheckResult]:
        seen.append(ctx.stage_state)
        yield _passing("BOT-CFG-002")

    ctx = _ctx(bot, settings, logger)
    run_stage(Stage.CONFIG, ctx)
    run_stage(Stage.CONFIG, ctx)
    assert seen[0] is seen[1]
    assert seen[2] is seen[3]
    assert seen[0] is not seen[2]
    assert ctx.stage_state == {}  # the caller's context is untouched


def test_max_wait_defaults_to_the_configured_budget(
    bot: Project, settings: Settings, logger: logging.Logger
) -> None:
    assert _ctx(bot, settings, logger).max_wait_seconds is None
