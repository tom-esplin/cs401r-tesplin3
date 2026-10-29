"""Pandas reference for glue-scripts/feature_engineer.py.

The production job remains in Spark. Integration tests compare this reference
against its actual Parquet output. All windows include T-N and T, matching
the existing Spark expressions. No feature includes holdout transactions.
"""

from datetime import timedelta

import pandas as pd

FEATURE_CUTOFF = pd.Timestamp("2026-04-01")
FEATURE_COLUMNS = [
    "days_since_last_purchase", "customer_tenure_days",
    "purchase_frequency_30d", "purchase_frequency_90d", "purchase_frequency_180d",
    "avg_order_value", "total_spend_90d", "total_lifetime_value",
    "avg_basket_size_6m", "category_diversity_score", "online_to_store_ratio",
]


def _history(transactions, snapshot_date):
    cutoff = pd.Timestamp(snapshot_date).normalize()
    history = transactions.copy()
    history["purchase_date"] = pd.to_datetime(
        history["purchase_date"], errors="raise", utc=True,
    ).dt.tz_localize(None).dt.normalize()
    return history.loc[history["purchase_date"] <= cutoff], cutoff


def compute_recency_features(transactions, snapshot_date=FEATURE_CUTOFF, customer_ids=None):
    """Recency and tenure in days; an optional roster includes inactive customers."""
    history, cutoff = _history(transactions, snapshot_date)
    dates = history.groupby("customer_id")["purchase_date"].agg(["min", "max"])
    result = pd.DataFrame({
        "days_since_last_purchase": (cutoff - dates["max"]).dt.days,
        "customer_tenure_days": (cutoff - dates["min"]).dt.days,
    }).reset_index()
    if customer_ids is not None:
        result = customer_ids[["customer_id"]].drop_duplicates().merge(
            result, on="customer_id", how="left",
        )
    return result.fillna({"days_since_last_purchase": 999, "customer_tenure_days": 0})


def compute_frequency_features(transactions, snapshot_date=FEATURE_CUTOFF):
    history, cutoff = _history(transactions, snapshot_date)
    result = history[["customer_id"]].drop_duplicates().set_index("customer_id")
    for days in (30, 90, 180):
        window = history.loc[history["purchase_date"] >= cutoff - timedelta(days=days)]
        result[f"purchase_frequency_{days}d"] = window.groupby("customer_id").size()
    return result.fillna(0).reset_index()


def compute_monetary_features(transactions, snapshot_date=FEATURE_CUTOFF):
    history, cutoff = _history(transactions, snapshot_date)
    result = history.groupby("customer_id")["order_value"].agg(
        avg_order_value="mean", total_lifetime_value="sum",
    )
    recent = history.loc[history["purchase_date"] >= cutoff - timedelta(days=90)]
    basket = history.loc[history["purchase_date"] >= cutoff - timedelta(days=180)]
    result["total_spend_90d"] = recent.groupby("customer_id")["order_value"].sum()
    # Mean items per order, never mean dollars per order.
    result["avg_basket_size_6m"] = basket.groupby("customer_id")["num_items"].mean()
    return result.fillna(0).reset_index()


def compute_behavioral_features(transactions, snapshot_date=FEATURE_CUTOFF):
    history, _ = _history(transactions, snapshot_date)
    result = history[["customer_id"]].drop_duplicates().set_index("customer_id")
    known = history.loc[history["product_category"] != "unknown"]
    result["category_diversity_score"] = known.groupby("customer_id")["product_category"].nunique() / 8
    result["online_to_store_ratio"] = (
        history.assign(_online=history["channel"].eq("online"))
        .groupby("customer_id")["_online"].mean()
    )
    return result.fillna(0).reset_index()


def build_churn_feature_set(customers, transactions, snapshot_date=FEATURE_CUTOFF):
    """Return the roster with all 11 features, preserving its labels and tiers.

    Customers without observation history have recency 999 and all other
    numeric features zero. Production parity is checked on customers with
    observation history, the population emitted by the existing Spark job.
    """
    result = customers.copy()
    for compute in (compute_recency_features, compute_frequency_features,
                    compute_monetary_features, compute_behavioral_features):
        result = result.merge(compute(transactions, snapshot_date), on="customer_id", how="left")
    result["days_since_last_purchase"] = result["days_since_last_purchase"].fillna(999)
    result[FEATURE_COLUMNS] = result[FEATURE_COLUMNS].fillna(0)
    return result
