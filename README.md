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

## Verified KPIs (real, rerunnable — see `kpis_and_keys.py`)

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

`api.py` — FastAPI service exposing:
- `GET /sellers/top?limit=N&sort_by=total_revenue` — top sellers by any KPI
- `GET /sellers/{seller_id}` — full KPI detail for one seller
- `GET /kpis/fulfillment?state=SP` — fulfillment summary, optionally
  filtered by seller state
- `GET /health`

Runs locally against the packaged Parquet files through DuckDB. A Redshift
backend requires a separate connection/query adapter; it is not a drop-in
connection change. Fulfillment rates are line-item weighted; `order_count`
is the distinct order count within the selected seller scope.


## Run locally

Python 3.10+ is required. Run from the repository root:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs for the API explorer. The committed Parquet
files are enough to serve the API; raw CSVs and AWS credentials are not required.
Paths resolve relative to the repository, independently of the shell directory.
`VENDORPULSE_WAREHOUSE` overrides the Parquet directory.

To rebuild, obtain the Olist source CSVs and put the eight files read by
`transform.py` in `data/` (or set `VENDORPULSE_RAW`). Then run:

```bash
python transform.py
python kpis_and_keys.py
```

These commands replace generated warehouse files. To preserve the packaged
outputs, set `VENDORPULSE_WAREHOUSE` to a separate output directory first.
The raw CSV download is not automated. Local tests use small synthetic fixtures
and do not independently validate the historical full-dataset metrics above.

## Optional Redshift deployment (not validated by the local API tests)

1. Upload the nine generated `.parquet` files to your bucket under
   `vendorpulse/staging/`, matching the paths in `02_copy_from_s3.sql`.
2. Create a Redshift Serverless workgroup + namespace, with an IAM role
   attached that has `s3:GetObject` on your bucket
3. Run `01_create_tables.sql` in the Redshift query editor
4. Fill in `<your-bucket>` and `<your-redshift-role-arn>` in
   `02_copy_from_s3.sql` and run it — the final query in that file
   checks loaded row counts against the numbers above

