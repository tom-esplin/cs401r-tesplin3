# Lab 4 XOps assessment

## Pipeline Stage Mapping

NorthStar retains AWS CodePipeline and CodeBuild because they integrate with the
existing AWS IAM roles, S3 data, SageMaker training and Model Registry, CloudWatch
logs and alarms, and SNS notifications. CI runs in `us-east-1`; local commands
prepare changes and inspect evidence, while AWS executes the tests and training.

| Logical phase | CodePipeline stage | Implementation |
|---|---|---|
| Source | Source | The GitHub App connection fetches the pushed `main` commit as `SourceArtifact`; an explicit V2 push trigger starts the execution. |
| Test | Build | CodeBuild runs data and feature tests in `pre_build`, before any training starts. |
| Build | Build | CodeBuild packages the checked-out training code and upserts/starts the SageMaker Pipeline; training runs on one managed Spot `ml.m5.large` instance using XGBoost 1.7. |
| Evaluate | Build | Training evaluates precision/recall and paired-bootstrap lift before registration. CodeBuild then runs the full suite against the trained candidate, including the Approved champion comparison and nonblocking fairness warning. |
| Register | Build | SageMaker registers a passing training candidate as PendingManualApproval. If a later CodeBuild gate fails, `post_build` marks that candidate Rejected. |

These are five logical phases within three CodePipeline stages, rather than five
separate compute projects. Candidate-dependent checks must run after training.
The supplied SageMaker Pipeline registers before those CodeBuild checks; the
rejection step prevents a later failed build leaving an approvable candidate.
Pre-training test failures never reach training or registration.

The third stage, ManualApproval, asks a human to review quality and fairness.
Changing a Model Registry package to Approved and approving the CodePipeline
action are separate human decisions. This Lab 4 pipeline does not deploy an
endpoint. Champion v2 remains Approved; new candidates remain pending review.

The failure alarm uses AWS/CodeBuild's built-in FailedBuilds metric so it can
observe failures even when a build does not reach `post_build`. SNS acceptance
alone is not proof of delivery: Task 2 evidence also requires a confirmed email
subscription and the actual received alarm email screenshot.

## Champion-Challenger

A challenger is eligible to replace the newest Approved champion only when its
validation AUC is **at least champion AUC + 0.01**, precision at the top-10%
contact budget is at least 0.50, recall is at least 0.25, the paired-bootstrap
95% AUC-lift interval over the recency baseline has a lower bound above zero,
and every required CI test passes. Human approval remains required. Compare
the same feature contract, label definition, and held-out population; a changed
evaluation population requires reevaluating both models on the same data.

The existing CI non-regression rule, candidate AUC >= champion AUC - 0.02,
determines whether a candidate passes CI. It does not authorize replacement.
The additional +0.01 rule is the documented promotion policy, not a deployed
automatic approval gate. Fairness recall gaps above 0.10 remain warnings for
human review. The final recovery candidate v7 has AUC 0.7819, matching champion
v2 at 0.7819; it does not reach the 0.7919 replacement threshold and stays
PendingManualApproval. See `docs/lab4-model-package.json`,
`docs/lab4-model-registry.json`, and `docs/lab4-build-green.log`.

## Retraining Triggers

These are automatable designs, **not deployed resources**. No production
endpoint, production-quality metric stream, or retraining schedule is claimed.
Both triggers request a candidate; they never approve or deploy it.

| Trigger | Exact condition | AWS services and action |
|---|---|---|
| Scheduled | Every Monday at 09:00 in `America/Denver`: `cron(0 9 ? * MON *)`. | EventBridge Scheduler starts a Step Functions workflow. It runs the Glue feature job, waits for success, and starts `northstar-pipeline`. Freshness and data/feature gates run before training. Failed refreshes stop the workflow. |
| Performance | Daily at 10:00 Denver time, evaluate the latest seven days of **mature** labeled predictions. Require at least 1,000 examples and both classes. Alarm when AUC is strictly below champion validation AUC minus 0.02 for two consecutive valid daily evaluations; with v2 this threshold is 0.7619. | EventBridge Scheduler invokes a SageMaker Processing evaluation job. It publishes one daily `ProductionAUC` metric to `NorthStar/ModelQuality`, dimensioned by champion package ARN. A CloudWatch alarm uses Average, period 86,400 seconds, two evaluation periods and two breaching datapoints. An EventBridge alarm-state-change rule starts the same Step Functions retraining workflow on entry into ALARM. |

For the churn label, an observation needs its full 90-day outcome window before
it is mature. Missing or undersized cohorts publish no AUC; missing alarm data
is nonbreaching and raises a separate data-availability notification. On champion
changes, update the alarm dimension and threshold. Both triggers must share a
concurrency guard: when a refresh, build, or training execution is active,
record the request rather than starting another training run.
Evaluation outputs must retain prediction IDs, label-window dates, sample
counts, and champion ARN so future alarms can be audited.

### Tracking and provenance evidence

`docs/lab4-mlflow-runs.txt` exports the existing `northstar-churn` experiment from
the Lab 3 MLflow App with untruncated parameters and metrics. Its four finished
runs cover three distinct hyperparameter combinations; no additional training
or synthetic runs were needed. `scripts/lab4_task3.py` reproduces this export.

The final green recovery build registered v7 from commit
`a85d7a13dc9bf09a66ffd0ebfdb0554f9235f81f`. Its registry metadata contains the
training channel URI, data timestamp, full commit, training-job ARN, metrics URI,
and numeric evaluation metrics. `docs/lab4-training-data.json` records the S3
object version IDs recovered as of each job's start. The data timestamp means
the latest S3 modification of those Parquet versions; event time is recorded
separately. Verified lineage was backfilled for v2-v7 without changing approval
statuses. The locally trained Lab 3 v1 lacks a SageMaker training-job link; its
original metadata is preserved and this historical gap is explicitly recorded.

## DataOps Maturity

Current level: **2/4**. Processing is repeatable and tested, with partial
integration; continuous operational feedback is incomplete.

Evidence: `infrastructure/modules/storage/main.tf` defines versioned S3 storage,
and `infrastructure/modules/glue/main.tf` manages the processing jobs. The Spark
feature implementation in `glue-scripts/feature_engineer.py` has a pandas
reference in `data/feature_engineering.py`. `tests/test_features.py` checks
window boundaries, excluded holdout activity, and feature values;
`tests/test_data.py` checks the real processed and feature outputs, freshness,
and parity. The final AWS build in `docs/lab4-build-green.log` reports 127 passed
tests without skips, including data and feature checks before training. The
controlled assertion in `docs/lab4-build-failed.log` failed PRE_BUILD;
`docs/lab4-failure-demo.txt` shows no new registry version during that failure.
These measured results demonstrate an enforced dependency between input
quality and training. `docs/lab4-training-data.json` adds auditable object
versions for the recovered training inputs.

Gap to Level 3: feature refresh is not yet automatically coordinated with
source arrival, quality checks, and downstream training. A fresh ingestion
timestamp alone cannot prove that business events are recent or complete.
The current synthetic dataset also uses a fixed observation cutoff. No
production distribution-drift feedback or automatic quarantine is demonstrated.

Top priority investment: implement the proposed Step Functions refresh workflow
with Glue Data Quality rules for event completeness and business-date freshness,
quarantine failed partitions, and publish quality outcomes to CloudWatch before
allowing training. This would extend the tested code path into an observable,
repeatable data-delivery process.

## MLOps Maturity

Current level: **2/4**. Automated model CI is demonstrated; a continuously
operated production model lifecycle is not.

Evidence: `pipeline.yaml` connects GitHub pushes to CodeBuild, while
`buildspec.yml` enforces data tests, managed SageMaker training, evaluation, and
registry handling. `evaluation/model_gates.py` compares candidates with the
Approved champion; `tests/test_fairness.py` exposes slice recall differences.
The green build records champion v2, the fairness warning, successful training,
registration, and all 127 passing tests. The failure snapshots and received
`docs/lab4-alarm-email.png` establish that the controlled failure reached SNS
and a human inbox. `docs/lab4-mlflow-runs.txt` provides deliberate experiment
comparisons, and `docs/lab4-model-package.json` links the final recovery model
to code, versioned data, and metrics. Candidates require human approval.

Gap to Level 3: no deployed endpoint, joined production labels, operational
quality time series, automated promotion enforcement, or rollback has been
demonstrated. The two retraining triggers above are designs rather than
running automation. Historical v1 lineage is incomplete, and metadata capture
currently requires an explicit command.

Top priority investment: implement the daily mature-label SageMaker Processing
evaluation and CloudWatch performance alarm described above, retaining cohort
and champion provenance. Connect it to candidate retraining and retain human
promotion review. This supplies measured production feedback before attempting
automatic deployment or more advanced optimization.
