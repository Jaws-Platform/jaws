from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from jaws.aws import (
    check_any_role,
    check_bucket,
    check_role,
    invalidate_distribution,
    role_name_from_arn,
)
from jaws.errors import PreflightError

if TYPE_CHECKING:
    from mypy_boto3_sts import STSClient

ROLE_ARN = "arn:aws:sts::570327089884:assumed-role/jaws-guitar-knowledge-base-ci-plan/gha-plan-pr-1"
USER_ARN = "arn:aws:iam::570327089884:user/example-user"


def _sts(arn: str) -> tuple[STSClient, Stubber]:
    sts = boto3.client("sts", region_name="us-east-1")
    stub = Stubber(sts)
    stub.add_response(
        "get_caller_identity",
        {"Account": arn.split(":")[4], "Arn": arn, "UserId": "AROAEXAMPLE:session"},
    )
    stub.activate()
    return sts, stub


def test_role_name_from_arn() -> None:
    assert role_name_from_arn(ROLE_ARN) == "jaws-guitar-knowledge-base-ci-plan"
    assert role_name_from_arn(USER_ARN) is None


def test_check_role_accepts_the_expected_role(logger: logging.Logger) -> None:
    sts, _ = _sts(ROLE_ARN)
    assert check_role(sts, "jaws-guitar-knowledge-base-ci-plan", logger, environ={}) == ROLE_ARN


def test_check_role_rejects_another_role(logger: logging.Logger) -> None:
    sts, _ = _sts(ROLE_ARN)
    with pytest.raises(
        PreflightError,
        match="must run as the jaws-guitar-knowledge-base-ci-apply role",
    ):
        check_role(sts, "jaws-guitar-knowledge-base-ci-apply", logger, environ={})


def test_check_role_rejects_a_user(logger: logging.Logger) -> None:
    sts, _ = _sts(USER_ARN)
    with pytest.raises(PreflightError, match="not an assumed role"):
        check_role(sts, "jaws-guitar-knowledge-base-ci-plan", logger, environ={})


def test_check_role_can_be_skipped_with_a_warning(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    sts, _ = _sts(USER_ARN)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        arn = check_role(sts, "any-role", logger, environ={"JAWS_SKIP_ROLE_CHECK": "1"})
    assert arn == USER_ARN
    assert "JAWS_SKIP_ROLE_CHECK=1" in caplog.text


@mock_aws
def test_check_bucket() -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="exists")
    check_bucket(s3, "exists")
    with pytest.raises(PreflightError, match="does not exist"):
        check_bucket(s3, "missing")


@mock_aws
def test_invalidate_distribution() -> None:
    cloudfront = boto3.client("cloudfront", region_name="us-east-1")
    distribution = cloudfront.create_distribution(
        DistributionConfig={
            "CallerReference": "test",
            "Comment": "",
            "Enabled": True,
            "Origins": {
                "Quantity": 1,
                "Items": [
                    {
                        "Id": "origin",
                        "DomainName": "bucket.s3.us-east-1.amazonaws.com",
                        "S3OriginConfig": {"OriginAccessIdentity": ""},
                    }
                ],
            },
            "DefaultCacheBehavior": {
                "TargetOriginId": "origin",
                "ViewerProtocolPolicy": "redirect-to-https",
                "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}},
                "MinTTL": 0,
            },
        }
    )
    invalidation = invalidate_distribution(cloudfront, distribution["Distribution"]["Id"], "ref")
    assert invalidation


def test_check_role_refuses_another_accounts_credentials(logger: logging.Logger) -> None:
    """Role names differ between the accounts, but a run with admin credentials
    skips the role check: the account is checked first, and always."""
    sts, stubber = _sts("arn:aws:sts::650503560686:assumed-role/jaws-guitar-ci-plan/s")
    with stubber, pytest.raises(PreflightError, match=r"650503560686.*570327089884"):
        check_role(sts, "jaws-guitar-ci-plan", logger, environ={}, account_id="570327089884")


def test_skipping_the_role_check_does_not_skip_the_account_check(logger: logging.Logger) -> None:
    sts, stubber = _sts("arn:aws:sts::650503560686:assumed-role/AWSReservedSSO_Admin_0f/owner")
    with stubber, pytest.raises(PreflightError, match="650503560686"):
        check_role(
            sts,
            "any-role",
            logger,
            environ={"JAWS_SKIP_ROLE_CHECK": "1"},
            account_id="570327089884",
        )


def test_check_role_accepts_the_addressed_accounts_credentials(logger: logging.Logger) -> None:
    arn = "arn:aws:sts::570327089884:assumed-role/jaws-guitar-ci-plan/s"
    sts, stubber = _sts(arn)
    with stubber:
        assert (
            check_role(
                sts,
                "jaws-guitar-ci-plan",
                logger,
                environ={},
                account_id="570327089884",
            )
            == arn
        )


def test_check_any_role_refuses_another_accounts_credentials(logger: logging.Logger) -> None:
    sts, stubber = _sts("arn:aws:sts::650503560686:assumed-role/jaws-guitar-ci-plan/s")
    with stubber, pytest.raises(PreflightError, match="650503560686"):
        check_any_role(sts, ["jaws-guitar-ci-plan"], logger, environ={}, account_id="570327089884")
