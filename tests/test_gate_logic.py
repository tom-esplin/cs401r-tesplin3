"""Failure-path checks for model gates; no live AWS calls or candidate needed."""

import io
import json
from unittest.mock import MagicMock
import warnings

import pytest
from botocore.exceptions import ClientError

from evaluation.model_gates import (
    check_champion_regression, load_champion, validate_evaluation_metrics,
    warn_fairness_gap,
)


def slice_metrics(recalls=(0.2, 0.2, 0.2, 0.2)):
    metrics = {}
    for tier, recall in zip(("bronze", "silver", "gold", "platinum"), recalls):
        metrics.update({f"slice_{tier}_n": 100, f"slice_{tier}_n_positive": 20,
                        f"slice_{tier}_auc": 0.7, f"slice_{tier}_recall_top10": recall})
    return metrics


def test_fairness_warns_without_failing_and_ten_point_boundary_is_quiet():
    with pytest.warns(UserWarning, match="Fairness flag"):
        assert warn_fairness_gap(slice_metrics((0.1, 0.3, 0.2, 0.2))) == pytest.approx(0.2)
    with warnings.catch_warnings(record=True) as caught:
        assert warn_fairness_gap(slice_metrics((0.2, 0.3, 0.2, 0.2))) == pytest.approx(0.1)
    assert not caught


def test_unusable_slice_evidence_blocks_the_gate():
    for key, value in (("slice_gold_n_positive", 0),
                       ("slice_bronze_recall_top10", None),
                       ("slice_silver_auc", float("nan"))):
        metrics = slice_metrics()
        metrics[key] = value
        with pytest.raises(ValueError):
            warn_fairness_gap(metrics)


@pytest.mark.parametrize("candidate,passes", [(0.78, True), (0.7799, False), (0.81, True)])
def test_regression_tolerance_and_warning(candidate, passes):
    champion = {"version": 7, "auc": 0.8}
    with pytest.warns(UserWarning, match="champion v7 auc=0.8000; candidate auc="):
        if passes:
            check_champion_regression(candidate, champion)
        else:
            with pytest.raises(ValueError, match="regresses"):
                check_champion_regression(candidate, champion)


def test_champion_lookup_filters_approved_packages_and_reads_registered_metrics():
    sm, s3 = MagicMock(), MagicMock()
    arn = "arn:aws:sagemaker:us-east-1:123456789012:model-package/northstar-churn-models/7"
    sm.get_paginator.return_value.paginate.return_value = iter([
        {"ModelPackageSummaryList": []},
        {"ModelPackageSummaryList": [{"ModelPackageArn": arn}]},
    ])
    sm.describe_model_package.return_value = {
        "ModelApprovalStatus": "Approved", "ModelPackageVersion": 7,
        "ModelMetrics": {"ModelQuality": {"Statistics": {"S3Uri": "s3://bucket/metrics.json"}}},
    }
    s3.get_object.return_value = {"Body": io.BytesIO(json.dumps({"auc_roc": 0.8}).encode())}
    assert load_champion(sm, s3) == {"version": 7, "auc": 0.8, "arn": arn}
    sm.get_paginator.return_value.paginate.assert_called_once_with(
        ModelPackageGroupName="northstar-churn-models", ModelApprovalStatus="Approved",
        SortBy="CreationTime", SortOrder="Descending",
    )
    sm.describe_model_package.assert_called_once_with(ModelPackageName=arn)
    s3.get_object.assert_called_once_with(Bucket="bucket", Key="metrics.json")


def test_no_champion_is_distinct_from_an_aws_failure():
    sm, s3 = MagicMock(), MagicMock()
    sm.get_paginator.return_value.paginate.return_value = [{"ModelPackageSummaryList": []}]
    assert load_champion(sm, s3) is None
    s3.get_object.assert_not_called()
    sm.get_paginator.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListModelPackages")
    with pytest.raises(ClientError):
        load_champion(sm, s3)


@pytest.mark.parametrize("name,value", [("auc_roc", None), ("precision_top10", float("nan")),
                                        ("recall_top10", 2), ("lift_ci_low", float("inf"))])
def test_missing_or_invalid_evaluation_metrics_fail(name, value):
    metrics = {"auc_roc": 0.8, "precision_top10": 0.7, "recall_top10": 0.3,
               "positive_rate_val": 0.22, "baseline_auc": 0.7,
               "lift_ci_low": 0.01, "lift_ci_high": 0.1}
    metrics[name] = value
    with pytest.raises(ValueError):
        validate_evaluation_metrics(metrics)
