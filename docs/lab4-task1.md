# Lab 4 Task 1: test suite and evidence

The production Glue job remains in Spark. `data/feature_engineering.py` is a
pandas reference whose 11 features are compared with actual Glue Parquet output
in the data tests. Both implementations include the lower window boundary
(`purchase_date >= T - N days`), and exclude purchases after April 1, 2026.
The reference supports roster customers with no observation history using
recency 999, tenure zero, and zero for the remaining features. Existing Glue
output includes customers with observation history only.

The suite covers raw/processed/feature schemas, transaction/customer grain,
leakage, distributions, 48-hour ingestion freshness, exact feature parity,
normal/zero/single-purchase cases, model probabilities, quality gates,
champion regression, and fairness. Missing inputs fail. Only the initial
absence of any Approved champion permits a bootstrap regression skip.

## Local verification (PowerShell, repository root)

Use the isolated environment rather than the global Python installation with
conflicting SageMaker packages and the incompatible BYU pytest plugin:

```powershell
.\.venv-churn\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv-churn\Scripts\python.exe scripts/lab4_task1.py stage-data --bucket northstar-dev-data-278634873542
```

Read the printed `paths.json` manifest and set its three dataset paths:

```powershell
$paths = Get-Content -LiteralPath '<printed manifest path>' -Raw | ConvertFrom-Json
$env:NORTHSTAR_RAW = $paths.NORTHSTAR_RAW
$env:NORTHSTAR_PROCESSED = $paths.NORTHSTAR_PROCESSED
$env:NORTHSTAR_FEATURES = $paths.NORTHSTAR_FEATURES
$env:OMP_NUM_THREADS = '2'
Remove-Item Env:ALLOW_MISSING_DATA,Env:ALLOW_MISSING_FEATURES_MODULE -ErrorAction SilentlyContinue
.\.venv-churn\Scripts\python.exe models/churn/train_sagemaker.py --train-channel $env:NORTHSTAR_FEATURES --model-dir artifacts/lab4/model --output-data-dir artifacts/lab4/output
.\.venv-churn\Scripts\python.exe -m pytest -p no:byu_pytest_utils tests/ -v -rw --model-path artifacts/lab4/output/model.ubj --eval-metrics-path artifacts/lab4/output/evaluation_metrics.json
```

The explicit output model path places the model beside its metadata and avoids
Windows/Git Bash `/tmp` path differences. Re-run Glue successfully before staging
if data is stale. Never change `event_time` locally to bypass freshness.

## CI and champion sequence

1. Apply the reviewed IAM changes and obtain a successful fresh feature-job run.
   The DataEngineer policy allows only the exact `features_$folder$` marker in
   addition to its existing feature prefix; MLEngineer can tag jobs, create
   model packages, describe/create the named model package group, and pass
   itself to SageMaker. The SDK registration step checks the group even when
   the group already exists.
2. Verify the existing CI stack, versioned artifacts bucket, and Available
   GitHub connection. Push the tested implementation to `main` to trigger CI.
   Data and feature tests run before training. After training, `pytest tests/`
   runs every suite against the newly registered candidate and emitted metrics.
3. The first green run may skip regression if there is no Approved champion.
   Have the user approve that green run's package, then trigger the next run.
   The final regression test must pass without skipping.
   Use a new commit for the final run: the starter stores evaluation metrics
   under a commit-based S3 key, so rerunning the same commit would overwrite
   the champion's metrics before the regression check reads them.
4. The champion is the newest **Approved** package in `northstar-churn-models`.
   Its registered ModelQuality Statistics S3 object supplies `auc_roc`.
   Candidate AUC must be at least champion AUC minus 0.02. The warning records
   the champion version and both AUCs. AWS lookup failures are failures.
5. Fairness compares the highest and lowest tier recall at the global top-10%
   contact cutoff. A gap over 0.10 warns without blocking; incomplete slice
   evidence blocks. No absolute validation-AUC threshold is added.

## Capture before teardown

```powershell
.\.venv-churn\Scripts\python.exe scripts/lab4_task1.py capture --build-id '<final green CodeBuild build ID>'
```

The capture helper only reads AWS. It validates the successful build, passing
counts, non-skipped champion comparison, warnings, training, registration, and
Approved champion before writing the exact required evidence files:

- `docs/lab4-build-green.log`: complete final green build log, at least two
  passes in each required category and at least five feature-test passes.
- `docs/lab4-model-registry.json`: all versions, including the Approved champion.

Commit these actual outputs before the final submission tag. Task 2's deliberate
failure/revert demonstration, other lab tasks, teardown, and tagging are separate.

## Verification record — October 29, 2026

- IAM repair applied: two policies updated in place; no resources created or
  destroyed. The exact S3 folder-marker permission resolved the observed Glue
  `AccessDenied` error.
- Glue feature refresh `jr_deff87f08a39b9b562d71e1e817ba8d2ef07b1edf533bac4ef0e50143a9c3eb7`
  succeeded. All 11 reference features matched its actual output.
- Local full suite: **115 passed, 1 bootstrap skip**, 32 subtests passed. The
  only warning was the measured fairness gap, 0.3444.
- Newly trained local candidate: AUC 0.7838, precision 0.7333, recall 0.3333,
  baseline AUC 0.7223, lift interval [0.0428, 0.0799], 3,000 validation rows.
- CI stack `northstar-cicd` is `CREATE_COMPLETE`; its separate artifacts bucket
  is versioned and the GitHub connection is Available.
- Commit `e2eebd14b786cbb90d6d7a87d7a571fc87994b35` was pushed to `main`.
  No automatic pipeline execution appeared despite `DetectChanges=true`.
  Pipeline execution `8b2110fc-efb0-4096-8927-3c637785c0c0` was explicitly started
  for Task 1 validation. Automatic push-trigger verification remains a Task 2
  follow-up; a manually started run is not evidence of an automatic trigger.
- That first CI run passed data/feature tests and the SageMaker training step,
  then exposed missing model-package-group permissions in MLEngineer during
  registration. The group permissions are scoped to `northstar-churn-models`.
- After applying that fix, commit `6ac061473601e7712b77bc58dee5c177c64feb05`
  produced successful CodeBuild run
  `northstar-ci:798de060-ef58-4e8b-ad40-71d02116fd9b`. It trained under the
  SageMaker XGBoost 1.7 container, registered package **v2**, and passed **115
  tests**, with only the initial no-Approved-champion regression skip.
- Package v2: AUC 0.7819, precision 0.7267, recall 0.3303, baseline AUC 0.7208,
  lift interval [0.0413, 0.0813]. The fairness warning reported a tier recall
  gap of 0.3058. Its metrics are under `artifacts/evaluations/6ac06147/` in the
  data bucket; a distinct final commit preserves this champion evidence.
- On October 30, the live regression test verified v2 as the newest Approved
  champion and passed: `champion v2 auc=0.7819; candidate auc=0.7838` for the
  local candidate. The next CI run uses this new documentation commit, keeping
  its candidate metrics separate from the champion's S3 key.

## Final CI evidence — October 30, 2026

CodeBuild `northstar-ci:191260e3-e60b-42d2-96e8-9099bbd4b28f` succeeded on
commit `243149cde7a5ce1b9135d565e922f83782b140ed`: **116 passed, no skips**, plus
32 passing subtests. The live regression warning records
`champion v2 auc=0.7819; candidate auc=0.7819`. The new candidate is package v3;
v2 remains Approved and v3 is PendingManualApproval. The fairness warning is
visible with a tier recall gap of 0.3058 and does not block the build.

The capture helper verified the passing counts, actual champion comparison,
training/registration success, and Approved champion before saving
`docs/lab4-build-green.log` and `docs/lab4-model-registry.json`. This run was
explicitly started after the push trigger again failed to start an execution;
the automatic-trigger follow-up was left for Task 2. That follow-up was resolved
with the installed GitHub App connection and a verified WebhookV2 execution;
see `docs/lab4-task2.md` for the subsequent demonstration and evidence.
