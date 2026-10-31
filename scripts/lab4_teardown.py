"""Scoped Lab 4 cleanup. Export and verify evidence before invoking ci.

Run backup, ci, then Terraform's reviewed Studio destroy. Run studio-leftovers,
then the reviewed remaining Terraform destroy, then finish and verify.
The serverless MLflow App and Terraform backend are retained deliberately.
"""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "278634873542"
REGION = "us-east-1"
DATA = f"northstar-dev-data-{ACCOUNT}"
ARTIFACTS = f"northstar-dev-cicd-artifacts-{ACCOUNT}"
VPC = "vpc-06930cd4262ceb49e"
DOMAIN = "d-tvykbyjdrlti"
APP = f"arn:aws:sagemaker:{REGION}:{ACCOUNT}:mlflow-app/app-2DBMQ67QFI76"
LOG = ROOT / "docs/lab4-teardown-output.txt"


def record(message):
    line = f"{datetime.now(timezone.utc).isoformat()} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def missing(exc):
    return exc.response["Error"]["Code"] in {"ResourceNotFound", "ResourceNotFoundException", "FileSystemNotFound", "InvalidVpcID.NotFound", "NoSuchBucket"}


def backup(session):
    s3 = session.client("s3")
    objects = [o for p in s3.get_paginator("list_objects_v2").paginate(Bucket=DATA) for o in p.get("Contents", [])]
    size = sum(o["Size"] for o in objects)
    if size > 512 * 1024 * 1024:
        raise ValueError("Backup exceeds 512 MiB; review its size before continuing")
    folder = ROOT / "artifacts/lab4/pre-teardown-backup" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (folder / "objects").mkdir(parents=True)
    for obj in objects:
        if obj["Key"].endswith("/"):
            continue
        # S3 keys may contain colons or exceed Windows path limits. Keep their
        # exact spelling in the manifest and use portable local filenames.
        target = (folder / "objects" / hashlib.sha256(obj["Key"].encode("utf-8")).hexdigest()).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise ValueError("Unsafe S3 object path")
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(DATA, obj["Key"], str(target))
        if target.stat().st_size != obj["Size"]:
            raise ValueError("Backup size mismatch")
        obj["backup_path"] = str(target.relative_to(folder))
        obj["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (folder / "backup-manifest.json").write_text(json.dumps({"bucket": DATA, "objects": objects}, indent=2, default=str), encoding="utf-8")
    record(f"BACKUP {len(objects)} current S3 objects, {size} bytes: {folder.relative_to(ROOT)}")
    record("MLflow run parameters/metrics exported separately; original Lab 3 repository files preserved.")


def empty_bucket(s3, bucket):
    while True:
        page = s3.list_object_versions(Bucket=bucket, MaxKeys=1000)
        items = [{"Key": x["Key"], "VersionId": x["VersionId"]} for k in ["Versions", "DeleteMarkers"] for x in page.get(k, [])]
        if not items:
            break
        response = s3.delete_objects(Bucket=bucket, Delete={"Objects": items, "Quiet": True})
        if response.get("Errors"):
            raise RuntimeError(response["Errors"])
        record(f"Removed {len(items)} versions/delete markers from {bucket}")
    assert not s3.list_objects_v2(Bucket=bucket, MaxKeys=1).get("Contents")


def delete_ci(session):
    subprocess.run([str(ROOT / ".venv-churn/Scripts/python.exe"), "scripts/lab4_verify.py"], cwd=ROOT, check=True)
    if not list((ROOT / "artifacts/lab4/pre-teardown-backup").glob("*/backup-manifest.json")):
        raise ValueError("Complete the local backup first")
    cf = session.client("cloudformation")
    cf.delete_stack(StackName="northstar-cicd")
    record("Requested CloudFormation deletion: northstar-cicd")
    while True:
        try:
            status = cf.describe_stacks(StackName="northstar-cicd")["Stacks"][0]["StackStatus"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ValidationError" and "does not exist" in str(exc):
                break
            raise
        if status == "DELETE_FAILED":
            raise RuntimeError("CI stack DELETE_FAILED; inspect stack events")
        record("CI stack: " + status)
        time.sleep(15)
    record("CI stack deleted; subsequent documentation pushes cannot start this pipeline.")
    s3 = session.client("s3")
    empty_bucket(s3, ARTIFACTS)
    s3.delete_bucket(Bucket=ARTIFACTS)
    record("Deleted versioned CI artifacts bucket: " + ARTIFACTS)
    session.client("logs").delete_log_group(logGroupName="/aws/codebuild/northstar-ci")
    record("Deleted CodeBuild log group after capture")
    sm = session.client("sagemaker")
    for page in sm.get_paginator("list_model_packages").paginate(ModelPackageGroupName="northstar-churn-models"):
        for package in page["ModelPackageSummaryList"]:
            if package["ModelApprovalStatus"] == "Approved":
                sm.update_model_package(ModelPackageArn=package["ModelPackageArn"], ModelApprovalStatus="Rejected",
                                        ApprovalDescription="Lab 4 teardown: reject before deleting backing training/artifact bucket. Pre-teardown Approved state saved in repository evidence.")
                record(f"Rejected previously Approved package v{package['ModelPackageVersion']} before data/artifact deletion")


def studio_leftovers(session):
    sm = session.client("sagemaker")
    try:
        sm.describe_domain(DomainId=DOMAIN)
    except ClientError as exc:
        if not missing(exc) and not (exc.response["Error"]["Code"] == "ValidationException" and "does not exist" in str(exc)):
            raise
    else:
        raise RuntimeError("Destroy the Terraform Studio module before cleaning its orphan dependencies")
    inventory = json.loads((ROOT / "artifacts/lab4/teardown-inventory.json").read_text(encoding="utf-8"))
    efs = session.client("efs")
    fsid = inventory["domain"]["HomeEfsFileSystemId"]
    try:
        targets = efs.describe_mount_targets(FileSystemId=fsid)["MountTargets"]
    except ClientError as exc:
        if not missing(exc):
            raise
    else:
        for target in targets:
            if target["VpcId"] != VPC:
                raise ValueError("Unexpected EFS VPC")
            efs.delete_mount_target(MountTargetId=target["MountTargetId"])
        while efs.describe_mount_targets(FileSystemId=fsid)["MountTargets"]:
            record("Waiting for Studio EFS mount targets to disappear")
            time.sleep(15)
        efs.delete_file_system(FileSystemId=fsid)
        record("Deleted orphan Studio EFS " + fsid)
    ec2 = session.client("ec2")
    for eni in ec2.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [VPC]}, {"Name": "status", "Values": ["available"]}])["NetworkInterfaces"]:
        if "Glue" in eni.get("Description", "") and not eni.get("RequesterManaged"):
            ec2.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
            record("Deleted orphan Glue ENI " + eni["NetworkInterfaceId"])
    groups = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [VPC]}])["SecurityGroups"]
    orphan_groups = [g for g in groups if DOMAIN in g["GroupName"] and "nfs" in g["GroupName"]]
    for group in orphan_groups:
        if group["IpPermissions"]:
            ec2.revoke_security_group_ingress(GroupId=group["GroupId"], IpPermissions=group["IpPermissions"])
        if group["IpPermissionsEgress"]:
            ec2.revoke_security_group_egress(GroupId=group["GroupId"], IpPermissions=group["IpPermissionsEgress"])
    for group in orphan_groups:
        ec2.delete_security_group(GroupId=group["GroupId"])
        record("Deleted Studio NFS security group " + group["GroupId"])


def finish(session):
    glue = session.client("glue")
    try:
        tables = [t for p in glue.get_paginator("get_tables").paginate(DatabaseName="sagemaker_featurestore") for t in p["TableList"]]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityNotFoundException":
            raise
    else:
        if all(t.get("StorageDescriptor", {}).get("Location", "").startswith("s3://" + DATA + "/") for t in tables):
            glue.delete_database(Name="sagemaker_featurestore")
            record("Deleted NorthStar-only Feature Store Glue catalog database")
        else:
            record("Retained shared Feature Store catalog database; contains another data location")
    sm = session.client("sagemaker")
    entities = []
    for operation, key, arn_key in [("list_contexts", "ContextSummaries", "ContextArn"), ("list_artifacts", "ArtifactSummaries", "ArtifactArn")]:
        for page in sm.get_paginator(operation).paginate():
            for item in page[key]:
                if "northstar" in json.dumps(item, default=str).lower():
                    entities.append((operation, item[arn_key]))
    for _, arn in entities:
        for direction in ["SourceArn", "DestinationArn"]:
            for page in sm.get_paginator("list_associations").paginate(**{direction: arn}):
                for association in page["AssociationSummaries"]:
                    sm.delete_association(SourceArn=association["SourceArn"], DestinationArn=association["DestinationArn"])
        if ":context/" in arn:
            sm.delete_context(ContextName=arn.split("/")[-1])
        else:
            sm.delete_artifact(ArtifactArn=arn)
        record("Deleted scoped lineage entity " + arn)
    logs = session.client("logs")
    for name in ["/aws-glue/crawlers", "/aws-glue/jobs/error", "/aws-glue/jobs/logs-v2", "/aws-glue/jobs/output"]:
        try:
            logs.delete_log_group(logGroupName=name)
        except ClientError as exc:
            if not missing(exc):
                raise
        else:
            record("Deleted captured lab Glue log group " + name)
    record("Retained MLflow App, completed SageMaker pipeline/registry history, CodeConnections, and Terraform state backend")


def verify(session):
    sm = session.client("sagemaker")
    ec2 = session.client("ec2")
    for bucket in [DATA, ARTIFACTS]:
        try:
            session.client("s3").get_bucket_location(Bucket=bucket)
        except ClientError as exc:
            if not missing(exc):
                raise
        else:
            raise AssertionError("Bucket remains: " + bucket)
        record("VERIFIED deleted bucket " + bucket)
    assert not ec2.describe_vpcs(Filters=[{"Name": "vpc-id", "Values": [VPC]}])["Vpcs"]
    assert not ec2.describe_nat_gateways(Filter=[{"Name": "vpc-id", "Values": [VPC]}, {"Name": "state", "Values": ["available", "pending", "deleting"]}])["NatGateways"]
    assert not [d for d in sm.list_domains()["Domains"] if d["DomainId"] == DOMAIN]
    assert not [f for f in sm.list_feature_groups()["FeatureGroupSummaries"] if f["FeatureGroupName"].startswith("northstar")]
    assert not [e for e in sm.list_endpoints()["Endpoints"] if e["EndpointName"].startswith("northstar")]
    assert not sm.list_mlflow_tracking_servers()["TrackingServerSummaries"]
    assert sm.describe_mlflow_app(Arn=APP)["Status"] == "Created"
    fsid = json.loads((ROOT / "artifacts/lab4/teardown-inventory.json").read_text(encoding="utf-8"))["domain"]["HomeEfsFileSystemId"]
    assert not [f for f in session.client("efs").describe_file_systems()["FileSystems"] if f["FileSystemId"] == fsid]
    assert not ec2.describe_addresses(Filters=[{"Name": "tag:Project", "Values": ["northstar"]}])["Addresses"]
    assert not [j for j in session.client("glue").list_jobs()["JobNames"] if j.startswith("northstar")]
    for operation, key in [("list_training_jobs", "TrainingJobSummaries"), ("list_processing_jobs", "ProcessingJobSummaries"), ("list_transform_jobs", "TransformJobSummaries")]:
        for status in ["InProgress", "Stopping"]:
            assert not getattr(sm, operation)(StatusEquals=status)[key]
    resources = subprocess.check_output(["terraform", "-chdir=infrastructure/environments/dev", "state", "list"], cwd=ROOT, text=True)
    assert not resources.strip(), resources
    record("VERIFIED Terraform state empty; NorthStar VPC/NAT/EIP/domain/EFS/feature group/Glue jobs/endpoints gone; no running/stopping ML jobs or MLflow tracking servers")
    record("VERIFIED MLflow App retained; Terraform backend intentionally retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "ci", "studio-leftovers", "finish", "verify"])
    args = parser.parse_args()
    session = boto3.Session(region_name=REGION)
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise ValueError("Wrong AWS account")
    record(f"Phase {args.command}; account {ACCOUNT}, region {REGION}")
    try:
        {"backup": backup, "ci": delete_ci, "studio-leftovers": studio_leftovers, "finish": finish, "verify": verify}[args.command](session)
    except Exception as exc:
        record(f"FAILED {args.command}: {exc}")
        raise


if __name__ == "__main__":
    main()
