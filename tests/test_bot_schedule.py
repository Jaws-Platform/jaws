"""A bot's running hours: the `schedule` field, what the stack gets, `bot start`,
`bot stop`, and a deploy while the instance is stopped outside its hours."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import boto3
import pytest
import yaml
from botocore.exceptions import ClientError
from moto import mock_aws
from typer.testing import CliRunner

from jaws import bot as botlib
from jaws import cli
from jaws import rollout as rollout_module
from jaws.components import BotSchedule
from jaws.errors import ConfigError, PreflightError, RunError
from jaws.project import Project
from jaws.settings import Settings
from jaws.site import load_site_config
from jaws.stack import render_tfvars

from .conftest import FIXTURES

REGION = "us-east-1"
PREFIX = "/jaws/braveheart/bot"
RELEASE_ROLE = "arn:aws:sts::570327089884:assumed-role/jaws-braveheart-ci-release/s"
PLAN_ROLE = "arn:aws:sts::570327089884:assumed-role/jaws-braveheart-ci-plan/s"
DAILY = {"days": "daily", "start": "08:00", "stop": "20:00"}
runner = CliRunner()
logger = logging.getLogger("test")


# --- helpers --------------------------------------------------------------------


def _raw(schedule: dict[str, Any] | None) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((FIXTURES / "bots" / "braveheart.yaml").read_text())
    bot = next(c for c in raw["components"] if c["kind"] == "lichess-bot")
    if schedule is not None:
        bot["schedule"] = schedule
    return raw


def _project(tmp_path: Path, settings: Settings, schedule: dict[str, Any] | None) -> Project:
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(_raw(schedule)))
    return Project.from_config(load_site_config(path), settings)


def _as_role(arn: str) -> AbstractContextManager[Any]:
    return patch("jaws.aws.caller_identity", return_value=("570327089884", arn))


def _instance(ec2: Any, state: str = "running") -> str:
    image = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    instance_id: str = ec2.run_instances(
        ImageId=image,
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Project", "Value": "braveheart"},
                    {"Key": "Component", "Value": "container-instance"},
                ],
            }
        ],
    )["Instances"][0]["InstanceId"]
    if state == "stopped":
        ec2.stop_instances(InstanceIds=[instance_id])
    return instance_id


def _state(ec2: Any, instance_id: str) -> str:
    reservations = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"]
    state: str = reservations[0]["Instances"][0]["State"]["Name"]
    return state


def _param(ssm: Any, name: str) -> str | None:
    values = botlib.get_parameters(ssm, [f"{PREFIX}/{name}"])
    return values[f"{PREFIX}/{name}"]


class _Clock:
    """A clock that `sleep` advances; `on_sleep` plays the instance's side."""

    def __init__(self, on_sleep: Callable[[int], None] = lambda n: None) -> None:
        self.t = 0.0
        self.sleeps = 0
        self.on_sleep = on_sleep

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.sleeps += 1
        self.on_sleep(self.sleeps)


@pytest.fixture
def aws() -> Iterator[tuple[Any, Any]]:
    with mock_aws():
        session = boto3.session.Session(region_name=REGION)
        yield session.client("ec2"), session.client("ssm")


# --- the schedule field -------------------------------------------------------------


def test_no_schedule_is_always_on(tmp_path: Path, settings: Settings) -> None:
    project = _project(tmp_path, settings, None)
    assert project.bot.schedule is None
    assert render_tfvars(project, settings)["schedule"] is None


def test_a_schedule_reaches_the_stack(tmp_path: Path, settings: Settings) -> None:
    project = _project(tmp_path, settings, {**DAILY, "days": "weekdays"})
    schedule = project.bot.schedule
    assert schedule is not None and schedule.timezone == "UTC"
    assert render_tfvars(project, settings)["schedule"] == {
        "days": "weekdays",
        "start": "08:00",
        "stop": "20:00",
    }
    assert schedule.describe() == "08:00-20:00 UTC, Monday to Friday"


def test_days_default_to_daily(tmp_path: Path, settings: Settings) -> None:
    project = _project(tmp_path, settings, {"start": "08:00", "stop": "20:00"})
    assert project.bot.schedule is not None and project.bot.schedule.days == "daily"


@pytest.mark.parametrize(
    ("start", "stop"),
    [("02:45", "22:45"), ("08:00", "12:00"), ("00:00", "20:00"), ("07:15", "19:30")],
)
def test_allowed_windows(start: str, stop: str) -> None:
    BotSchedule(start=start, stop=stop)


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ({**DAILY, "days": "mondays"}, "days"),
        ({**DAILY, "start": "08:10"}, "quarter hour"),
        ({**DAILY, "start": "8:00"}, "quarter hour"),
        ({**DAILY, "stop": "24:00"}, "quarter hour"),
        ({**DAILY, "start": "20:00", "stop": "08:00"}, "may not cross midnight"),
        ({**DAILY, "stop": "08:00"}, "may not cross midnight"),
        ({**DAILY, "stop": "11:45"}, "4 to 20 hours"),
        ({**DAILY, "start": "02:00", "stop": "22:15"}, "4 to 20 hours"),
        ({**DAILY, "start": "10:00", "stop": "23:00"}, "22:45 at the latest"),
        ({**DAILY, "timezone": "Europe/London"}, "timezone"),
        ({**DAILY, "every": "hour"}, "every"),
    ],
)
def test_schedules_that_make_no_sense_are_refused(
    tmp_path: Path, settings: Settings, schedule: dict[str, Any], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        _project(tmp_path, settings, schedule)


def test_a_yaml_time_must_be_quoted(tmp_path: Path, settings: Settings) -> None:
    # Unquoted, YAML 1.1 reads 08:00 as the integer 480: refused, not misread.
    path = tmp_path / "jaws.yaml"
    text = yaml.safe_dump(_raw(DAILY)).replace("'08:00'", "08:00").replace("'20:00'", "20:00")
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_site_config(path)


def test_cli_and_module_agree_on_the_latest_stop() -> None:
    """The module's own validation is `stop + drain_minutes <= 23:59` with drain 60."""
    BotSchedule(start="10:00", stop="22:45")
    with pytest.raises(ValueError, match="22:45"):
        BotSchedule(start="10:00", stop="23:00")


# --- bot start -------------------------------------------------------------------


def test_start_starts_and_waits_for_the_reconcile(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    instance_id = _instance(ec2, "stopped")
    botlib.put_parameter(ssm, f"{PREFIX}/status", "ok")  # stale, from before the stop
    seen: list[str | None] = []

    def boot(n: int) -> None:
        seen.append(_param(ssm, "status"))
        if n == 3:
            botlib.put_parameter(ssm, f"{PREFIX}/status", "ok")

    clock = _Clock(boot)
    status = botlib.start_instance(ec2, ssm, project, logger, clock.sleep, clock.now)
    assert status == "ok"
    assert _state(ec2, instance_id) == "running"
    assert seen[:3] == ["starting", "starting", "starting"], "a stale ok never ends the wait"
    assert clock.sleeps == 3


def test_start_reports_a_failed_reconcile(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2, "stopped")
    clock = _Clock(
        lambda n: botlib.put_parameter(ssm, f"{PREFIX}/status", "failed:could not pull v1")
    )
    status = botlib.start_instance(ec2, ssm, project, logger, clock.sleep, clock.now)
    assert status == "failed:could not pull v1"


def test_start_of_a_running_instance_does_nothing(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2)
    clock = _Clock()
    assert botlib.start_instance(ec2, ssm, project, logger, clock.sleep, clock.now) == (
        "already running"
    )
    assert clock.sleeps == 0 and _param(ssm, "status") is None


def test_start_without_an_instance_is_refused(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    with pytest.raises(PreflightError, match="apply"):
        botlib.start_instance(ec2, ssm, _project(tmp_path, settings, DAILY), logger)


def test_start_gives_up_after_the_timeout(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2, "stopped")
    clock = _Clock()
    with pytest.raises(RunError, match="did not report ok within 60s"):
        botlib.start_instance(ec2, ssm, project, logger, clock.sleep, clock.now, timeout=60)


def test_a_refused_start_puts_the_status_back(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2, "stopped")
    botlib.put_parameter(ssm, f"{PREFIX}/status", "stopped")

    class Refusing:
        def __getattr__(self, name: str) -> Any:
            return getattr(ec2, name)

        def start_instances(self, **kwargs: Any) -> Any:
            raise ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "StartInstances")

    with pytest.raises(RunError, match="UnauthorizedOperation"):
        botlib.start_instance(Refusing(), ssm, project, logger)  # type: ignore[arg-type]
    assert _param(ssm, "status") == "stopped"


# --- bot stop ---------------------------------------------------------------------


def _commands(ssm: Any) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = ssm.list_commands()["Commands"]
    return commands


def test_stop_sends_the_drain_and_returns_once_it_has_begun(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    instance_id = _instance(ec2)
    clock = _Clock(
        lambda n: botlib.put_parameter(ssm, f"{PREFIX}/status", "waiting:v1") if n == 2 else None
    )
    status = botlib.drain_instance(ec2, ssm, project, logger, False, clock.sleep, clock.now)
    assert status == "waiting:v1"
    (command,) = _commands(ssm)
    assert command["InstanceIds"] == [instance_id]
    assert command["DocumentName"] == "AWS-RunShellScript"
    assert command["Parameters"]["commands"] == ["/usr/local/bin/container-reconcile-async --drain"]
    assert _state(ec2, instance_id) == "running", "without --wait it does not wait for the stop"


def test_stop_with_wait_returns_once_the_instance_has_stopped(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    instance_id = _instance(ec2)

    def instance(n: int) -> None:
        botlib.put_parameter(ssm, f"{PREFIX}/status", "waiting:v1")
        if n == 4:  # the game ends, the reconciler powers off
            botlib.put_parameter(ssm, f"{PREFIX}/status", "stopped")
            ec2.stop_instances(InstanceIds=[instance_id])

    clock = _Clock(instance)
    status = botlib.drain_instance(ec2, ssm, project, logger, True, clock.sleep, clock.now)
    assert status in ("stopping", "stopped")
    assert clock.sleeps == 4


def test_stop_reports_an_instance_that_ignores_the_drain(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2)
    botlib.put_parameter(ssm, f"{PREFIX}/status", "ok")
    clock = _Clock()
    with pytest.raises(RunError, match=r"0\.22\.0"):
        botlib.drain_instance(ec2, ssm, project, logger, False, clock.sleep, clock.now)


def test_stop_of_a_stopped_instance_does_nothing(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    ec2, ssm = aws
    project = _project(tmp_path, settings, DAILY)
    _instance(ec2, "stopped")
    assert botlib.drain_instance(ec2, ssm, project, logger) == "stopped"
    assert _commands(ssm) == []


# --- the commands -------------------------------------------------------------------


@pytest.fixture
def scheduled_workspace(bot_workspace: Path) -> Path:
    (bot_workspace / "jaws.yaml").write_text(yaml.safe_dump(_raw(DAILY)))
    return bot_workspace


def _ecr_with(tag: str) -> None:
    ecr = boto3.client("ecr", region_name=REGION)
    ecr.create_repository(repositoryName="jaws-braveheart")
    ecr.put_image(
        repositoryName="jaws-braveheart",
        imageManifest=(
            '{"schemaVersion": 2, "mediaType": '
            '"application/vnd.docker.distribution.manifest.v2+json", '
            '"config": {"digest": "sha256:x", "size": 1, "mediaType": "x"}, "layers": []}'
        ),
        imageTag=tag,
    )


def test_deploy_to_a_stopped_scheduled_bot_sets_the_version(
    scheduled_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_command(*args: object, **kwargs: object) -> str:
        raise AssertionError("Run Command cannot reach a stopped instance")

    monkeypatch.setattr(rollout_module, "send_reconcile", no_command)
    with mock_aws(), _as_role(RELEASE_ROLE):
        ec2, ssm = boto3.client("ec2", region_name=REGION), boto3.client("ssm", region_name=REGION)
        _ecr_with("v0.14.0")
        _instance(ec2, "stopped")
        botlib.put_parameter(ssm, f"{PREFIX}/status", "stopped")
        result = runner.invoke(cli.app, ["bot", "deploy", "--version", "v0.14.0"])
        desired, status = _param(ssm, "desired-version"), _param(ssm, "status")
    assert result.exit_code == 0, result.output
    assert desired == "v0.14.0"
    assert status == "stopped", "the status stays what the drain left"
    assert "outside its running hours" in result.output
    assert "08:00-20:00 UTC, every day" in result.output


def test_deploy_to_a_stopped_bot_without_a_schedule_still_fails(bot_workspace: Path) -> None:
    with mock_aws(), _as_role(RELEASE_ROLE):
        ec2, ssm = boto3.client("ec2", region_name=REGION), boto3.client("ssm", region_name=REGION)
        _ecr_with("v0.14.0")
        _instance(ec2, "stopped")
        result = runner.invoke(cli.app, ["bot", "deploy", "--version", "v0.14.0"])
        desired = _param(ssm, "desired-version")
    assert result.exit_code == 3
    assert "is stopped" in result.output and "bot start" in result.output
    assert desired is None


@pytest.mark.parametrize("command", [["bot", "start"], ["bot", "stop"]])
def test_start_and_stop_need_the_release_role(
    scheduled_workspace: Path, command: list[str]
) -> None:
    with mock_aws(), _as_role(PLAN_ROLE):
        result = runner.invoke(cli.app, command)
    assert result.exit_code == 3


def test_bot_start_command(scheduled_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_start(ec2: object, ssm: object, project: Project, log: object) -> str:
        calls.append(project.project)
        return "ok"

    monkeypatch.setattr(botlib, "start_instance", fake_start)
    with mock_aws(), _as_role(RELEASE_ROLE):
        result = runner.invoke(cli.app, ["bot", "start"])
    assert result.exit_code == 0, result.output
    assert calls == ["braveheart"]
    assert "next scheduled drain" in result.output


def test_bot_start_fails_on_a_failed_reconcile(
    scheduled_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(botlib, "start_instance", lambda *a: "failed:could not pull v1")
    with mock_aws(), _as_role(RELEASE_ROLE):
        result = runner.invoke(cli.app, ["bot", "start"])
    assert result.exit_code == 1
    assert "could not pull v1" in result.output


def test_bot_stop_command_passes_wait(
    scheduled_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[bool] = []

    def fake_drain(ec2: object, ssm: object, project: Project, log: object, wait: bool) -> str:
        waits.append(wait)
        return "stopped"

    monkeypatch.setattr(botlib, "drain_instance", fake_drain)
    with mock_aws(), _as_role(RELEASE_ROLE):
        assert runner.invoke(cli.app, ["bot", "stop"]).exit_code == 0
        assert runner.invoke(cli.app, ["bot", "stop", "--wait"]).exit_code == 0
    assert waits == [False, True]


def test_status_shows_the_running_hours(
    aws: tuple[Any, Any], tmp_path: Path, settings: Settings
) -> None:
    session = boto3.session.Session(region_name=REGION)
    scheduled = botlib.render_status(botlib.status(session, _project(tmp_path, settings, DAILY)))
    assert "running hours:     08:00-20:00 UTC, every day" in scheduled
    always = botlib.render_status(botlib.status(session, _project(tmp_path, settings, None)))
    assert "running hours:     always on" in always
