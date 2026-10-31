# Lab 4 deliverables verification

Verified at 2026-10-31T02:51:04.169107+00:00.

All items in the handout's complete list passed local evidence checks.

| Deliverable | Result | SHA-256 |
|---|---|---|
| `tests/test_data.py` | Present and checked | `2e77c5131f3d3607a0f8f00a32bc4dfe642c77b949934a170d90c8ef63615161` |
| `tests/test_features.py` | Present and checked | `7b9f4b92dfe256ed3e0f2685d69436e8412e861cc86c1c1aab5e67c5f74e0d73` |
| `tests/test_model.py` | Present and checked | `3d45240cfc0e70ec332f8a43cb5c91659e97c5bb4cb0e50463a07c9b85886f3a` |
| `tests/test_fairness.py` | Present and checked | `22f592d2435b0c8743a74027374c922d37ad94b88ad153e6a34f876bb69c9cf6` |
| `models/churn/churn_model.py` | Present and checked | `b52ed11535295d01ea4e603fbfad431eb4ddaa8d106a04056d3a8004947ec771` |
| `buildspec.yml` | Present and checked | `d42299137b1470b54da843cd969d12d0e27d285ed07ffd15e5da336a852ff4f9` |
| `pipeline.yaml` | Present and checked | `690b342f2d1760653caf1321cf42919e301fa4c848c76db06fefa01b020e5c88` |
| `docs/lab4-build-green.log` | Present and checked | `6ed7a22acdcd840d84ec58cabd99edae78d88f536f6746de3c3cc5984188b100` |
| `docs/lab4-build-failed.log` | Present and checked | `1b8cfe35eae7411a063b889d47235eab5c493d2612c7be6450c73bbf0bb37f99` |
| `docs/lab4-pipeline-runs.txt` | Present and checked | `7164e6089e4d6a00be1b005d5f39fc44ef4853ecc49f9ba8e649a025d652ff35` |
| `docs/lab4-failure-demo.txt` | Present and checked | `be8634d890ad4af2e2b28a365eca57b30f338a77530507b6dea9c1bd9f838987` |
| `docs/lab4-alarm-email.png` | Present and checked | `4e885a1d2c66f2a84370f2dd83af0865dfc2c3b917d6d4bfc0f54afc4b018457` |
| `docs/lab4-model-registry.json` | Present and checked | `a98d610b0baa29c0821334cbd0fa9900bbe4e31ed3219eeec90eeefcb6c59181` |
| `docs/lab4-model-package.json` | Present and checked | `6995b6b04dd4f5f842bf050bd2d24d30dd656f22b6626ff95817ad2c2fbd6a47` |
| `docs/lab4-mlflow-runs.txt` | Present and checked | `7177daf90f73946b68206fd50679ff6589864319b8d5ad24fd380566c986226a` |
| `docs/lab4-xops-assessment.md` | Present and checked | `cdf3d4d39455537961956ae253654ac666750f1be19383767281b838fe032b51` |

Semantic checks: 127 passing tests without skips; champion and fairness warnings;
training/registration success; genuine failure/recovery snapshots; alarm screenshot;
four MLflow runs with three parameter configurations and complete metrics; v7 lineage;
Approved v2 in the pre-teardown registry; all five assessment headings; cited paths;
and both failure/revert commits in main history.

The alarm screenshot was visually checked against the actual received email during
Task 2. Automated checks verify its PNG signature and preserved file hash.

The registry export records approval statuses before teardown. Teardown subsequently
rejects Approved packages before deleting their artifact bucket; it must not overwrite
this historical export. See `docs/lab4-teardown-output.txt` for the separate teardown record.

Historical limitation: Lab 3 v1 has no recoverable SageMaker training-job link; its
original metadata is preserved. Verified provenance was backfilled for v2-v7.

Submission commit/tag publication is checked separately after deleting the CI stack.
