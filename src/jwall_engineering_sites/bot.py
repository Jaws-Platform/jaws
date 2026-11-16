"""AWS calls for bot projects: the secret, the shared parameters, the
instance, starting and draining it, the status view and the container's logs."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import Logger
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from .errors import PreflightError, RunError
from .project import Project

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_ssm import SSMClient

#: The `Component` tag the container-instance module puts on the instance.
INSTANCE_COMPONENT = "container-instance"
FOLLOW_POLL_SECONDS = 5.0


def put_secret(ssm: SSMClient, name: str, value: str) -> None:
    """Write (or rotate) a SecureString with the account's default SSM key."""
    try:
        ssm.put_parameter(
            Name=name, Value=value, Type="SecureString", Overwrite=True, Tier="Standard"
        )
    except ClientError as exc:
        raise RunError(f"could not write {name}: {exc.response['Error']['Code']}") from exc


def secret_exists(ssm: SSMClient, name: str) -> bool:
    response = ssm.describe_parameters(ParameterFilters=[{"Key": "Name", "Values": [name]}])
    return bool(response.get("Parameters"))


def get_parameters(ssm: SSMClient, names: list[str]) -> dict[str, str | None]:
    response = ssm.get_parameters(Names=names)
    found = {p["Name"]: p["Value"] for p in response.get("Parameters", [])}
    return {name: found.get(name) for name in names}


def put_parameter(ssm: SSMClient, name: str, value: str) -> None:
    ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)


@dataclass(frozen=True)
class InstanceInfo:
    id: str
    state: str
    public_ip: str | None


def find_instance(
    ec2: EC2Client, project: str, component: str = INSTANCE_COMPONENT
) -> InstanceInfo | None:
    """The project's bot instance, by its Project and Component tags."""
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "tag:Component", "Values": [component]},
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            },
        ]
    )
    instances = [i for r in response.get("Reservations", []) for i in r.get("Instances", [])]
    if not instances:
        return None
    if len(instances) > 1:
        ids = ", ".join(i["InstanceId"] for i in instances)
        raise PreflightError(
            f"{len(instances)} instances are tagged Project={project}, Component={component} "
            f"({ids}); exactly one bot may hold the token"
        )
    instance = instances[0]
    return InstanceInfo(
        id=instance["InstanceId"],
        state=instance["State"]["Name"],
        public_ip=instance.get("PublicIpAddress"),
    )


@dataclass(frozen=True)
class BotStatus:
    instance: InstanceInfo | None
    desired: str | None
    running: str | None
    status: str | None
    last_sync: str | None
    profile_url: str | None
    #: The running hours from the project file, or None: always on.
    schedule: str | None = None


#: What the scheduled drain and `bot stop` run on the instance.
DRAIN_COMMAND = "/usr/local/bin/container-reconcile-async --drain"
START_TIMEOUT_SECONDS = 900.0
DRAIN_ACK_SECONDS = 120.0
#: The status `bot start` writes before starting; the boot's reconcile replaces it.
STARTING = "starting"
POWER_POLL_SECONDS = 10.0


def start_instance(
    ec2: EC2Client,
    ssm: SSMClient,
    project: Project,
    logger: Logger,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    timeout: float = START_TIMEOUT_SECONDS,
) -> str:
    """Start the stopped bot instance and wait for the reconciler at boot to end
    (status `ok` or `failed:...`). Returns that status, or "already running"."""
    instance = find_instance(ec2, project.project)
    if instance is None:
        raise PreflightError(f"{project.project} has no bot instance; run `apply` first")
    if instance.state in ("running", "pending"):
        logger.info("%s is already %s", instance.id, instance.state)
        return "already running"
    if instance.state != "stopped":
        raise PreflightError(
            f"{instance.id} is {instance.state}; run `bot start` again once it has stopped"
        )
    status_name = project.parameter("status")
    before = get_parameters(ssm, [status_name])[status_name]
    # Not finished until the reconciler at boot writes ok or failed: a stale `ok`
    # from before the stop must never end the wait early.
    put_parameter(ssm, status_name, STARTING)
    try:
        ec2.start_instances(InstanceIds=[instance.id])
    except ClientError as exc:
        if before is not None:
            put_parameter(ssm, status_name, before)
        raise RunError(f"could not start {instance.id}: {exc.response['Error']['Code']}") from exc
    logger.info("starting %s; waiting for the bot to come up", instance.id)
    deadline = now() + timeout
    while now() < deadline:
        sleep(POWER_POLL_SECONDS)
        current = find_instance(ec2, project.project)
        status = get_parameters(ssm, [status_name])[status_name]
        state = current.state if current else "gone"
        if (
            state == "running"
            and status is not None
            and (status == "ok" or status.startswith("failed:"))
        ):
            logger.info("%s is running; status %s", instance.id, status)
            return status
    raise RunError(
        f"{instance.id} did not report ok within {int(timeout)}s; check `bot status` and `bot logs`"
    )


def drain_instance(
    ec2: EC2Client,
    ssm: SSMClient,
    project: Project,
    logger: Logger,
    wait: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    ack_seconds: float = DRAIN_ACK_SECONDS,
) -> str:
    """Ask the bot instance to drain: the bot finishes its game, ships its records
    and powers off. Returns once the drain has begun (status `waiting:...` or
    `stopped`), or with `wait` once the instance has stopped. A manual drain has no
    deadline: the reconciler waits as long as the game lasts."""
    instance = find_instance(ec2, project.project)
    if instance is None:
        raise PreflightError(f"{project.project} has no bot instance")
    if instance.state in ("stopped", "stopping"):
        logger.info("%s is already %s", instance.id, instance.state)
        return instance.state
    if instance.state != "running":
        raise PreflightError(f"{instance.id} is {instance.state}; try again once it is running")
    status_name = project.parameter("status")
    try:
        ssm.send_command(
            InstanceIds=[instance.id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [DRAIN_COMMAND], "executionTimeout": ["120"]},
            Comment="jwall-engineering-sites bot stop",
        )
    except ClientError as exc:
        raise RunError(
            f"could not send the drain to {instance.id}: {exc.response['Error']['Code']}"
        ) from exc
    logger.info(
        "asked %s to drain; the bot finishes its game, then the instance stops", instance.id
    )
    deadline = now() + ack_seconds
    while True:
        status = get_parameters(ssm, [status_name])[status_name] or ""
        current = find_instance(ec2, project.project)
        state = current.state if current else "gone"
        if state in ("stopping", "stopped"):
            logger.info("%s is %s", instance.id, state)
            return state
        draining = status.startswith("waiting:") or status == "stopped"
        if draining and not wait:
            logger.info("draining (status %s); it stops once the game in progress ends", status)
            return status
        if not draining and now() >= deadline:
            raise RunError(
                f"{instance.id} has not started draining after {int(ack_seconds)}s (status "
                f"{status or 'not set'}). An instance from before the drain mode ignores it: "
                "apply the stack (library 0.22.0 or later), then try again"
            )
        sleep(POWER_POLL_SECONDS)


def status(session: boto3.session.Session, project: Project) -> BotStatus:
    names = [project.parameter(n) for n in ("desired-version", "running-version", "status")]
    names.append(project.parameter("last-sync"))
    values = get_parameters(session.client("ssm"), names)
    return BotStatus(
        instance=find_instance(session.client("ec2"), project.project),
        desired=values[names[0]],
        running=values[names[1]],
        status=values[names[2]],
        last_sync=values[names[3]],
        profile_url=project.profile_url,
        schedule=project.bot.schedule.describe() if project.bot.schedule else None,
    )


def render_status(s: BotStatus) -> str:
    instance = (
        f"{s.instance.id} ({s.instance.state}, {s.instance.public_ip or 'no public IP'})"
        if s.instance
        else "none"
    )
    rows = [
        ("instance", instance),
        ("desired version", s.desired or "not set"),
        ("running version", s.running or "not set"),
        ("status", s.status or "not set"),
        ("running hours", s.schedule or "always on"),
        ("last records sync", s.last_sync or "never"),
        ("lichess profile", s.profile_url or "not configured (lichess_user)"),
    ]
    width = max(len(k) for k, _ in rows) + 2
    return "\n".join(f"{k + ':':<{width}}{v}" for k, v in rows)


def tail_logs(
    logs: CloudWatchLogsClient,
    group: str,
    since_seconds: int,
    follow: bool,
    logger: Logger,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    max_polls: int | None = None,
) -> Iterator[str]:
    """Events of the log group as `<iso time> <stream> <message>`, oldest first.
    With `follow`, keeps polling every 5 s (forever unless `max_polls`)."""
    start = int(now() * 1000) - since_seconds * 1000
    polls = 0
    while True:
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {"logGroupName": group, "startTime": start}
            if token:
                kwargs["nextToken"] = token
            try:
                page = logs.filter_log_events(**kwargs)  # type: ignore[arg-type]
            except ClientError as exc:
                raise RunError(f"cannot read {group}: {exc.response['Error']['Code']}") from exc
            for event in page.get("events", []):
                stamp = datetime.fromtimestamp(event["timestamp"] / 1000, tz=UTC)
                start = max(start, event["timestamp"] + 1)
                yield (
                    f"{stamp.isoformat(timespec='seconds')} {event['logStreamName']} "
                    f"{event['message'].rstrip()}"
                )
            token = page.get("nextToken")
            if not token:
                break
        if not follow or (max_polls is not None and polls >= max_polls):
            return
        polls += 1
        logger.debug("following %s", group)
        sleep(FOLLOW_POLL_SECONDS)
