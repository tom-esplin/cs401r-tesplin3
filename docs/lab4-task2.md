# Lab 4 Task 2 execution and evidence

The native V2 trigger filters pushes to the configured `main` branch, using
source action `GitHubSource` and the existing authorized connection. Default
change detection is disabled because the explicit trigger replaces it. No
pull-request, tag, or file-path filters are configured. Validate automatic
execution using its exact SHA and Webhook/WebhookV2 trigger metadata; a manually
started execution does not prove the source trigger.

`scripts/lab4_task2.py` only reads AWS and writes local evidence. It never starts
the pipeline, approves a model, changes the alarm, or subscribes recipients.
Email addresses and message bodies are omitted from snapshot output.

Before the demonstration, confirm the SNS email subscription, refresh Glue if
features are approaching 48 hours old, complete the automatic smoke run, wait
for the alarm to read OK, and ensure no training or CodeBuild jobs are active.
Old executions waiting for human approval are not active training/build jobs.

From the repository root, use the exact build/execution IDs for each snapshot:

```powershell
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py snapshot --label BEFORE --build-id '<baseline build ID>' --execution-id '<baseline pipeline execution ID>'
```

Add a new feature test with `assert False, "Deliberate Lab4 Task2 failure"`, commit
it and push. Wait for PRE_BUILD FAILED, no BUILD phase, no additional registry
version, the real ALARM state, and a successful SNS action. Save the received
email screenshot as `docs/lab4-alarm-email.png`, showing the ALARM subject and
received time. The address may be blurred; the screenshot must be real.

```powershell
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py snapshot --label 'AFTER FAILED RUN' --build-id '<failed build ID>' --execution-id '<failed pipeline execution ID>'
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py save-log --build-id '<failed build ID>' --output docs/lab4-build-failed.log
```

Revert the failure commit with `git revert` and push. Preserve both commits in
main history. Wait for the recovery build to pass all tests, register exactly
one additional PendingManualApproval version, and the alarm to return to OK.

```powershell
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py snapshot --label 'AFTER REVERT' --build-id '<recovery build ID>' --execution-id '<recovery pipeline execution ID>'
.\.venv-churn\Scripts\python.exe scripts/lab4_task1.py capture --build-id '<recovery build ID>'
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py capture-runs
.\.venv-churn\Scripts\python.exe scripts/lab4_task2.py validate-evidence
```

The helper checks all snapshot labels, webhook-triggered runs, confirmed
subscriptions, phase boundaries, registry version sets, correlated alarm
delivery, distinct commit SHAs, and pending recovery-candidate approval. It
rejects duplicate snapshot labels rather than overwriting proof. Screenshot
subject, received time, and correspondence to the failed run still require
visual verification. Wait for real metric ingestion rather than forcing the
alarm state. A 20-minute alarm wait is the diagnostic timeout.

Capture all evidence before teardown. Final evidence includes the three
snapshots, complete failed and recovery logs, pipeline execution history,
registry snapshot, and actual alarm email screenshot. A documentation push also
triggers CI; preserve the recovery run's exact identifiers when exporting logs.

## Implementation verification — October 30, 2026

- CloudFormation update completed in place: only `NorthStarPipeline` and
  `BuildFailureAlarm` changed; no resources were replaced. AWS reports the
  explicit `main` push filter on `GitHubSource`.
- Commit `28b74dcfb7000e539eb8e871a2027d6665c6bfe9` contains the implementation.
  All **127 local tests passed**, including the 11 new evidence checks and
  the live Approved-v2 regression test. The original staged `.gitignore`
  changes were excluded from the commit.
- The five-minute automatic-trigger probe produced no execution. The user
  found AWS Connector for GitHub under authorized apps, not installed apps;
  the repository's App installation must be completed before retesting with
  a fresh push. The missing event was not replaced with a manual start.
- The SNS email subscription was created, but the last AWS check still showed
  PendingConfirmation. Complete confirmation before taking the BEFORE
  snapshot. No deliberate failure has been pushed yet.

## GitHub App connection repair

The user installed the GitHub App and supplied the Available replacement
connection `northstar-github-installed`:
`arn:aws:codeconnections:us-east-1:278634873542:connection/f9929443-5743-4bb3-9c68-45828f87a6af`.
The stack's `GitHubConnectionArn` parameter and its scoped CodePipeline role
permission are updated together through CloudFormation. The old connection
is retained while the replacement is verified. A fresh push after the update
is the automatic-trigger probe; previous manually started runs are not used
as proof of push-trigger automation.
