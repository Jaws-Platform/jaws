"""Task-run records (runs-1) and campaigns.

`task run` writes a `started` record when its instance launches and a
`finished` record when the task ends; `task sweep` writes `swept` when it
terminates a leaked instance. They go to the billing bucket for the monitoring
stack's normalizer. A record can never fail or delay a task, and a task without
`--campaign` carries no Campaign tag.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from moto import mock_aws
from typer.testing import CliRunner

from jaws import cli, run_records, tasks
from jaws.errors import ConfigError, RunError
from jaws.project import Project
from jaws.settings import Settings
from tests.conftest import read_config, write_config
from tests.test_cli import _as_role
from tests.test_tasks_launch import FakeEC2, _gpu_spec, _spec
from tests.test_tasks_run import FakeSession, Recorder

LOG = logging.getLogger("test-records")
#: How the CLI speaks of a run record, in any message.
RECORD_MESSAGE = re.compile(r"\b(started|finished|swept) record\b")
runner = CliRunner()
BUCKET = "jaws-billing-570327089884"
SHA = "0123456789abcdef0123456789abcdef01234567"
TASK_ROLE = "arn:aws:sts::570327089884:assumed-role/jaws-braveheart-ci-task/s"
LAUNCHED_AT = datetime(2026, 11, 24, 21, 10, 3, tzinfo=UTC)
ENDED_AT = datetime(2026, 11, 25, 2, 52, 41, tzinfo=UTC)
PREFIX = "raw/provider=jaws/source=task-runs/project=braveheart"
SPOT_PLAN = tasks.PricePlan(
    [tasks.Subnet("subnet-a", "us-east-1a", "use1-az6")],
    "2.0002", 3.44864, {"us-east-1a": 1.0712}, {"us-east-1a": 9},
)  # fmt: skip


# --- the normalizer's runs-1 checks ------------------------------------------------

#: Every field a runs-1 record may have, and those of its instance and prices
#: (terraform-aws-jaws-monitoring, modules/billing-normalizer/README.md, "Task runs").
RECORD_FIELDS = {
    "schema", "event", "at", "tags", "project", "campaign", "kind", "instance", "prices",
    "outcome", "exit_code", "interrupted_at", "reason", "links", "attributes",
}  # fmt: skip
INSTANCE_FIELDS = {"type", "accelerators", "market", "zone", "id"}
PRICE_FIELDS = {"hourly_usd", "on_demand_hourly_usd", "worst_case_usd", "ceiling_usd", "max_hours"}


def _runs_1(record: dict[str, Any]) -> dict[str, Any]:
    """What the normalizer's flatten_event requires (normalizer/runs.py), and no
    field it does not read: a record that fails this would be skipped."""
    assert set(record) <= RECORD_FIELDS, set(record) - RECORD_FIELDS
    assert record["schema"] == "runs-1"
    assert record["event"] in ("started", "finished", "swept")
    tags = record["tags"]
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items())
    assert tags["RunId"].strip() and tags["TaskId"].strip()
    assert isinstance(record["project"], str) and record["project"].strip()
    assert datetime.fromisoformat(record["at"]).tzinfo is not None
    instance = record.get("instance") or {}
    prices = record.get("prices") or {}
    assert set(instance) <= INSTANCE_FIELDS and set(prices) <= PRICE_FIELDS
    for count in (instance.get("accelerators"), record.get("exit_code")):
        assert count is None or (isinstance(count, int) and -(2**31) <= count < 2**31)
    assert all(v is None or isinstance(v, int | float) for v in prices.values())
    if record.get("interrupted_at") is not None:
        datetime.fromisoformat(record["interrupted_at"])
    for mapping in ("links", "attributes"):
        assert all(isinstance(v, str) for v in (record.get(mapping) or {}).values())
    return record


# --- fakes -----------------------------------------------------------------------------


class FakeS3:
    """Keeps every put_object, or raises `error` on each."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        self.puts.append(kwargs)
        return {}

    @property
    def records(self) -> list[tuple[str, dict[str, Any]]]:
        return [(p["Key"], json.loads(p["Body"])) for p in self.puts]

    @property
    def events(self) -> list[str]:
        return [record["event"] for _, record in self.records]


def _records(s3: FakeS3, *times: datetime) -> run_records.RunRecords:
    clock = iter(times or (LAUNCHED_AT, ENDED_AT))
    return run_records.RunRecords(s3, BUCKET, LOG, now=lambda: next(clock))  # type: ignore[arg-type]


def _run(bot: Project, tmp_path: Path, records: Any, **spec: Any) -> int:
    session: Any = FakeSession()
    spec.setdefault("max_run_cost_usd", 50.0)
    return tasks.run_task(
        session, _spec(bot, **spec), tmp_path / "out", LOG, write=lambda _: None, records=records
    )


@pytest.fixture
def gpus(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """DescribeInstanceTypes stands in: one GPU, and the types it was asked about."""
    asked: list[str] = []

    def accelerator_count(ec2: Any, instance_type: str) -> int:
        asked.append(instance_type)
        return 1

    monkeypatch.setattr(tasks, "accelerator_count", accelerator_count)
    return asked


# --- started and finished ----------------------------------------------------------------


def test_task_run_writes_started_at_launch(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    s3 = FakeS3()
    seen_at_agent: list[list[str]] = []
    Recorder(
        monkeypatch, price_plan=SPOT_PLAN,
        wait_for_agent=lambda *a, **k: seen_at_agent.append(s3.events),
    )  # fmt: skip
    assert _run(bot, tmp_path, _records(s3)) == 0
    # Written the moment the instance launched, before anything waits on it.
    assert seen_at_agent == [["started"]]
    key, started = s3.records[0]
    assert key == f"{PREFIX}/date=2026-11-24/123-1.sprt-0.started.json"
    assert _runs_1(started) == {
        "schema": "runs-1",
        "event": "started",
        "at": "2026-11-24T21:10:03Z",
        "tags": tasks.task_tags(_spec(bot, max_run_cost_usd=50.0), "spot"),
        "project": "braveheart",
        "campaign": None,
        "kind": "SPRT",
        "instance": {
            "type": "c8a.16xlarge", "accelerators": 1, "market": "spot", "zone": "use1-az6",
            "id": "i-1",
        },
        "prices": {
            "hourly_usd": 1.0712, "on_demand_hourly_usd": 3.44864,
            "worst_case_usd": pytest.approx(3.44864 * 6), "ceiling_usd": 50.0, "max_hours": 6,
        },
        "links": {
            "commit": f"https://github.com/Braveheart-Chess/braveheart/commit/{SHA}",
        },
        "attributes": {
            "profile": "cpu", "lifecycle": "spot", "repository": "Braveheart-Chess/braveheart",
            "commit": SHA, "run_id": "123-1", "task_id": "sprt-0", "workflow": "SPRT",
            "availability_zone": "us-east-1a", "image": "ami-1", "spot_cap_usd": "2.0002",
            "spot_placement_score": "9",
        },
    }  # fmt: skip
    assert gpus == ["c8a.16xlarge"]
    put = s3.puts[0]
    assert (put["Bucket"], put["ContentType"], put["IfNoneMatch"]) == (
        BUCKET,
        "application/json",
        "*",
    )


def test_task_run_writes_finished_after_terminating(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    s3 = FakeS3()
    seen_at_terminate: list[list[str]] = []

    def terminate(ec2: Any, instance_id: str, logger: Any) -> None:
        seen_at_terminate.append(s3.events)

    Recorder(monkeypatch, price_plan=SPOT_PLAN, terminate=terminate)
    assert _run(bot, tmp_path, _records(s3)) == 0
    assert seen_at_terminate == [["started"]]  # the instance first, the record after
    key, finished = s3.records[1]
    assert key == f"{PREFIX}/date=2026-11-25/123-1.sprt-0.finished.json"
    _runs_1(finished)
    started = s3.records[0][1]
    assert finished["at"] == "2026-11-25T02:52:41Z"
    assert (finished["outcome"], finished["exit_code"], finished["interrupted_at"]) == (
        "passed",
        0,
        None,
    )
    # Self-sufficient if the started record was lost: the same launch metadata.
    for field in ("tags", "project", "campaign", "kind", "instance", "prices", "links"):
        assert finished[field] == started[field], field


@pytest.mark.parametrize(
    ("behaviour", "code", "outcome", "interrupted_at"),
    [
        ({"stream": 7}, 7, "failed", None),
        ({"stream": 1, "interruption": "2026-10-29T12:00:05Z"}, 75, "interrupted",
         "2026-10-29T12:00:05Z"),
        ({"stream": 1, "interruption": "unknown"}, 75, "interrupted", None),
        ({"collect": RunError("download failed")}, 1, "failed", None),
        ({"send": ClientError({"Error": {"Code": "AccessDenied"}}, "SendCommand")}, 1, "failed",
         None),
    ],
    ids=["task-failed", "interrupted", "interrupted-unknown-time", "collect-failed",
         "aws-error"],
)  # fmt: skip
def test_finished_records_the_outcome_exit_code_and_interruption(
    bot: Project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gpus: list[str],
    behaviour: dict[str, Any],
    code: int,
    outcome: str,
    interrupted_at: str | None,
) -> None:
    s3 = FakeS3()
    Recorder(monkeypatch, **behaviour)
    assert _run(bot, tmp_path, _records(s3)) == code
    assert s3.events == ["started", "finished"]
    finished = _runs_1(s3.records[1][1])
    assert (finished["outcome"], finished["exit_code"], finished["interrupted_at"]) == (
        outcome,
        code,
        interrupted_at,
    )


def test_finished_carries_the_gpu_driver_and_cuda_from_the_environment_block(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    printed: list[str] = []
    block = [
        "== task-runner environment", "profile=gpu", "image_id=ami-0f9", "cpu_model=AMD EPYC",
        "gpu_model=NVIDIA L4", "gpu_memory=23034 MiB", "nvidia_driver=580.95.05",
        "cuda_version=13.0", "==", "gpu_model=printed by the task, not the runner",
    ]  # fmt: skip

    def stream(logs: Any, ssm: Any, group: str, command: str, iid: str, write: Any, *a: Any,
               **k: Any) -> int:  # fmt: skip
        for line in block:
            write(line)
        return 0

    s3 = FakeS3()
    Recorder(monkeypatch, stream=stream, instance_types_info={"g6.xlarge": (4, 2)},
             launch=tasks.Launched("i-1", "us-east-1a", "ami-0f9", "on-demand"))  # fmt: skip
    session: Any = FakeSession()
    code = tasks.run_task(
        session, _gpu_spec(bot), tmp_path / "out", LOG, write=printed.append,
        records=_records(s3),
    )  # fmt: skip
    assert code == 0
    assert printed == block  # every line still reaches the job log
    finished = _runs_1(s3.records[1][1])
    attributes = finished["attributes"]
    assert {k: attributes[k] for k in ("gpu_model", "gpu_memory", "nvidia_driver",
                                       "cuda_version")} == {
        "gpu_model": "NVIDIA L4", "gpu_memory": "23034 MiB", "nvidia_driver": "580.95.05",
        "cuda_version": "13.0",
    }  # fmt: skip
    assert finished["instance"]["accelerators"] == 1
    assert finished["prices"]["hourly_usd"] == 3.44864  # on demand pays the on-demand price


class TypesEC2:
    """DescribeInstanceTypes for one type, or an error."""

    def __init__(self, info: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.info, self.error = info or {}, error
        self.asked: list[list[str]] = []

    def describe_instance_types(self, InstanceTypes: list[str]) -> dict[str, Any]:  # noqa: N803
        self.asked.append(InstanceTypes)
        if self.error is not None:
            raise self.error
        return {"InstanceTypes": [{"InstanceType": InstanceTypes[0], **self.info}]}


@pytest.mark.parametrize(
    ("info", "count"),
    [
        ({"GpuInfo": {"Gpus": [{"Name": "L4", "Manufacturer": "NVIDIA", "Count": 1}]}}, 1),
        ({"GpuInfo": {"Gpus": [{"Count": 4}, {"Count": 4}]}}, 8),
        ({"VCpuInfo": {"DefaultVCpus": 64}}, 0),
    ],
    ids=["one-gpu", "two-kinds", "no-gpu"],
)
def test_the_gpu_count_comes_from_the_instance_type(info: dict[str, Any], count: int) -> None:
    ec2 = TypesEC2(info)
    assert tasks.accelerator_count(ec2, "g6.xlarge") == count  # type: ignore[arg-type]
    assert ec2.asked == [["g6.xlarge"]]


def test_an_unknown_gpu_count_is_none_not_a_failure() -> None:
    denied = ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "DescribeInstanceTypes")
    assert tasks.accelerator_count(TypesEC2(error=denied), "g6.xlarge") is None  # type: ignore[arg-type]


def test_nothing_launched_writes_nothing(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    s3 = FakeS3()
    Recorder(monkeypatch, launch=tasks.NoCapacity("no spot capacity"))
    assert _run(bot, tmp_path, _records(s3)) == 3
    assert s3.puts == []


def test_without_records_nothing_is_written_or_said(
    bot: Project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gpus: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    Recorder(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        assert _run(bot, tmp_path, None) == 0
    assert gpus == []  # not even the GPU lookup
    assert not [r for r in caplog.records if RECORD_MESSAGE.search(r.getMessage())]


# --- a failed write never fails or delays a task --------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject"),
        ClientError({"Error": {"Code": "NoSuchBucket"}}, "PutObject"),
        EndpointConnectionError(endpoint_url="https://s3.amazonaws.com"),
        TypeError("a bug in the writer"),
    ],
    ids=["denied", "no-bucket", "unreachable", "bug"],
)
def test_a_failed_write_is_a_warning_and_the_task_goes_on(
    bot: Project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gpus: list[str],
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    rec = Recorder(monkeypatch, stream=7)
    with caplog.at_level(logging.WARNING, logger=LOG.name):
        assert _run(bot, tmp_path, _records(FakeS3(error))) == 7
    assert rec.calls == [
        "check_ceiling", "instance_types_info", "wait_for_slot", "public_subnets", "price_plan",
        "launch", "wait_for_agent", "send", "stream", "results_location", "collect",
        "interruption", "terminate",
    ]  # fmt: skip
    assert rec.terminated == ["i-1"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("started record" in w and "not written" in w for w in warnings), warnings
    assert any("finished record" in w and "not written" in w for w in warnings), warnings


def test_a_failed_gpu_lookup_still_writes_the_record(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = FakeS3()
    Recorder(monkeypatch)  # the session's clients are bare objects: the lookup fails
    assert _run(bot, tmp_path, _records(s3)) == 0
    assert s3.events == ["started", "finished"]
    assert s3.records[0][1]["instance"]["accelerators"] is None


def test_the_client_gives_up_within_seconds(settings: Settings) -> None:
    """A slow or unreachable S3 must not hold the task: short timeouts, one retry."""
    records = run_records.RunRecords.from_settings(
        settings, boto3.session.Session(region_name="us-east-1"), LOG
    )
    assert records is not None
    config: Any = records.s3.meta.config
    assert config.connect_timeout <= 5 and config.read_timeout <= 10
    assert config.retries == {"total_max_attempts": 2, "mode": "standard"}  # one retry


def test_a_record_is_written_once(settings: Settings) -> None:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        records = run_records.RunRecords(s3, BUCKET, LOG, now=lambda: LAUNCHED_AT)
        record = run_records.record(
            "started", project="braveheart", tags={"RunId": "1-1", "TaskId": "t"},
            at=LAUNCHED_AT,
        )  # fmt: skip
        assert records.write(record) is True
        assert records.write({**record, "kind": "rewritten"}) in (True, False)
        key = f"{PREFIX}/date=2026-11-24/1-1.t.started.json"
        body = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    if body.get("kind") == "rewritten":
        pytest.skip("moto does not enforce IfNoneMatch; the parameter is asserted above")
    assert body == record


# --- where records go ------------------------------------------------------------------------


def test_records_go_to_the_configured_bucket(settings: Settings) -> None:
    session = boto3.session.Session(region_name="us-east-1")
    records = run_records.RunRecords.from_settings(settings, session, LOG)
    assert records is not None and records.bucket == BUCKET


def test_no_monitoring_or_no_cost_means_no_records(settings: Settings) -> None:
    session = boto3.session.Session(region_name="us-east-1")
    assert settings.monitoring is not None
    host_only = settings.model_copy(
        update={"monitoring": settings.monitoring.model_copy(update={"cost": None})}
    )
    none = settings.model_copy(update={"monitoring": None})
    assert run_records.RunRecords.from_settings(host_only, session, LOG) is None
    assert run_records.RunRecords.from_settings(none, session, LOG) is None


@pytest.mark.parametrize(
    ("run_id", "task_id", "file"),
    [("123-1", "sprt-0", "123-1.sprt-0"), ("a/b", "t:1", "a-b.t-1")],
)
def test_a_key_is_one_file_under_the_projects_prefix(run_id: str, task_id: str, file: str) -> None:
    record = run_records.record(
        "swept", project="braveheart", tags={"RunId": run_id, "TaskId": task_id}, at=ENDED_AT
    )
    assert run_records.key(record) == f"{PREFIX}/date=2026-11-25/{file}.swept.json"


def test_links_name_the_run_attempt_pull_request_and_commit(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Braveheart-Chess/braveheart")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    s3 = FakeS3()
    Recorder(monkeypatch)
    assert _run(bot, tmp_path, _records(s3), pull_request="88") == 0
    started = s3.records[0][1]
    base = "https://github.com/Braveheart-Chess/braveheart"
    assert started["links"] == {
        "run": f"{base}/actions/runs/123456/attempts/2",
        "pr": f"{base}/pull/88",
        "commit": f"{base}/commit/{SHA}",
    }
    assert started["attributes"]["pull_request"] == "88"


# --- campaigns --------------------------------------------------------------------------------


def _tag_specifications(spec: tasks.TaskSpec) -> list[dict[str, Any]]:
    ec2 = FakeEC2()
    tasks._run_instance(ec2, spec, "jaws-braveheart-task", SPOT_PLAN.subnets[0], "spot", None)  # type: ignore[arg-type]
    specifications: list[dict[str, Any]] = ec2.calls[0]["TagSpecifications"]
    return specifications


def test_a_campaign_tags_the_instance_and_volume_and_the_record(
    bot: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gpus: list[str]
) -> None:
    spec = _spec(bot, campaign="datagen-2026-12")
    for specification in _tag_specifications(spec):
        assert specification["ResourceType"] in ("instance", "volume")
        assert {"Key": "Campaign", "Value": "datagen-2026-12"} in specification["Tags"]
    s3 = FakeS3()
    Recorder(monkeypatch)
    assert _run(bot, tmp_path, _records(s3), campaign="datagen-2026-12") == 0
    started = s3.records[0][1]
    assert started["campaign"] == "datagen-2026-12"
    assert started["tags"]["Campaign"] == "datagen-2026-12"


def test_without_a_campaign_there_is_no_campaign_tag(bot: Project) -> None:
    spec = _spec(bot)
    assert "Campaign" not in tasks.task_tags(spec, "spot")
    for specification in _tag_specifications(spec):
        assert all(t["Key"] != "Campaign" for t in specification["Tags"])


@pytest.mark.parametrize(
    "slug", ["Datagen", "net_v12", "a" * 64, "", "net v12", "net/v12", "net-v12\n"]
)
def test_a_campaign_is_a_short_lowercase_slug(bot: Project, slug: str) -> None:
    with pytest.raises(ConfigError, match="campaign"):
        tasks.task_script(_spec(bot, campaign=slug), "jaws-braveheart-tasks", "tasks/")


@pytest.mark.parametrize("slug", ["net-v12", "datagen-2026-12", "a" * 63, "7"])
def test_good_campaign_slugs(bot: Project, slug: str) -> None:
    assert tasks.task_script(_spec(bot, campaign=slug), "jaws-braveheart-tasks", "tasks/")


# --- the commands -----------------------------------------------------------------------------


@pytest.fixture
def run_captured(monkeypatch: pytest.MonkeyPatch, bot_workspace: Path) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def run_task(session: Any, spec: tasks.TaskSpec, out_dir: Path, logger: Any, **kw: Any) -> int:
        seen["spec"], seen["kw"] = spec, kw
        return 0

    monkeypatch.setattr(tasks, "run_task", run_task)
    return seen


def _task_run(*args: str) -> Any:
    with _as_role(TASK_ROLE):
        return runner.invoke(
            cli.app, ["task", "run", "--script", "scripts/sprt.sh", "--ref", SHA, *args]
        )


def test_task_run_takes_a_campaign(run_captured: dict[str, Any]) -> None:
    result = _task_run("--campaign", "net-v12")
    assert result.exit_code == 0, result.output
    assert run_captured["spec"].campaign == "net-v12"
    assert _task_run().exit_code == 0
    assert run_captured["spec"].campaign is None


@pytest.mark.parametrize("slug", ["Net-V12", "net_v12", "a" * 64])
def test_task_run_refuses_a_bad_campaign(run_captured: dict[str, Any], slug: str) -> None:
    result = _task_run("--campaign", slug)
    assert result.exit_code == 2, result.output
    assert "--campaign" in result.output and "spec" not in run_captured


def test_task_run_writes_records_to_the_configured_bucket(
    run_captured: dict[str, Any], bot_workspace: Path
) -> None:
    assert _task_run().exit_code == 0
    records = run_captured["kw"]["records"]
    assert isinstance(records, run_records.RunRecords) and records.bucket == BUCKET
    config = read_config(bot_workspace)
    del config["monitoring"]["cost"]
    write_config(bot_workspace, config)
    assert _task_run().exit_code == 0
    assert run_captured["kw"]["records"] is None


NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _instance(id_: str, age: int, **tags: str) -> tasks.TaskInstance:
    all_tags = {"Project": "braveheart", "Purpose": "ci-task", "RunId": "9-1", "TaskId": id_,
                "Workflow": "Datagen", "Profile": "cpu", "Lifecycle": "spot",
                "MaxLifetimeHours": "6", **tags}  # fmt: skip
    return tasks.TaskInstance(
        id_, "c8a.xlarge", "running", all_tags.get("RunId"), all_tags.get("TaskId"),
        NOW - timedelta(hours=age), 6, tags=all_tags,
    )  # fmt: skip


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch, bot_workspace: Path) -> Iterator[FakeS3]:
    s3 = FakeS3()
    fleet = [
        _instance("i-leaked", 9, Campaign="datagen-2026-12"),
        _instance("i-young", 1),
        _instance("i-untagged", 9, RunId=""),
    ]
    monkeypatch.setattr(tasks, "running_tasks", lambda ec2, project: fleet)
    monkeypatch.setattr(tasks, "terminate", lambda ec2, i, logger: True)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "_run_records", lambda run, session: _records(s3, NOW, NOW))
    yield s3


def test_task_sweep_writes_swept(sweep: FakeS3) -> None:
    with _as_role(TASK_ROLE):
        result = runner.invoke(cli.app, ["task", "sweep"])
    assert result.exit_code == 0, result.output
    ((key, swept),) = sweep.records  # i-untagged has no run to name
    assert key == f"{PREFIX}/date=2026-11-25/9-1.i-leaked.swept.json"
    assert _runs_1(swept)["at"] == "2026-11-25T12:00:00Z"
    assert (swept["campaign"], swept["kind"]) == ("datagen-2026-12", "Datagen")
    assert swept["instance"] == {"type": "c8a.xlarge", "market": "spot", "id": "i-leaked"}
    assert swept["reason"] == (
        "past its lifetime: 9.0 h since launch, over MaxLifetimeHours 6 plus 1 h of setup"
    )
    assert swept["tags"]["Campaign"] == "datagen-2026-12"
    assert "no record" in result.output and "i-untagged" in result.output


def test_task_sweep_dry_run_writes_nothing(sweep: FakeS3) -> None:
    with _as_role(TASK_ROLE):
        result = runner.invoke(cli.app, ["task", "sweep", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert sweep.puts == []
