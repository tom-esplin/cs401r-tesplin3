"""Capture existing MLflow runs and verified SageMaker registry provenance.

No training or approval changes. Lineage writes require --write-lineage.
"""

import argparse
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
APP = "arn:aws:sagemaker:us-east-1:278634873542:mlflow-app/app-2DBMQ67QFI76"
GROUP = "northstar-churn-models"
ACCOUNT = "278634873542"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def export_mlflow():
    import mlflow

    mlflow.set_tracking_uri(APP)
    runs = mlflow.search_runs(experiment_names=["northstar-churn"], max_results=1000)
    params = sorted(c for c in runs if c.startswith("params."))
    metrics = sorted(c for c in runs if c.startswith("metrics."))
    completed = runs[runs.status == "FINISHED"]
    if len(completed[params].drop_duplicates()) < 3:
        raise ValueError("Need three completed, distinct hyperparameter configurations")
    if not metrics or completed[metrics].isna().any().any():
        raise ValueError("Completed runs must contain all logged metrics")
    cols = ["run_id", "tags.mlflow.runName", "start_time", "status"] + params + metrics
    (DOCS / "lab4-mlflow-runs.txt").write_text(
        f"tracking_uri: {APP}\nexperiment: northstar-churn\n"
        f"captured_at: {datetime.now(timezone.utc).isoformat()}\n\n"
        + runs[cols].to_string(index=False) + "\n", encoding="utf-8",
    )
    print(f"Exported {len(runs)} MLflow runs; {len(completed[params].drop_duplicates())} distinct configurations", flush=True)


def source_revision(short):
    if short == "unknown" or len(short) < 8:
        raise ValueError("Training job has no verifiable commit")
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", short + "^{commit}"], cwd=ROOT, text=True,
    ).strip()
    subprocess.run(["git", "merge-base", "--is-ancestor", sha, "main"], cwd=ROOT, check=True)
    return sha


def data_snapshot(s3, uri, at):
    """Reconstruct the versioned prefix as of job start, including deletions."""
    parsed = urlparse(uri)
    latest = {}
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=parsed.netloc, Prefix=parsed.path.lstrip("/")):
        for kind in ("Versions", "DeleteMarkers"):
            for item in page.get(kind, []):
                if item["LastModified"] <= at and (
                    item["Key"] not in latest or item["LastModified"] > latest[item["Key"]][1]["LastModified"]
                ):
                    latest[item["Key"]] = kind, item
    objects = []
    times = []
    for kind, item in latest.values():
        if kind != "Versions" or not item["Key"].endswith(".parquet") or "_glue_temp" in item["Key"]:
            continue
        body = s3.get_object(Bucket=parsed.netloc, Key=item["Key"], VersionId=item["VersionId"])["Body"].read()
        frame = pd.read_parquet(io.BytesIO(body), columns=["event_time"])
        values = pd.to_numeric(frame.event_time, errors="raise")
        if not values.notna().all():
            raise ValueError("Missing dataset event_time")
        times.extend([float(values.min()), float(values.max())])
        objects.append({k: item[k] for k in ("Key", "VersionId", "LastModified", "ETag", "Size")})
    if not objects:
        raise ValueError("Cannot recover training Parquet versions")
    return {
        "s3_uri": uri,
        "as_of_training_start": at,
        "data_timestamp": max(o["LastModified"] for o in objects).astimezone(timezone.utc).isoformat(),
        "timestamp_meaning": "Latest S3 LastModified of recovered training Parquet versions at job start; not the business observation cutoff",
        "event_time_min": datetime.fromtimestamp(min(times), timezone.utc).isoformat(),
        "event_time_max": datetime.fromtimestamp(max(times), timezone.utc).isoformat(),
        "objects": sorted(objects, key=lambda o: o["Key"]),
    }


def capture_lineage(session, write):
    sm = session.client("sagemaker")
    s3 = session.client("s3")
    snapshots, unrecoverable = {}, []
    for page in sm.get_paginator("list_model_packages").paginate(ModelPackageGroupName=GROUP):
        for summary in page["ModelPackageSummaryList"]:
            package = sm.describe_model_package(ModelPackageName=summary["ModelPackageArn"])
            execution = package.get("MetadataProperties", {}).get("GeneratedBy")
            if not execution or ":pipeline/" not in execution:
                unrecoverable.append({"package": package["ModelPackageArn"], "reason": "No training-job execution lineage; existing Lab 3 metadata preserved"})
                continue
            steps = sm.list_pipeline_execution_steps(PipelineExecutionArn=execution)["PipelineExecutionSteps"]
            jobs = [s["Metadata"]["TrainingJob"]["Arn"] for s in steps if s.get("Metadata", {}).get("TrainingJob")]
            if len(jobs) != 1:
                raise ValueError("Expected exactly one training job")
            job = sm.describe_training_job(TrainingJobName=jobs[0].split("/")[-1])
            sha = source_revision(job["Environment"]["COMMIT_SHA"])
            channels = [c for c in job["InputDataConfig"] if c["ChannelName"] == "training"]
            uri = channels[0]["DataSource"]["S3DataSource"]["S3Uri"]
            snapshot = data_snapshot(s3, uri, job["TrainingStartTime"])
            metrics_uri = package["ModelMetrics"]["ModelQuality"]["Statistics"]["S3Uri"]
            parsed = urlparse(metrics_uri)
            metrics = json.loads(s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"].read())
            metadata = {
                "training_data_s3_uri": uri,
                "training_data_timestamp": snapshot["data_timestamp"],
                "training_data_timestamp_basis": "S3 LastModified of training Parquet versions recovered as of training start",
                "training_data_event_time": snapshot["event_time_max"],
                "commit_sha": sha,
                "training_job_arn": jobs[0],
                "evaluation_metrics_s3_uri": metrics_uri,
            }
            for key, value in metrics.items():
                if isinstance(value, (str, int, float, bool)) and value is not None:
                    metadata["eval_" + key] = str(value)
            if len(metadata) > 50 or any(len(k) > 128 or len(v) > 256 for k, v in metadata.items()):
                raise ValueError("Metadata exceeds conservative registry limits")
            if write:
                sm.update_model_package(ModelPackageArn=package["ModelPackageArn"], CustomerMetadataProperties=metadata)
                updated = sm.describe_model_package(ModelPackageName=package["ModelPackageArn"])
                assert updated["ModelApprovalStatus"] == package["ModelApprovalStatus"]
                assert all(updated["CustomerMetadataProperties"].get(k) == v for k, v in metadata.items())
            snapshots[str(package["ModelPackageVersion"])] = {"package": package["ModelPackageArn"], "commit_sha": sha, "training_job_arn": jobs[0], "dataset": snapshot, "metadata": metadata}
            print(f"{'Updated' if write else 'Verified'} v{package['ModelPackageVersion']} provenance: {sha}", flush=True)
    write_json(DOCS / "lab4-training-data.json", {"captured_at": datetime.now(timezone.utc), "packages": snapshots, "unrecoverable": unrecoverable})
    if write:
        package = sm.describe_model_package(ModelPackageName=f"arn:aws:sagemaker:us-east-1:{ACCOUNT}:model-package/{GROUP}/7")
        assert package["CustomerMetadataProperties"]["commit_sha"] == source_revision("a85d7a13")
        package.pop("ResponseMetadata", None)
        write_json(DOCS / "lab4-model-package.json", package)
    print("Unrecoverable historical lineage:", json.dumps(unrecoverable), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["mlflow", "lineage"])
    parser.add_argument("--write-lineage", action="store_true")
    args = parser.parse_args()
    DOCS.mkdir(exist_ok=True)
    session = boto3.Session(region_name="us-east-1")
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise ValueError("Wrong AWS account")
    if args.command == "mlflow":
        export_mlflow()
    else:
        capture_lineage(session, args.write_lineage)


if __name__ == "__main__":
    main()
