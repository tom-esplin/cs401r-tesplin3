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
   model packages, and pass itself to SageMaker.
2. Verify the existing CI stack, versioned artifacts bucket, and Available
   GitHub connection. Push the tested implementation to `main` to trigger CI.
   Data and feature tests run before training. After training, `pytest tests/`
   runs every suite against the newly registered candidate and emitted metrics.
3. The first green run may skip regression if there is no Approved champion.
   Have the user approve that green run's package, then trigger the next run.
   The final regression test must pass without skipping.
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
