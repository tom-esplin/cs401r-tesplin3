## Data Contract: processed/customers

### Producer
Team / process: Glue ETL job `northstar-dev-transform` (`infrastructure/modules/glue`, logic in `glue-scripts/transform.py`). Reads the crawler-registered `northstar_dev.customers` catalog table (sourced from `raw/customers/`) and writes Parquet to `processed/customers/`.

### Consumers
- Feature engineering job `northstar-dev-feature-engineer` (reads `processed/customers/`, writes `features/customers/` and the `northstar-dev-customer-features` Feature Group)
- (Future) Direct model training in Lab 3

### Grain
One row per transaction. A `customer_id` appears on many rows — this is transaction-level data, not customer-level. The feature-engineering job is what collapses it to one row per customer; `processed/customers/` itself must never be deduplicated on `customer_id`.

### Schema
| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `transaction_id` | string | No | `TXN-{12 alphanumeric}`. Natural key — unique per row after dedup. |
| `customer_id` | string | No | `CUST-{8 digits}`. Join key for every downstream feature; rows with a null source value are dropped by the producer, never imputed. |
| `purchase_date` | date | No | Parsed from ISO 8601 or `MM/DD/YYYY` source strings; rows the producer cannot parse are not expected to survive (see Quality Guarantees). |
| `order_value` | double | No | USD, gross, per order. Source nulls (~4% of raw rows) are imputed with the column median. |
| `num_items` | int | No | Line items in the order. No source nulls observed, but the column participates in the same median-imputation pass as the other numeric columns. |
| `payment_method` | string | No | One of `credit_card`, `debit_card`, `gift_card`, `cash`. Source nulls imputed as `"unknown"`. |
| `channel` | string | No | One of `store`, `online`. Source nulls imputed as `"unknown"`. |
| `store_id` | string | No | `STORE-{3 digits}` or `ONLINE`. Source nulls imputed as `"unknown"`. |
| `product_category` | string | No | One of 8 categories. Source nulls imputed as `"unknown"` — consumers computing category-diversity-style metrics must exclude `"unknown"` or it will be miscounted as a real category. |

### Quality Guarantees
- `customer_id` is never null — enforced at the producer by an explicit assertion (`glue-scripts/transform.py`); the job fails rather than write a row without one.
- No duplicate `transaction_id` rows — enforced at the producer by an explicit assertion after deduplication.
- `purchase_date` is always a valid, parsed date (never null) — enforced at the producer by an explicit assertion; both ISO 8601 and `MM/DD/YYYY` source formats are parsed before this check runs.
- `order_value` falls within $15.00–$620.00 (the full observed range of the source data; imputed values are the column median, which falls inside this range by construction).
- `num_items` falls within 1–9 (the full observed range of the source data).
- `payment_method` ∈ {`credit_card`, `debit_card`, `gift_card`, `cash`, `unknown`}; `channel` ∈ {`store`, `online`, `unknown`} — the `"unknown"` value is a legitimate imputed value, not a defect, and consumers should treat it as such.
- Grain is transaction-level: row count is always strictly greater than distinct `customer_id` count for any non-trivial dataset (a customer is expected to have multiple transactions).

### SLA
- Data is available in `processed/customers/` within 2 hours of landing in `raw/customers/`, assuming the crawler and transform job are triggered promptly after upload. This lab does not implement automated triggering or SLA monitoring (the pipeline is run manually via `aws glue start-crawler` / `start-job-run`) — the 2-hour figure is the target once Lab 5+ wires up an EventBridge-triggered pipeline, not a currently-enforced guarantee.

### Versioning
- Schema changes require a new S3 prefix (e.g. `processed/customers/v2/`) rather than an in-place column change, so existing consumers never see a schema they didn't sign up for.
- Breaking changes (column removal, type change, semantic change to an existing column) require consumer notification 5 business days in advance. Additive changes (a new nullable column) do not require a prefix bump but should still be announced to consumers.
