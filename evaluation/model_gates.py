"""Lab 4 model gates; AWS access is limited to reading the approved champion."""

import json
import math
import warnings
from decimal import Decimal
from urllib.parse import urlparse

TIERS = ("bronze", "silver", "gold", "platinum")


def probability(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return float(value)


def validate_evaluation_metrics(metrics):
    for name in ("auc_roc", "precision_top10", "recall_top10", "positive_rate_val"):
        probability(metrics.get(name), name)
    probability(metrics.get("baseline_auc_roc", metrics.get("baseline_auc")), "baseline_auc")
    lo, hi = metrics.get("lift_ci_low"), metrics.get("lift_ci_high")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lo, hi)):
        raise ValueError("lift_ci_low and lift_ci_high must be finite numbers")
    if not -1 <= lo <= hi <= 1:
        raise ValueError("Invalid AUC lift confidence interval")


def tier_recalls(metrics):
    recalls = {}
    for tier in TIERS:
        prefix = f"slice_{tier}"
        n, positive = metrics.get(f"{prefix}_n"), metrics.get(f"{prefix}_n_positive")
        if type(n) is not int or type(positive) is not int or not 0 < positive <= n:
            raise ValueError(f"{tier}: slice counts must include at least one positive")
        probability(metrics.get(f"{prefix}_auc"), f"{prefix}_auc")
        recalls[tier] = probability(metrics.get(f"{prefix}_recall_top10"), f"{prefix}_recall_top10")
    return recalls


def warn_fairness_gap(metrics):
    recalls = tier_recalls(metrics)
    gap = max(recalls.values()) - min(recalls.values())
    if Decimal(str(max(recalls.values()))) - Decimal(str(min(recalls.values()))) > Decimal("0.10"):
        warnings.warn(f"Fairness flag: loyalty-tier recall gap={gap:.4f} exceeds 0.10; recalls={recalls}", UserWarning, stacklevel=2)
    return gap


def load_champion(sm, s3):
    """Newest Approved package, never the PendingManualApproval candidate.

    Return None only when there is no Approved package. Permission, transport,
    missing object, and malformed metric errors deliberately propagate.
    """
    pages = sm.get_paginator("list_model_packages").paginate(
        ModelPackageGroupName="northstar-churn-models",
        ModelApprovalStatus="Approved", SortBy="CreationTime", SortOrder="Descending",
    )
    for page in pages:
        for package in page["ModelPackageSummaryList"]:
            arn = package["ModelPackageArn"]
            detail = sm.describe_model_package(ModelPackageName=arn)
            if detail["ModelApprovalStatus"] != "Approved":
                raise ValueError("Champion approval changed during evaluation; retry the build")
            uri = urlparse(detail["ModelMetrics"]["ModelQuality"]["Statistics"]["S3Uri"])
            if uri.scheme != "s3" or not uri.netloc or not uri.path.lstrip("/"):
                raise ValueError("Champion metrics must reference an S3 object")
            response = s3.get_object(Bucket=uri.netloc, Key=uri.path.lstrip("/"))
            body = response["Body"]
            try:
                metrics = json.loads(body.read())
            finally:
                body.close()
            auc = probability(metrics.get("auc_roc"), "champion auc_roc")
            return {"version": detail["ModelPackageVersion"], "auc": auc, "arn": arn}
    return None


def check_champion_regression(candidate_auc, champion):
    candidate_auc = probability(candidate_auc, "candidate auc_roc")
    champion_auc = probability(champion["auc"], "champion auc_roc")
    warnings.warn(
        f"champion v{champion['version']} auc={champion_auc:.4f}; candidate auc={candidate_auc:.4f}",
        UserWarning, stacklevel=2,
    )
    if Decimal(str(candidate_auc)) < Decimal(str(champion_auc)) - Decimal("0.02"):
        raise ValueError(f"Candidate AUC {candidate_auc:.4f} regresses more than 0.02 from champion {champion_auc:.4f}")
