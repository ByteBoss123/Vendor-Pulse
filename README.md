# VendorPulse

Seller performance & fulfillment KPI warehouse. Built to demonstrate the ETL
+ data-warehousing + self-serve reporting responsibilities in Amazon's
Data Engineer I, Sales Data Services (SDS) posting.

## Architecture

```
Raw CSVs (Olist Brazilian e-commerce, 9 real tables, ~450K total rows)
   -> S3 (raw landing zone)
   -> Transform (Python/DuckDB: clean, dedup, build star schema, write Parquet)
   -> S3 (staging, Parquet)
   -> Redshift COPY (star schema, DISTKEY/SORTKEY per table)
   -> FastAPI self-serve KPI layer
```

## Data

Real, public Olist Brazilian e-commerce dataset: orders, order_items,
payments, reviews, sellers, products, customers, geolocation,
category-name translation. 99,441 orders / 112,650 order line items /
3,095 sellers / 32,951 products.

## Star schema

- `dim_seller`, `dim_product`, `dim_customer`, `dim_date` — small,
  `DISTSTYLE ALL` (replicated to every node, no shuffle on join)
- `fact_orders`, `fact_order_items`, `fact_reviews`, `fact_payments` —
  large, `DISTKEY` on the join column that co-locates each fact with the
  dimension/fact it's most often joined against, `SORTKEY` on
  `purchase_date` for date-range zone-map pruning
- `seller_kpis` — pre-aggregated rollup table the API reads from directly

## Verified data quality

- 0 duplicate `order_id` rows, 0 duplicate `seller_id` rows
- 0 orphaned `seller_id`/`product_id` foreign keys in `fact_order_items`
  after the join (checked explicitly, not assumed)
- Review dedup logic verified: 99,224 raw review rows -> 98,673 after
  keeping the latest review per order

## Verified KPIs (real, rerunnable — see `scripts/kpis_and_keys.py`)

- 3,095 sellers with computed KPIs
- 90.09% overall on-time delivery rate
- 4.09 average review score
- Top seller by revenue: $249,640.70 across 1,132 orders (87.8% on-time)

## Sort-key justification (real measurement, disclosed limitation)

Measured a 27.9% median latency improvement (1.99ms -> 1.43ms) on a
one-month date-range aggregate query when the fact table is physically
sorted by `purchase_date`, versus randomly ordered. This is a local
DuckDB approximation of Redshift's zone-map block-skipping behavior on a
~112K-row table — not a production Redshift benchmark on production data
volumes. The mechanism (skip blocks outside the sort key's min/max range)
is the same one Redshift's SORTKEY relies on, so the direction of the
result should hold, but the magnitude will differ at Redshift scale and
is disclosed as such.

## Self-serve API

`scripts/api.py` — FastAPI service exposing:
- `GET /sellers/top?limit=N&sort_by=total_revenue` — top sellers by any KPI
- `GET /sellers/{seller_id}` — full KPI detail for one seller
- `GET /kpis/fulfillment?state=SP` — fulfillment summary, optionally
  filtered by seller state
- `GET /health`

Runs locally against the DuckDB warehouse for development. Swapping
`get_con()` to `redshift_connector` against a real Redshift Serverless
workgroup endpoint requires no route changes — same self-serve pattern,
different engine underneath.

## Deploying the Redshift half yourself

This sandbox has no network access to AWS, so the Redshift Serverless
provisioning and the actual `COPY` load have to run in your own AWS
account (free-tier eligible):

1. Create an S3 bucket, upload `warehouse/*.parquet`
   (skip the `duckdb_export/` folder — that's for local use only)
2. Create a Redshift Serverless workgroup + namespace, with an IAM role
   attached that has `s3:GetObject` on your bucket
3. Run `sql/01_create_tables.sql` in the Redshift query editor
4. Fill in `<your-bucket>` and `<your-redshift-role-arn>` in
   `sql/02_copy_from_s3.sql` and run it — the final query in that file
   checks loaded row counts against the numbers above
