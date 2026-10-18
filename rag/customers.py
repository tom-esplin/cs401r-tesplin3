"""Read customer features without inferring missing purchase history or scores."""
import math
import re

from .config import ROOT, aws_client

CATEGORIES = {"Apparel", "Footwear", "Home", "Electronics", "Beauty", "Grocery", "Toys", "Outdoor"}
FIELDS = {
    "churn_probability", "loyalty_tier", "total_lifetime_value", "top_categories",
    "category_diversity_score", "days_since_last_purchase", "avg_order_value",
    "online_to_store_ratio", "tier_verified", "country",
}


def validate_customer(profile):
    # Never send unrelated or sensitive fields from caller-supplied profiles to the model.
    customer = {k: v for k, v in profile.items() if k in FIELDS}
    if customer.get("loyalty_tier") not in {"Bronze", "Silver", "Gold", "Platinum"}:
        raise ValueError("Customer must have a valid loyalty_tier")
    categories = customer.get("top_categories")
    if not isinstance(categories, list) or not categories or any(c not in CATEGORIES for c in categories):
        raise ValueError("Supply top_categories from purchase history; Feature Store does not contain them")
    probability = customer.get("churn_probability")
    if isinstance(probability, bool) or not isinstance(probability, (float, int)) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Supply churn_probability from the trained model, in [0, 1]")
    customer.setdefault("tier_verified", False)
    if not isinstance(customer["tier_verified"], bool):
        raise ValueError("tier_verified must be a boolean")
    return customer


def load_customer(customer_id, config, *, top_categories=None, churn_probability=None, client=None,
                  purchase_path=None, model_dir=None):
    if not re.fullmatch(r"CUST-\d+", customer_id):
        raise ValueError("Invalid customer ID")
    client = client or aws_client("sagemaker-featurestore-runtime", config.region)
    model_dir = model_dir or ROOT / "model"
    model_features = []
    if churn_probability is None:
        import json
        model_features = json.loads((model_dir / "model_metadata.json").read_text(encoding="utf-8"))["feature_columns"]
    names = sorted(set(model_features + ["loyalty_tier", "total_lifetime_value", "category_diversity_score",
                                       "days_since_last_purchase", "avg_order_value", "online_to_store_ratio"]))
    result = client.get_record(
        FeatureGroupName=config.feature_group,
        RecordIdentifierValueAsString=customer_id,
        FeatureNames=names,
    )
    record = result.get("Record")
    if not record:
        raise ValueError(f"No online Feature Store record for {customer_id}")
    profile = {r["FeatureName"]: r["ValueAsString"] if r["FeatureName"] == "loyalty_tier"
               else float(r["ValueAsString"]) for r in record}
    provenance = {"features": "online-feature-store", "feature_group": config.feature_group}
    if churn_probability is None:
        import numpy as np
        import xgboost as xgb
        from .index import digest
        model_path = model_dir / "model.json"
        model = xgb.Booster()
        model.load_model(model_path)
        # Match training preprocessing: sentinel -1 for missing feature values.
        values = [[profile.get(name, -1) for name in model_features]]
        values = np.nan_to_num(np.asarray(values, dtype="float32"), nan=-1)
        churn_probability = float(model.predict(xgb.DMatrix(values, feature_names=model_features))[0])
        provenance["churn_model_sha256"] = digest(model_path.read_bytes())
    else:
        provenance["churn_probability"] = "caller-supplied trained-model prediction"
    if top_categories is None:
        import pandas as pd
        purchase_path = purchase_path or ROOT / "snapshots/lab2/processed/customers"
        purchases = pd.read_parquet(purchase_path, columns=["customer_id", "product_category", "order_value"],
                                    filters=[("customer_id", "=", customer_id)])
        if purchases.empty:
            raise ValueError("No saved purchase history; supply --categories from an authoritative source")
        spend = purchases.groupby("product_category")["order_value"].sum().sort_values(ascending=False)
        top_categories = [category for category in spend.index if category in CATEGORIES][:3]
        provenance["categories"] = str(purchase_path)
        provenance["category_method"] = "top three categories by summed order_value in saved history"
        manifest_path = purchase_path.parent.parent / "manifest.json"
        if manifest_path.exists():
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            provenance["purchase_snapshot_saved_at"] = manifest.get("saved_at")
    else:
        provenance["categories"] = "caller-supplied purchase preferences"
    # Feature-store churn_risk_score is a heuristic, not the trained model prediction.
    profile.update(top_categories=top_categories, churn_probability=churn_probability, tier_verified=False)
    return {**validate_customer(profile), "customer_id": customer_id, "_provenance": provenance}
