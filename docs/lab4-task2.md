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
- The SNS email subscription was initially PendingConfirmation. The recipient
  confirmed it before the controlled demonstration; the address is omitted
  from the captured evidence.

## GitHub App connection repair

The user installed the GitHub App and supplied the Available replacement
connection `northstar-github-installed`:
`arn:aws:codeconnections:us-east-1:278634873542:connection/f9929443-5743-4bb3-9c68-45828f87a6af`.
The stack's `GitHubConnectionArn` parameter and its scoped CodePipeline role
permission are updated together through CloudFormation. The old connection
is retained while the replacement is verified. A fresh push after the update
is the automatic-trigger probe; previous manually started runs are not used
as proof of push-trigger automation.

The replacement connection was applied in place, updating only
`NorthStarPipeline` and `CodePipelineRole`. Commit
`bfa84857b5c64251c82f174bf90ec95b041b9f91` automatically started execution
`3b77036c-483e-461b-a594-1a8055c18870` with trigger type **WebhookV2** and
CodeBuild `northstar-ci:785d0932-6c69-48f1-aedb-2fd86e576ae1`. Exactly one
execution matched the pushed SHA. The SNS email subscription was also
confirmed before the failure demonstration.

## Controlled demonstration

An initial rehearsal was interrupted by an additional manual **Release change**
execution of the preceding good commit. That run legitimately added a registry
version during the first evidence window. The evidence validator rejected the
version mismatch, the rehearsal files were archived locally, and the passing
tests were restored before starting a fresh baseline. The final evidence uses
only the repeated, uninterrupted sequence below.

- **BEFORE:** automatic baseline commit
  `e3fdc1c1d4cd0a06701946be4bcacf5828140f35` passed all 127 tests. The latest
  package was v6, the alarm was OK, the email subscription was confirmed, and
  no builds or training jobs were active when the snapshot was taken.
- **AFTER FAILED RUN:** commit `c088d8c9f1bfca913ddef0341ef014bbc7fbfa92`
  automatically started execution `f6d2ebc7-fb81-4044-bc4d-e66445b00005` and
  build `northstar-ci:6e6a1838-58a9-4c52-92bf-e866710fc28d`. The deliberate
  assertion failed in PRE_BUILD; BUILD never started. The registry remained
  unchanged at v6, the alarm transitioned to ALARM, and SNS accepted the
  notification at 20:24:19 UTC on October 30. The complete failed log and
  AFTER FAILED RUN snapshot were captured after the alarm action.
- The assertion was reverted in commit
  `a85d7a13dc9bf09a66ffd0ebfdb0554f9235f81f`, retaining the failure and revert
  commits in main history. Its recovery execution is
  `ab837cba-fd17-4b8b-bffa-f31380637776`.
- **AFTER REVERT:** automatic recovery build
  `northstar-ci:83c2b00c-f9a2-4483-8805-6ccdfb6c8d72` passed **127 tests with
  no skips**, registered exactly one additional version (**v7**,
  PendingManualApproval), and the alarm naturally returned to OK. Champion v2
  remained Approved; the log records `champion v2 auc=0.7819; candidate auc=0.7819`.

All three recorded executions were WebhookV2-triggered. The validated snapshots
show the registry sequence **6 → 6 → 7** and alarm sequence **OK → ALARM → OK**.
The final ALARM action at 20:24:19 UTC matches the actual Gmail screenshot's
2:24 PM receipt and message timestamp. The screenshot was visually checked and
kept as provided; its subject and received time are visible.

Required evidence is captured in `docs/lab4-failure-demo.txt`,
`docs/lab4-build-failed.log`, `docs/lab4-build-green.log`,
`docs/lab4-pipeline-runs.txt`, `docs/lab4-model-registry.json`, and
`docs/lab4-alarm-email.png`. `validate-evidence` passed for the snapshot sequence,
deliberate assertion log, and PNG; visual verification confirmed email content
and timing. The final green log contains the live champion warning and the
nonblocking fairness warning.
