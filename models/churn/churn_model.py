"""Your Lab 3 churn model, packaged for the Lab 4 pipeline.

YOU WRITE THIS FILE. The pipeline's training job runs train_sagemaker.py
(beside this file; do not edit it), which imports this module and calls
train(). Everything the job needs from you goes through the three names below.

Contract (train_sagemaker.py checks it in the first seconds of the job):

    FEATURE_COLUMNS   list[str]   model input columns, in order
    LABEL             str         "churn_label"
    train(df, seed=42) -> (xgboost.Booster, dict)

`df` is the full labeled feature table: every column of your Lab 2 output,
including `loyalty_tier` for slice evaluation. It is already loaded. Do not
query Athena or the Feature Store from here; the training container stages
the data for you and has no business making service calls for its input.

The metrics dict must include the four numbers the CI gate in
tests/test_model.py reads. Your Lab 3 evaluate_model() already returns them:

    precision_top10, recall_top10      gated at 0.50 / 0.25
    lift_ci_low, lift_ci_high          bootstrap 95% CI on AUC lift over the
                                       recency-only baseline; lift_ci_low > 0

Include anything else you reported in Lab 3 (auc_roc, baseline_auc,
positive_rate_val, slice results). It is all written to evaluation_metrics.json
and attached to the registered model.

What runs in the container: the SageMaker XGBoost 1.7-1 image ships pandas,
numpy, scikit-learn, xgboost and boto3. It does NOT ship mlflow or sagemaker,
so do not import them at the top of this file. MLflow tracking stays in your
Lab 3 script.

Only this directory (models/churn/) is uploaded to the training job, so the
code must live here. `import churn_training_skeleton` will fail inside the
container even though it works on your laptop. Copy the functions you need.

Test it locally before pushing:

    python models/churn/train_sagemaker.py \
        --train-channel <dir containing your features CSV or Parquet> \
        --model-dir /tmp/model --output-data-dir /tmp/out
"""

# Keeps Lab 3 annotations like `-> tuple[np.ndarray, np.ndarray]` from being
# evaluated, whatever Python the training container runs.
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

# Must match the columns your Lab 3 model was trained on, in the same order.
FEATURE_COLUMNS = [
    "days_since_last_purchase",
    "customer_tenure_days",
    "purchase_frequency_30d",
    "purchase_frequency_90d",
    "purchase_frequency_180d",
    "avg_order_value",
    "total_spend_90d",
    "total_lifetime_value",
    "avg_basket_size_6m",
    "category_diversity_score",
    "online_to_store_ratio",
]

LABEL = "churn_label"
SLICE_COLUMN = "loyalty_tier"
BASELINE_FEATURE = "days_since_last_purchase"
BOOTSTRAP_N = 2000
EVAL_THRESHOLDS = {"precision_top10": 0.50, "recall_top10": 0.25}


def train(df: pd.DataFrame, seed: int = 42) -> tuple[xgb.Booster, dict]:
    """Train and evaluate the Lab 3 model; raise if promotion gates fail.

    Preserve Lab 3's -1 sentinel for missing features, depth-3 weighted
    classifier, and 30% stratified validation split. Tiers follow the same
    split but never enter the feature matrix. The caller owns data loading,
    model serialization, and registration.
    """
    required = FEATURE_COLUMNS + [LABEL, SLICE_COLUMN]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Training data missing required columns: {missing}")

    # Filter the entire table so tiers stay aligned when labels are absent.
    labeled = df.dropna(subset=[LABEL])
    labels = pd.to_numeric(labeled[LABEL], errors="raise")
    if not labels.isin([0, 1]).all() or labels.nunique() != 2:
        raise ValueError("Training labels must contain both binary classes, 0 and 1.")
    X = labeled[FEATURE_COLUMNS].fillna(-1).to_numpy(dtype=float)
    y = labels.to_numpy(dtype=int)
    tiers = labeled[SLICE_COLUMN].to_numpy(dtype=object)
    X_train, X_val, y_train, y_val, _, tier_val = train_test_split(
        X, y, tiers, test_size=0.30, random_state=seed, stratify=y,
    )
    if len(np.unique(y_train)) != 2 or len(np.unique(y_val)) != 2:
        raise ValueError("Training and validation splits must each contain both classes.")

    model = train_model(X_train, y_train, X_val, y_val, seed=seed)
    baseline_proba = train_recency_baseline(X_train, y_train, X_val, seed=seed)
    metrics = evaluate_model(model, X_val, y_val, baseline_proba, seed=seed)
    metrics.update(evaluate_slices(model, X_val, y_val, tier_val))
    return model, metrics


def train_model(X_train, y_train, X_val, y_val, seed: int = 42) -> xgb.Booster:
    """Use the selected Lab 3 hyperparameters and AUC early stopping."""
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
    params = {
        "objective": "binary:logistic",
        # XGBoost early-stops on the last metric; keep AUC last.
        "eval_metric": ["logloss", "auc"],
        "max_depth": 3,
        "eta": 0.1,
        "min_child_weight": 5,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": float((y_train == 0).sum() / (y_train == 1).sum()),
        "seed": seed,
        "verbosity": 1,
    }
    # As in Lab 3, return the complete booster, including the stopping rounds.
    # Evaluation and serving both use that same booster's default predictions.
    return xgb.train(
        params, dtrain, num_boost_round=200,
        evals=[(dtrain, "train"), (dval, "validation")],
        early_stopping_rounds=20, verbose_eval=25,
    )


def train_recency_baseline(X_train, y_train, X_val, seed: int = 42) -> np.ndarray:
    """Fit the Lab 3 baseline on the same training rows, using recency alone."""
    i = FEATURE_COLUMNS.index(BASELINE_FEATURE)
    dtrain = xgb.DMatrix(
        X_train[:, [i]], label=y_train, feature_names=[BASELINE_FEATURE],
    )
    dval = xgb.DMatrix(X_val[:, [i]], feature_names=[BASELINE_FEATURE])
    params = {
        "objective": "binary:logistic", "eval_metric": "auc",
        "max_depth": 4, "eta": 0.1, "subsample": 0.9,
        "colsample_bytree": 0.9,
        "scale_pos_weight": float((y_train == 0).sum() / (y_train == 1).sum()),
        "seed": seed,
    }
    return xgb.train(params, dtrain, num_boost_round=200).predict(dval)


def bootstrap_lift_ci(
    y_true, proba, baseline_proba, n: int = BOOTSTRAP_N,
    seed: int = 42, alpha: float = 0.05,
) -> tuple[float, float]:
    """Paired percentile CI for AUC lift, skipping single-class resamples."""
    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true)
    proba = np.asarray(proba)
    baseline_proba = np.asarray(baseline_proba)
    diffs = []
    for _ in range(n):
        indices = rng.choice(len(y_true), size=len(y_true), replace=True)
        ys = y_true[indices]
        if len(np.unique(ys)) < 2:
            continue
        diffs.append(
            roc_auc_score(ys, proba[indices])
            - roc_auc_score(ys, baseline_proba[indices])
        )
    if not diffs or len(diffs) < n // 2:
        raise ValueError(
            "Too few usable bootstrap replicates to form a confidence interval. "
            "The validation set is too small or too imbalanced."
        )
    return (
        float(np.quantile(diffs, alpha / 2)),
        float(np.quantile(diffs, 1 - alpha / 2)),
    )


def evaluate_model(model, X_val, y_val, baseline_proba, seed: int = 42) -> dict:
    """Report Lab 3 metrics and reject models that fail the pipeline gates."""
    proba = model.predict(xgb.DMatrix(X_val, feature_names=FEATURE_COLUMNS))
    # Preserve Lab 3's percentile cutoff, including ties at the cutoff.
    selected = proba >= np.percentile(proba, 90)
    auc_roc = float(roc_auc_score(y_val, proba))
    baseline_auc = float(roc_auc_score(y_val, baseline_proba))
    lo, hi = bootstrap_lift_ci(y_val, proba, baseline_proba, seed=seed)
    metrics = {
        "auc_roc": round(auc_roc, 4),
        "precision_top10": round(float(y_val[selected].mean()), 4),
        "recall_top10": round(float(y_val[selected].sum() / y_val.sum()), 4),
        "auc_vs_baseline": round(auc_roc - baseline_auc, 4),
        "baseline_auc": round(baseline_auc, 4),
        "baseline_auc_roc": round(baseline_auc, 4),
        "lift_ci_low": round(lo, 4),
        "lift_ci_high": round(hi, 4),
        "positive_rate_val": round(float(y_val.mean()), 4),
        "n_val_samples": int(len(y_val)),
        "eval_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    failures = [
        f"{name}={metrics[name]:.4f} < {threshold}"
        for name, threshold in EVAL_THRESHOLDS.items()
        if metrics[name] < threshold
    ]
    # Check the emitted value too: CI reads the rounded metrics from JSON.
    if lo <= 0 or metrics["lift_ci_low"] <= 0:
        failures.append(
            f"auc_lift 95% CI [{lo:.4f}, {hi:.4f}] does not establish "
            "positive lift over the recency-only baseline"
        )
    if failures:
        raise ValueError(
            f"Model failed evaluation thresholds: {'; '.join(failures)}. "
            "Do not promote to Model Registry."
        )
    return metrics


def evaluate_slices(model, X_val, y_val, slice_column) -> dict:
    """Report tier AUC and recall using the aggregate top-10% contact cutoff.

    Flag recall more than 10 percentage points below aggregate. Single-class
    slices have no AUC; slices with no positives have no recall. Use None so
    their metrics remain valid JSON without implying a measured score.
    """
    proba = model.predict(xgb.DMatrix(X_val, feature_names=FEATURE_COLUMNS))
    selected = proba >= np.percentile(proba, 90)
    aggregate_recall = float(y_val[selected].sum() / y_val.sum())
    tiers = pd.Series(slice_column, dtype=object).fillna("Unknown").to_numpy()
    metrics = {}
    for tier in pd.unique(tiers):
        mask = tiers == tier
        labels = y_val[mask]
        n_positive = int(labels.sum())
        recall = float(y_val[mask & selected].sum() / n_positive) if n_positive else None
        auc = float(roc_auc_score(labels, proba[mask])) if len(np.unique(labels)) == 2 else None
        prefix = f"slice_{str(tier).lower()}"
        metrics.update({
            f"{prefix}_auc": round(auc, 4) if auc is not None else None,
            f"{prefix}_recall_top10": round(recall, 4) if recall is not None else None,
            f"{prefix}_n": int(mask.sum()),
            f"{prefix}_n_positive": n_positive,
            f"{prefix}_recall_flag": bool(
                recall is not None and recall < aggregate_recall - 0.10
            ),
        })
    return metrics
