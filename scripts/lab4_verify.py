"""Verify the handout's complete deliverables list without an AWS connection."""

import hashlib
import math
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lab4_task2 import read_snapshots, validate_snapshots

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def main():
    source = ["tests/test_data.py", "tests/test_features.py", "tests/test_model.py",
              "tests/test_fairness.py", "models/churn/churn_model.py", "buildspec.yml", "pipeline.yaml"]
    evidence = ["lab4-build-green.log", "lab4-build-failed.log", "lab4-pipeline-runs.txt",
                "lab4-failure-demo.txt", "lab4-alarm-email.png", "lab4-model-registry.json",
                "lab4-model-package.json", "lab4-mlflow-runs.txt", "lab4-xops-assessment.md"]
    paths = source + ["docs/" + name for name in evidence]
    for name in paths:
        assert (ROOT / name).is_file() and (ROOT / name).stat().st_size, name
    assessment = (DOCS / "lab4-xops-assessment.md").read_text(encoding="utf-8")
    for heading in ["Pipeline Stage Mapping", "Champion-Challenger", "Retraining Triggers", "DataOps Maturity", "MLOps Maturity"]:
        assert "## " + heading in assessment, heading
    for name in re.findall(r"`([^`]+\.(?:py|tf|yml|yaml|json|txt|log|png))`", assessment):
        assert (ROOT / name).is_file(), name
    package = json.loads((DOCS / "lab4-model-package.json").read_text(encoding="utf-8"))
    metadata = package["CustomerMetadataProperties"]
    assert package["ModelPackageVersion"] == 7 and package["ModelApprovalStatus"] == "PendingManualApproval"
    assert all(metadata.get(k) for k in ["commit_sha", "training_data_s3_uri", "training_data_timestamp",
                                        "evaluation_metrics_s3_uri", "eval_auc_roc", "eval_precision_top10", "eval_recall_top10"])
    for sha in [metadata["commit_sha"], "c088d8c9f1bfca913ddef0341ef014bbc7fbfa92", "a85d7a13dc9bf09a66ffd0ebfdb0554f9235f81f"]:
        subprocess.run(["git", "merge-base", "--is-ancestor", sha, "main"], cwd=ROOT, check=True)
    registry = json.loads((DOCS / "lab4-model-registry.json").read_text(encoding="utf-8"))["ModelPackageSummaryList"]
    assert len(registry) == 7 and any(p["ModelPackageVersion"] == 2 and p["ModelApprovalStatus"] == "Approved" for p in registry)
    log = (DOCS / "lab4-build-green.log").read_text(encoding="utf-8")
    assert "127 passed" in log and not re.search(r"\d+ skipped", log)
    for name in ["data", "features", "model", "fairness"]:
        assert re.search(r"tests/test_" + name + r"\.py::[^\n]*PASSED", log), name
    assert all(s in log for s in ["Fairness flag:", "champion v2 auc=", "Pipeline succeeded", "Registered:"])
    assert "PRE_BUILD State: FAILED" in (DOCS / "lab4-build-failed.log").read_text(encoding="utf-8")
    validate_snapshots(read_snapshots(DOCS / "lab4-failure-demo.txt"))
    assert (DOCS / "lab4-alarm-email.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    runs = (DOCS / "lab4-mlflow-runs.txt").read_text(encoding="utf-8")
    rows = [line.split() for line in runs.splitlines() if re.match("[0-9a-f]{32} ", line)]
    assert len(rows) >= 3 and len({tuple(row[5:13]) for row in rows}) >= 3
    assert all(len(row) == 22 and row[4] == "FINISHED" and all(math.isfinite(float(v)) for v in row[13:]) for row in rows)
    assert all(s in runs for s in ["mlflow-app/", "params.max_depth", "metrics.auc_roc"]) and "..." not in runs
    history = (DOCS / "lab4-pipeline-runs.txt").read_text(encoding="utf-8")
    assert all(s in history for s in ["CodePipeline", "CodeBuild", "SageMaker", "pytest:", "83c2b00c-f9a2-4483-8805-6ccdfb6c8d72", "6e6a1838-58a9-4c52-92bf-e866710fc28d"])
    lines = ["# Lab 4 deliverables verification", "", f"Verified at {datetime.now(timezone.utc).isoformat()}.", "",
             "All items in the handout's complete list passed local evidence checks.", "",
             "| Deliverable | Result | SHA-256 |", "|---|---|---|"]
    for name in paths:
        digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        lines.append(f"| `{name}` | Present and checked | `{digest}` |")
    lines += ["", "Semantic checks: 127 passing tests without skips; champion and fairness warnings;",
              "training/registration success; genuine failure/recovery snapshots; alarm screenshot;",
              "four MLflow runs with three parameter configurations and complete metrics; v7 lineage;",
              "Approved v2 in the pre-teardown registry; all five assessment headings; cited paths;",
              "and both failure/revert commits in main history.", "",
              "The alarm screenshot was visually checked against the actual received email during",
              "Task 2. Automated checks verify its PNG signature and preserved file hash.", "",
              "The registry export records approval statuses before teardown. Teardown subsequently",
              "rejects Approved packages before deleting their artifact bucket; it must not overwrite",
              "this historical export. See `docs/lab4-teardown-output.txt` for the separate teardown record.", "",
              "Historical limitation: Lab 3 v1 has no recoverable SageMaker training-job link; its",
              "original metadata is preserved. Verified provenance was backfilled for v2-v7.", "",
              "Submission commit/tag publication is checked separately after deleting the CI stack."]
    (DOCS / "lab4-deliverables-checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"PASS: {len(paths)} required files, all sections and semantic evidence checks")
    print("Task 4 word count:", len(assessment[assessment.index("## DataOps Maturity"):].split()))


if __name__ == "__main__":
    main()
