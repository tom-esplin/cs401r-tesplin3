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
