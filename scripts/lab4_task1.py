"""Stage real Lab 2 data or capture verified Task 1 CI evidence.

Only reads AWS resources. Run with the isolated churn Python environment.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import boto3

ROOT = Path(__file__).resolve().parents[1]


def stage_data(session, bucket):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = ROOT / "artifacts" / "lab4" / "data" / stamp
    destination.mkdir(parents=True)
    s3 = session.client("s3")
    raw = destination / "northstar-raw-sample.csv"
    s3.download_file(bucket, "raw/customers/northstar-raw-sample.csv", str(raw))
    paths = {"NORTHSTAR_RAW": str(raw)}
    for kind in ("processed", "features"):
        folder = destination / kind
        folder.mkdir()
        prefix = f"{kind}/customers/"
        count = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not key.endswith(".parquet") or "_glue_temp" in key:
                    continue
                target = (folder / key[len(prefix):]).resolve()
                if not target.is_relative_to(folder.resolve()):
                    raise ValueError("S3 key would escape its local dataset directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(target))
                count += 1
        if not count:
            raise ValueError(f"No Parquet output under s3://{bucket}/{prefix}")
        paths[f"NORTHSTAR_{kind.upper()}"] = str(folder)
    manifest = destination / "paths.json"
    manifest.write_text(json.dumps(paths, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest), **paths}, indent=2))


def capture(session, build_id):
    build = session.client("codebuild").batch_get_builds(ids=[build_id])["builds"][0]
    if build["buildStatus"] != "SUCCEEDED":
        raise ValueError("Final Task 1 evidence must come from a SUCCEEDED build")
    logs = session.client("logs")
    events = []
    for page in logs.get_paginator("filter_log_events").paginate(
        logGroupName=build["logs"]["groupName"], logStreamNames=[build["logs"]["streamName"]],
    ):
        events.extend(page["events"])
    text = "".join(event["message"].rstrip("\n") + "\n" for event in events)
    for name, minimum in (("data", 2), ("features", 5), ("model", 2), ("fairness", 2)):
        count = len(re.findall(rf"tests/test_{name}\.py::[^\n]*\bPASSED\b", text))
        if count < minimum:
            raise ValueError(f"Build log has only {count} passing {name} tests; expected {minimum}")
    if not re.search(r"test_candidate_does_not_regress_against_approved_champion[^\n]*\bPASSED\b", text):
        raise ValueError("Champion regression did not pass; bootstrap runs are not final evidence")
    if not re.search(r"champion v\d+ auc=", text):
        raise ValueError("Champion version/AUC warning is missing")
    if "Fairness flag:" not in text:
        raise ValueError("Expected fairness warning is missing from the final evidence")
    if "Pipeline succeeded" not in text or "Registered:" not in text:
        raise ValueError("Training pipeline success or registration evidence is missing")
    sm = session.client("sagemaker")
    packages = []
    for page in sm.get_paginator("list_model_packages").paginate(
        ModelPackageGroupName="northstar-churn-models", SortBy="CreationTime", SortOrder="Descending",
    ):
        packages.extend(page["ModelPackageSummaryList"])
    versions = {int(v) for v in re.findall(r"champion v(\d+) auc=", text)}
    if not any(p["ModelPackageVersion"] in versions and p["ModelApprovalStatus"] == "Approved" for p in packages):
        raise ValueError("The champion shown in the log is not Approved in the registry")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "lab4-build-green.log").write_text(text, encoding="utf-8")
    (docs / "lab4-model-registry.json").write_text(
        json.dumps({"ModelPackageSummaryList": packages}, indent=2, default=str) + "\n", encoding="utf-8",
    )
    print(f"Captured build {build_id}, commit {build['resolvedSourceVersion']}, and {len(packages)} registry versions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage-data")
    stage.add_argument("--bucket", required=True)
    evidence = sub.add_parser("capture")
    evidence.add_argument("--build-id", required=True)
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    if args.command == "stage-data":
        stage_data(session, args.bucket)
    else:
        capture(session, args.build_id)


if __name__ == "__main__":
    main()
