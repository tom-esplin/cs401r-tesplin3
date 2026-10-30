"""Guard against accepting manual starts or unrelated failures as Task 2 proof."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from scripts.lab4_task2 import notification_state, read_snapshots, validate_snapshots


def demonstration():
    base = {
        "captured_at": "2026-10-30T12:00:00+00:00",
        "pipeline_execution": {"trigger": {"triggerType": "WebhookV2"}},
        "build": {"buildStatus": "SUCCEEDED", "resolvedSourceVersion": "baseline", "phases": []},
        "model_packages": [{"ModelPackageVersion": 2, "ModelApprovalStatus": "Approved"}],
        "alarm": {"StateValue": "OK"}, "alarm_actions": [],
        "subscriptions": [{"Protocol": "email", "SubscriptionArn": "arn:aws:sns:confirmed"}],
    }
    failed = deepcopy(base)
    failed.update(captured_at="2026-10-30T12:10:00+00:00",
                  alarm={"StateValue": "ALARM"},
                  alarm_actions=[{"Timestamp": "2026-10-30T06:05:00-06:00",
                                  "NotificationState": "ALARM",
                                  "HistorySummary": "Successfully executed action arn:aws:sns:topic"}])
    failed["build"] = {"buildStatus": "FAILED", "resolvedSourceVersion": "failure",
                       "phases": [{"phaseType": "PRE_BUILD", "phaseStatus": "FAILED"}]}
    recovered = deepcopy(base)
    recovered["captured_at"] = "2026-10-30T12:30:00+00:00"
    recovered["build"]["resolvedSourceVersion"] = "revert"
    recovered["model_packages"].append({"ModelPackageVersion": 3, "ModelApprovalStatus": "PendingManualApproval"})
    return {"BEFORE": base, "AFTER FAILED RUN": failed, "AFTER REVERT": recovered}


def test_valid_demonstration_handles_mixed_timezone_offsets():
    validate_snapshots(demonstration())


@pytest.mark.parametrize("mistake", ["manual", "training_started", "new_version", "unconfirmed",
                                     "old_notification", "recovery_failed", "candidate_approved"])
def test_incomplete_or_misleading_evidence_is_rejected(mistake):
    snapshots = demonstration()
    failed = snapshots["AFTER FAILED RUN"]
    recovered = snapshots["AFTER REVERT"]
    if mistake == "manual":
        failed["pipeline_execution"]["trigger"]["triggerType"] = "StartPipelineExecution"
    elif mistake == "training_started":
        failed["build"]["phases"].append({"phaseType": "BUILD", "phaseStatus": "SUCCEEDED"})
    elif mistake == "new_version":
        failed["model_packages"].append({"ModelPackageVersion": 3, "ModelApprovalStatus": "Rejected"})
    elif mistake == "unconfirmed":
        failed["subscriptions"][0]["SubscriptionArn"] = "PendingConfirmation"
    elif mistake == "old_notification":
        failed["alarm_actions"][0]["Timestamp"] = "2026-10-29T12:05:00+00:00"
    elif mistake == "recovery_failed":
        recovered["build"]["buildStatus"] = "FAILED"
    else:
        recovered["model_packages"][-1]["ModelApprovalStatus"] = "Approved"
    with pytest.raises(ValueError):
        validate_snapshots(snapshots)


def test_snapshot_file_roundtrip_and_duplicate_labels_fail(tmp_path):
    path = tmp_path / "evidence.txt"
    records = demonstration()
    text = "".join(f"===== {label} (2026-10-30T12:30:00Z) =====\n{json.dumps(item)}\n\n"
                   for label, item in records.items())
    path.write_text(text, encoding="utf-8")
    assert read_snapshots(path) == records
    path.write_text(text + text, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate snapshot"):
        read_snapshots(path)


def test_notification_summary_omits_recipient_and_message_body():
    event = {"HistoryData": json.dumps({"publishedMessage": json.dumps({
        "default": json.dumps({"NewStateValue": "ALARM"}), "email": "private email body",
    })})}
    assert notification_state(event) == "ALARM"
    assert notification_state({"HistoryData": "{}"}) is None


def test_template_uses_one_native_push_trigger_for_configured_branch():
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, tag, node: {tag: loader.construct_scalar(node)})
    template = yaml.load((Path(__file__).resolve().parents[1] / "pipeline.yaml").read_text(encoding="utf-8"), Loader=Loader)
    properties = template["Resources"]["NorthStarPipeline"]["Properties"]
    assert properties["PipelineType"] == "V2"
    assert properties["ExecutionMode"] == "SUPERSEDED"
    assert len(properties["Triggers"]) == 1
    trigger = properties["Triggers"][0]
    assert trigger == {
        "ProviderType": "CodeStarSourceConnection",
        "GitConfiguration": {"SourceActionName": "GitHubSource", "Push": [
            {"Branches": {"Includes": [{"Ref": "GitHubBranch"}]}}
        ]},
    }
    source = properties["Stages"][0]["Actions"][0]
    assert source["Name"] == "GitHubSource"
    assert source["Configuration"]["DetectChanges"] is False
