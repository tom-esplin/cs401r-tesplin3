# ── modules/feature_store ────────────────────────────────────────────────────
# Task 3: the customer-features Feature Group. 16 definitions: 2 keys
# (customer_id, event_time), 13 features, 1 label (churn_label).
#
# event_time MUST be Fractional (Unix epoch seconds), not String (ISO 8601).
# PutRecord accepts either and returns success either way, but a type
# mismatch against what the feature-engineer job actually sends means the
# record silently never lands in either store. See glue-scripts/feature_engineer.py,
# which writes event_time as float(int(time.time())) to match this.

resource "aws_sagemaker_feature_group" "customer_features" {
  feature_group_name             = "${var.project}-${var.environment}-customer-features"
  record_identifier_feature_name = "customer_id"
  event_time_feature_name        = "event_time"
  role_arn                       = var.data_engineer_role_arn

  online_store_config {
    enable_online_store = true
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.bucket_name}/${var.offline_store_prefix}"
    }
  }

  feature_definition {
    feature_name = "customer_id"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "event_time"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "days_since_last_purchase"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "customer_tenure_days"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "purchase_frequency_30d"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "purchase_frequency_90d"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "purchase_frequency_180d"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "avg_order_value"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "total_spend_90d"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "total_lifetime_value"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "avg_basket_size_6m"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "category_diversity_score"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "online_to_store_ratio"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "loyalty_tier"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "churn_risk_score"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "churn_label"
    feature_type = "Integral"
  }
}
