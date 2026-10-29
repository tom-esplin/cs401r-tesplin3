"""Local checks for the pipeline trainer, without AWS or saved Lab 3 artifacts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xgboost as xgb

from models.churn import churn_model as churn
from models.churn import train_sagemaker as entrypoint


def features():
    rng = np.random.default_rng(42)
    n = 1200
    df = pd.DataFrame(rng.uniform(0, 100, (n, len(churn.FEATURE_COLUMNS))),
                      columns=churn.FEATURE_COLUMNS)
    df[churn.LABEL] = rng.binomial(1, 0.2, n)
    # Strong non-recency signal makes the expected quality-gate verdict clear.
    df["purchase_frequency_30d"] = (1 - df[churn.LABEL]) * 100
    df[churn.SLICE_COLUMN] = rng.choice(["Bronze", "Silver", "Gold", "Platinum"], n)
    df.loc[::19, "avg_order_value"] = np.nan
    return df


def check_training_channel(features, tmp_path):
    channel = tmp_path / "training"
    channel.mkdir()
    features.to_csv(channel / "features.csv", index=False)
    original = features.copy(deep=True)
    model, metrics = churn.train(features)
    pd.testing.assert_frame_equal(features, original)
    assert isinstance(model, xgb.Booster)
    assert model.feature_names == churn.FEATURE_COLUMNS
    assert metrics["n_val_samples"] == 360
    assert metrics["precision_top10"] >= 0.5
    assert metrics["recall_top10"] >= 0.25
    assert metrics["lift_ci_low"] > 0
    assert sum(metrics[f"slice_{tier}_n"] for tier in
               ["bronze", "silver", "gold", "platinum"]) == 360
    json.dumps(metrics, allow_nan=False)
    entrypoint._check_outputs(model, metrics)
    loaded = entrypoint.read_channel(str(channel))
    assert len(loaded) == len(features)
    path = tmp_path / "model.ubj"
    model.save_model(path)
    reloaded = xgb.Booster()
    reloaded.load_model(path)
    matrix = xgb.DMatrix(features[churn.FEATURE_COLUMNS].fillna(-1),
                         feature_names=churn.FEATURE_COLUMNS)
    np.testing.assert_array_equal(model.predict(matrix), reloaded.predict(matrix))


def check_label_filtering(features):
    features.index = np.arange(len(features)) * 7
    features[churn.SLICE_COLUMN] = features.index.astype(str)
    features["customer_tenure_days"] = features.index
    features.loc[features.index[5], churn.LABEL] = np.nan
    with patch.object(churn, "train_model") as fit, \
            patch.object(churn, "train_recency_baseline") as baseline, \
            patch.object(churn, "evaluate_model", return_value={}), \
            patch.object(churn, "evaluate_slices", return_value={}) as slices:
        churn.train(features, seed=19)
    validation = fit.call_args.args[2]
    tiers = slices.call_args.args[3]
    np.testing.assert_array_equal(validation[:, 1].astype(int).astype(str), tiers)
    assert len(fit.call_args.args[0]) + len(validation) == len(features) - 1
    assert fit.call_args.kwargs["seed"] == 19
    assert baseline.call_args.kwargs["seed"] == 19


class FixedModel:
    def __init__(self, scores):
        self.scores = scores

    def predict(self, matrix):
        return self.scores


def check_slices():
    scores = np.arange(100, dtype=float) / 100
    labels = np.zeros(100, dtype=int)
    labels[[0, 1, 2, 3, 90, 91, 92, 93, 94, 95]] = 1
    tiers = np.array(["Bronze"] * 50 + ["Silver"] * 40 + ["Gold"] * 10,
                     dtype=object)
    tiers[99] = None
    metrics = churn.evaluate_slices(FixedModel(scores), np.zeros((100, 11)), labels, tiers)
    assert metrics["slice_bronze_recall_top10"] == 0
    assert metrics["slice_bronze_recall_flag"] is True
    assert metrics["slice_gold_recall_top10"] == 1
    assert metrics["slice_silver_auc"] is None
    assert metrics["slice_silver_recall_top10"] is None
    assert metrics["slice_unknown_n"] == 1
    json.dumps(metrics, allow_nan=False)


class TestChurnTraining(unittest.TestCase):
    def test_training_channel_produces_serializable_model_and_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            check_training_channel(features(), Path(directory))

    def test_label_filtering_keeps_tiers_aligned_and_passes_seed(self):
        check_label_filtering(features())

    def test_invalid_or_single_class_labels_are_rejected(self):
        for label in [0, 2, 0.5]:
            with self.subTest(label=label):
                df = features()
                df[churn.LABEL] = label
                with self.assertRaisesRegex(ValueError, "both binary classes"):
                    churn.train(df)

    def test_missing_columns_are_reported(self):
        with self.assertRaisesRegex(ValueError, "loyalty_tier"):
            churn.train(features().drop(columns=[churn.SLICE_COLUMN]))

    def test_bootstrap_preserves_pairing_and_is_reproducible(self):
        labels = np.tile([0, 1], 20)
        scores = np.linspace(0, 1, len(labels))
        self.assertEqual(churn.bootstrap_lift_ci(labels, scores, scores, n=100), (0.0, 0.0))
        first = churn.bootstrap_lift_ci(labels, labels, scores, n=100, seed=17)
        self.assertEqual(first, churn.bootstrap_lift_ci(labels, labels, scores, n=100, seed=17))
        self.assertGreater(first[0], 0)
        with self.assertRaisesRegex(ValueError, "Too few usable bootstrap"):
            churn.bootstrap_lift_ci(np.zeros(20), np.zeros(20), np.zeros(20), n=100)

    def test_failed_promotion_gates_raise(self):
        for ci, inverted, failure in [
            ((0.0, 0.1), False, "positive lift"),
            ((0.000001, 0.1), False, "positive lift"),
            ((0.1, 0.2), True, "precision_top10.*recall_top10"),
        ]:
            with self.subTest(ci=ci, inverted=inverted):
                labels = np.r_[np.zeros(80), np.ones(20)]
                scores = np.arange(100, dtype=float) / 100
                if inverted:
                    scores = scores[::-1]
                with patch.object(churn, "bootstrap_lift_ci", return_value=ci):
                    with self.assertRaisesRegex(ValueError, failure):
                        churn.evaluate_model(
                            FixedModel(scores), np.zeros((100, 11)), labels, scores,
                        )

    def test_slices_use_global_cutoff_and_handle_single_class_tiers(self):
        check_slices()


if __name__ == "__main__":
    unittest.main()
