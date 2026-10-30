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
