"""Task-run records: one JSON object per event of a task run, for cost per run.

`task run` writes `started` the moment its instance launches and `finished`
once the task has ended and its instance is terminated; `task sweep` writes
`swept` when it terminates a leaked instance. They go to the billing bucket
(`monitoring.cost.bucket`, config/monitoring.yaml), at

    raw/provider=jaws/source=task-runs/project=<p>/date=YYYY-MM-DD/<run-id>.<task-id>.<event>.json

write-once, like every raw delivery. The monitoring stack's normalizer reads
them as its `runs` source, schema runs-1 (terraform-aws-jaws-monitoring,
modules/billing-normalizer), and the node joins each run to its billing rows on
the RunId and TaskId tags its instance and volume carry.

Like the event log (events.py), a record can never fail a run: its client gives
up within seconds, and a write that fails is a warning. Without monitoring.cost
there is no writer at all, and nothing is said.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from logging import Logger
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

SCHEMA = "runs-1"
EVENTS = ("started", "finished", "swept")
#: The runs prefix in the billing bucket; the monitoring stack's `runs` input names it too.
PREFIX = "raw/provider=jaws/source=task-runs"
#: The tags a run's billing rows are joined on (the normalizer's run_join_tags).
JOIN_TAGS = ("RunId", "TaskId")
#: A record waits for S3 at most a few seconds, once retried, and is then dropped
#: with a warning: a slow bucket never holds a task.
CLIENT_CONFIG = Config(
    connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2, "mode": "standard"}
)
_KEY_PART = re.compile(r"[^A-Za-z0-9._-]")


def _now() -> datetime:
    return datetime.now(UTC)


def timestamp(at: datetime) -> str:
    """An ISO 8601 UTC time to the second, as the records carry it."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    event: str, *, project: str, tags: Mapping[str, str], at: datetime, **fields: Any
) -> dict[str, Any]:
    """A runs-1 record: the fields the normalizer requires (schema, event, at,
    tags with every join tag, project), then the event's own."""
    if event not in EVENTS:
        raise ValueError(f"a run record's event is one of {', '.join(EVENTS)}, not {event!r}")
    return {
        "schema": SCHEMA,
        "event": event,
        "at": timestamp(at),
        "tags": dict(tags),
        "project": project,
        **fields,
    }


def key(record: Mapping[str, Any]) -> str:
    """Where a record lives: its project's prefix, the UTC date of its event, then
    `<run-id>.<task-id>.<event>.json`, each part kept to one file name."""
    tags = record["tags"]
    run_id, task_id = (_KEY_PART.sub("-", tags[tag]) for tag in JOIN_TAGS)
    day = datetime.fromisoformat(record["at"]).strftime("%Y-%m-%d")
    return (
        f"{PREFIX}/project={record['project']}/date={day}/{run_id}.{task_id}.{record['event']}.json"
    )


def links(repository: str, commit: str, pull_request: str | None) -> dict[str, str]:
    """The run's GitHub Actions run (with its attempt), pull request and commit,
    which the Cost · Tasks table links. The run link exists only in a workflow."""
    server = os.environ.get("GITHUB_SERVER_URL") or "https://github.com"
    found: dict[str, str] = {}
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        actions = os.environ.get("GITHUB_REPOSITORY") or repository
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT") or "1"
        found["run"] = f"{server}/{actions}/actions/runs/{run_id}/attempts/{attempt}"
    if pull_request:
        found["pr"] = f"{server}/{repository}/pull/{pull_request}"
    found["commit"] = f"{server}/{repository}/commit/{commit}"
    return found


class RunRecords:
    """Writes run records to the billing bucket. `write` never raises for S3."""

    def __init__(
        self, s3: S3Client, bucket: str, logger: Logger, now: Callable[[], datetime] = _now
    ) -> None:
        self.s3 = s3
        self.bucket = bucket
        self._logger = logger
        self._now = now

    @classmethod
    def from_settings(
        cls, settings: Settings, session: boto3.session.Session, logger: Logger
    ) -> RunRecords | None:
        """The writer for the configured billing bucket, or None without
        monitoring.cost: then no record is written, and nothing is said."""
        cost = settings.monitoring.cost if settings.monitoring is not None else None
        if cost is None:
            return None
        return cls(session.client("s3", config=CLIENT_CONFIG), cost.bucket, logger)

    def now(self) -> datetime:
        return self._now()

    def write(self, record: Mapping[str, Any]) -> bool:
        """Put the record once (a retry after a write that landed finds it there).
        Returns whether it is stored; a failure is a warning naming the error."""
        where = key(record)
        event = record["event"]
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=where,
                Body=json.dumps(record, sort_keys=True).encode(),
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "unknown")
            if code in ("PreconditionFailed", "412"):
                self._logger.debug("the %s record %s is already written", event, where)
                return True
            self._logger.warning("the %s record %s was not written: %s", event, where, code)
            return False
        except BotoCoreError as error:
            self._logger.warning(
                "the %s record %s was not written: %s", event, where, type(error).__name__
            )
            return False
        self._logger.debug("wrote the %s record s3://%s/%s", event, self.bucket, where)
        return True
