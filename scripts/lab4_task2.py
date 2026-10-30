"""Read AWS state and capture correlated Lab 4 Task 2 evidence.

No command starts builds, changes approval, subscribes recipients, or changes
alarm state. Snapshot/log commands only write local evidence files.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import boto3

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "northstar-pipeline"
PROJECT = "northstar-ci"
GROUP = "northstar-churn-models"
ALARM = "northstar-ci-build-failure"
LABELS = ("BEFORE", "AFTER FAILED RUN", "AFTER REVERT")
AUTOMATIC = {"Webhook", "WebhookV2"}


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def pages(client, operation, key, **kwargs):
    return [item for page in client.get_paginator(operation).paginate(**kwargs)
            for item in page.get(key, [])]


def log_text(session, build):
    events = pages(session.client("logs"), "filter_log_events", "events",
                   logGroupName=build["logs"]["groupName"],
                   logStreamNames=[build["logs"]["streamName"]])
    return "".join(event["message"].rstrip("\n") + "\n" for event in events)


def notification_state(event):
    """Extract the notification state without committing email/message bodies."""
    info = json.loads(event.get("HistoryData", "{}"))
    published = info.get("publishedMessage")
    if not published:
        return None
    message = json.loads(published)
    default = message.get("default", {})
    if isinstance(default, str):
        default = json.loads(default)
    return default.get("NewStateValue")


def snapshot(session, build_id, execution_id):
    build = session.client("codebuild").batch_get_builds(ids=[build_id])["builds"][0]
    cp = session.client("codepipeline")
    executions = pages(cp, "list_pipeline_executions", "pipelineExecutionSummaries",
                       pipelineName=PIPELINE)
    execution = next((item for item in executions if item["pipelineExecutionId"] == execution_id), None)
    if execution is None:
        raise ValueError("Pipeline execution ID not found")
    revisions = execution.get("sourceRevisions", [])
    if not any(item["revisionId"] == build.get("resolvedSourceVersion") for item in revisions):
        raise ValueError("Build SHA does not match the requested pipeline execution")
    actions = pages(cp, "list_action_executions", "actionExecutionDetails",
                    pipelineName=PIPELINE, filter={"pipelineExecutionId": execution_id})
    if not any(item.get("output", {}).get("executionResult", {}).get("externalExecutionId") == build_id
               for item in actions):
        raise ValueError("Build ID is not linked to the requested pipeline execution")
    sm = session.client("sagemaker")
    packages = pages(sm, "list_model_packages", "ModelPackageSummaryList",
                     ModelPackageGroupName=GROUP, SortBy="CreationTime", SortOrder="Descending")
    cw = session.client("cloudwatch")
    alarm = cw.describe_alarms(AlarmNames=[ALARM])["MetricAlarms"][0]
    history = pages(cw, "describe_alarm_history", "AlarmHistoryItems",
                    AlarmName=ALARM, HistoryItemType="Action")
    actions = [{"Timestamp": item["Timestamp"], "HistorySummary": item["HistorySummary"],
                "NotificationState": notification_state(item)} for item in history]
    topic = alarm["AlarmActions"][0]
    subscriptions = pages(session.client("sns"), "list_subscriptions_by_topic", "Subscriptions",
                          TopicArn=topic)
    # The recipient address stays private; an ARN plus protocol proves confirmation.
    subscriptions = [{"Protocol": item["Protocol"], "SubscriptionArn": item["SubscriptionArn"]}
                     for item in subscriptions]
    return {
        "captured_at": datetime.now(timezone.utc),
        "pipeline_execution": execution,
        "build": {key: build.get(key) for key in
                  ("id", "resolvedSourceVersion", "buildStatus", "startTime", "endTime", "phases")},
        "model_packages": packages,
        "alarm": {key: alarm.get(key) for key in
                  ("AlarmName", "StateValue", "StateUpdatedTimestamp", "ActionsEnabled", "Period")},
        "alarm_actions": actions,
        "subscriptions": subscriptions,
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_snapshots(path):
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^===== (BEFORE|AFTER FAILED RUN|AFTER REVERT) \([^\n]+\) =====\n", text, re.M))
    result = {}
    for match in matches:
        label = match.group(1)
        require(label not in result, f"Duplicate snapshot label: {label}")
        result[label], _ = json.JSONDecoder().raw_decode(text[match.end():])
    return result


def validate_snapshots(snapshots):
    require(set(snapshots) == set(LABELS), "All three labelled snapshots are required")
    before, failed, recovered = (snapshots[label] for label in LABELS)
    for label, item in snapshots.items():
        require(item["pipeline_execution"]["trigger"]["triggerType"] in AUTOMATIC,
                f"{label}: execution was not webhook-triggered")
        require(any(s["Protocol"] == "email" and s["SubscriptionArn"].startswith("arn:")
                    for s in item["subscriptions"]), f"{label}: confirmed email subscription missing")
    require(before["build"]["buildStatus"] == "SUCCEEDED", "Baseline build must succeed")
    require(before["alarm"]["StateValue"] == "OK", "Baseline alarm must be OK")
    require(failed["build"]["buildStatus"] == "FAILED", "Deliberate-failure build must fail")
    phases = {p["phaseType"]: p.get("phaseStatus") for p in failed["build"]["phases"]}
    require(phases.get("PRE_BUILD") == "FAILED", "Deliberate failure must halt PRE_BUILD")
    require("BUILD" not in phases, "Failed run reached BUILD")
    versions = lambda item: {p["ModelPackageVersion"] for p in item["model_packages"]}
    require(versions(before) == versions(failed), "Registry gained a version during the failed run")
    require(failed["alarm"]["StateValue"] == "ALARM", "Failed-run alarm must be ALARM")
    utc = lambda value: datetime.fromisoformat(value).astimezone(timezone.utc)
    require(any(a.get("NotificationState") == "ALARM"
                and "Successfully executed action" in a["HistorySummary"]
                and utc(before["captured_at"]) <= utc(a["Timestamp"]) <= utc(failed["captured_at"])
                for a in failed["alarm_actions"]), "No correlated successful ALARM notification")
    require(recovered["build"]["buildStatus"] == "SUCCEEDED", "Recovery build must succeed")
    require(recovered["alarm"]["StateValue"] == "OK", "Recovery alarm must be OK")
    new = versions(recovered) - versions(failed)
    require(len(new) == 1 and versions(failed) <= versions(recovered), "Recovery must add exactly one package version")
    require(all(p["ModelApprovalStatus"] == "PendingManualApproval"
                for p in recovered["model_packages"] if p["ModelPackageVersion"] in new),
            "Recovery candidate must remain PendingManualApproval")
    shas = {item["build"]["resolvedSourceVersion"] for item in snapshots.values()}
    require(len(shas) == 3, "Baseline, failure, and revert must be distinct commits")


def capture_runs(session, output):
    cp = session.client("codepipeline")
    executions = pages(cp, "list_pipeline_executions", "pipelineExecutionSummaries", pipelineName=PIPELINE)
    cb = session.client("codebuild")
    ids = pages(cb, "list_builds_for_project", "ids", projectName=PROJECT, sortOrder="DESCENDING")
    lines = [f"Captured at {datetime.now(timezone.utc).isoformat()}",
             "===== CodePipeline executions: time, status, SHA, trigger, ID ====="]
    for item in executions:
        revision = ",".join(r["revisionId"] for r in item.get("sourceRevisions", []))
        lines.append(f"{item['startTime']} {item['status']} {revision} {item['trigger']['triggerType']} {item['pipelineExecutionId']}")
    lines.append("===== CodeBuild builds and phases =====")
    for offset in range(0, len(ids), 100):
        for build in cb.batch_get_builds(ids=ids[offset:offset + 100])["builds"]:
            lines.append(f"{build['startTime']} {build['buildStatus']} {build.get('resolvedSourceVersion')} {build['id']}")
            lines.extend(f"  {p['phaseType']} {p.get('phaseStatus', 'IN_PROGRESS')}" for p in build["phases"])
            if build.get("logs", {}).get("streamName"):
                lines.extend("  pytest: " + line for line in log_text(session, build).splitlines()
                             if re.match(r"^=+ .*(passed|failed|error)", line))
    lines.append("===== SageMaker Pipeline executions =====")
    for item in pages(session.client("sagemaker"), "list_pipeline_executions", "PipelineExecutionSummaries",
                      PipelineName="northstar-churn-pipeline"):
        lines.append(f"{item['StartTime']} {item['PipelineExecutionStatus']} {item.get('PipelineExecutionDisplayName')} {item['PipelineExecutionArn']}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--label", choices=LABELS, required=True)
    snap.add_argument("--build-id", required=True)
    snap.add_argument("--execution-id", required=True)
    snap.add_argument("--output", type=Path, default=ROOT / "docs/lab4-failure-demo.txt")
    log = sub.add_parser("save-log")
    log.add_argument("--build-id", required=True)
    log.add_argument("--output", type=Path, required=True)
    runs = sub.add_parser("capture-runs")
    runs.add_argument("--output", type=Path, default=ROOT / "docs/lab4-pipeline-runs.txt")
    validate = sub.add_parser("validate-evidence")
    validate.add_argument("--snapshots", type=Path, default=ROOT / "docs/lab4-failure-demo.txt")
    args = parser.parse_args()
    if args.command == "validate-evidence":
        validate_snapshots(read_snapshots(args.snapshots))
        failed_log = (ROOT / "docs/lab4-build-failed.log").read_text(encoding="utf-8")
        require("Deliberate Lab4 Task2 failure" in failed_log, "Failed log lacks the deliberate assertion")
        image = ROOT / "docs/lab4-alarm-email.png"
        require(image.is_file() and image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Actual alarm email screenshot missing")
        print("Snapshots, deliberate assertion, and screenshot file validated; visually verify email subject and received time.")
        return
    session = boto3.Session(region_name=args.region)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "snapshot":
        existing = read_snapshots(args.output) if args.output.exists() else {}
        require(args.label not in existing, f"Snapshot {args.label} already exists; preserve the original evidence")
        item = snapshot(session, args.build_id, args.execution_id)
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(f"===== {args.label} ({datetime.now(timezone.utc).isoformat()}) =====\n")
            stream.write(json.dumps(item, indent=2, default=json_default) + "\n\n")
    elif args.command == "save-log":
        build = session.client("codebuild").batch_get_builds(ids=[args.build_id])["builds"][0]
        args.output.write_text(log_text(session, build), encoding="utf-8")
    else:
        capture_runs(session, args.output)


if __name__ == "__main__":
    main()
