"""Validation shared by dataset integration tests and isolated failure checks."""

import numpy as np
import pandas as pd

from .feature_engineering import FEATURE_COLUMNS


def validate_freshness(event_time, now=None):
    values = pd.to_numeric(event_time, errors="raise").to_numpy(dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("event_time must contain finite epoch seconds")
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    age = current.timestamp() - values.max()
    if not 0 <= age < 48 * 3600:
        raise ValueError(f"Latest feature event_time must be less than 48 hours old and not future-dated; age={age / 3600:.2f} hours")


def validate_feature_parity(expected, actual):
    """Compare the reference with actual Glue output, including customer grain."""
    for name, frame in (("reference", expected), ("Glue", actual)):
        if frame["customer_id"].duplicated().any():
            raise ValueError(f"{name} contains duplicate customer IDs")
    if set(expected["customer_id"]) != set(actual["customer_id"]):
        raise ValueError("Reference and Glue customer sets differ")
    expected = expected.set_index("customer_id").sort_index()
    actual = actual.set_index("customer_id").sort_index()
    exact = [c for c in FEATURE_COLUMNS if c.startswith("purchase_frequency") or c.endswith("_days") or c == "days_since_last_purchase"]
    for column in FEATURE_COLUMNS:
        tolerance = 0 if column in exact else 0.0001 + 1e-12
        left = expected[column].to_numpy(dtype=float)
        right = actual[column].to_numpy(dtype=float)
        if not np.isfinite(left).all() or not np.isfinite(right).all() or not np.allclose(left, right, rtol=0, atol=tolerance):
            raise ValueError(f"Glue output differs from reference for {column}")
