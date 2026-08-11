"""
VendorPulse transform layer.
Reads raw Olist CSVs, builds a star schema (fact_orders, fact_order_items,
dim_seller, dim_product, dim_customer, dim_date), writes to Parquet.

This mirrors the transform step that would run before an S3 -> Redshift COPY
in a real deployment. Locally we validate against DuckDB, which understands
the same COPY/DISTKEY-adjacent concepts and lets us verify row counts and
join integrity before touching real infrastructure.
"""
import duckdb
import os

RAW = "/home/claude/vendorpulse/data"
OUT = "/home/claude/vendorpulse/warehouse"
os.makedirs(OUT, exist_ok=True)

con = duckdb.connect()

# ---- Load raw CSVs ----
con.execute(f"""
    CREATE OR REPLACE TABLE raw_orders AS
    SELECT * FROM read_csv_auto('{RAW}/olist_orders_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_order_items AS
    SELECT * FROM read_csv_auto('{RAW}/olist_order_items_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_payments AS
    SELECT * FROM read_csv_auto('{RAW}/olist_order_payments_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_reviews AS
    SELECT * FROM read_csv_auto('{RAW}/olist_order_reviews_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_customers AS
    SELECT * FROM read_csv_auto('{RAW}/olist_customers_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_sellers AS
    SELECT * FROM read_csv_auto('{RAW}/olist_sellers_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_products AS
    SELECT * FROM read_csv_auto('{RAW}/olist_products_dataset.csv', header=True);

    CREATE OR REPLACE TABLE raw_category_translation AS
    SELECT * FROM read_csv_auto('{RAW}/product_category_name_translation.csv', header=True);
""")

print("Raw row counts:")
for t in ["raw_orders", "raw_order_items", "raw_payments", "raw_reviews",
          "raw_customers", "raw_sellers", "raw_products"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n:,}")

# ---- Data quality: dedup check before building dims ----
dupe_orders = con.execute(
    "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM raw_orders"
).fetchone()[0]
dupe_sellers = con.execute(
    "SELECT COUNT(*) - COUNT(DISTINCT seller_id) FROM raw_sellers"
).fetchone()[0]
print(f"\nDuplicate order_id rows: {dupe_orders}")
print(f"Duplicate seller_id rows: {dupe_sellers}")

# ---- dim_seller ----
con.execute("""
    CREATE OR REPLACE TABLE dim_seller AS
    SELECT
        seller_id,
        seller_zip_code_prefix,
        seller_city,
        seller_state
    FROM raw_sellers;
""")

# ---- dim_product ----
con.execute("""
    CREATE OR REPLACE TABLE dim_product AS
    SELECT
        p.product_id,
        p.product_category_name,
        COALESCE(t.product_category_name_english, p.product_category_name) AS category_english,
        p.product_weight_g,
        p.product_length_cm,
        p.product_height_cm,
        p.product_width_cm
    FROM raw_products p
    LEFT JOIN raw_category_translation t
        ON p.product_category_name = t.product_category_name;
""")

# ---- dim_customer ----
con.execute("""
    CREATE OR REPLACE TABLE dim_customer AS
    SELECT
        customer_id,
        customer_unique_id,
        customer_zip_code_prefix,
        customer_city,
        customer_state
    FROM raw_customers;
""")

# ---- dim_date (from order purchase timestamps, one row per calendar day in range) ----
con.execute("""
    CREATE OR REPLACE TABLE dim_date AS
    SELECT
        CAST(d AS DATE) AS date_key,
        EXTRACT(year FROM d) AS year,
        EXTRACT(month FROM d) AS month,
        EXTRACT(day FROM d) AS day,
        EXTRACT(dow FROM d) AS day_of_week
    FROM (
        SELECT UNNEST(generate_series(
            (SELECT MIN(CAST(order_purchase_timestamp AS DATE)) FROM raw_orders),
            (SELECT MAX(CAST(order_purchase_timestamp AS DATE)) FROM raw_orders),
            INTERVAL 1 DAY
        )) AS d
    );
""")

# ---- fact_orders: one row per order, with fulfillment KPIs pre-computed ----
con.execute("""
    CREATE OR REPLACE TABLE fact_orders AS
    SELECT
        o.order_id,
        o.customer_id,
        o.order_status,
        CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
        o.order_purchase_timestamp,
        o.order_approved_at,
        o.order_delivered_carrier_date,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date,
        -- delivery delay in days: negative = delivered early, positive = late
        DATE_DIFF('day',
            CAST(o.order_estimated_delivery_date AS TIMESTAMP),
            CAST(o.order_delivered_customer_date AS TIMESTAMP)
        ) AS delivery_delay_days,
        CASE
            WHEN o.order_delivered_customer_date IS NULL THEN NULL
            WHEN CAST(o.order_delivered_customer_date AS TIMESTAMP)
                 <= CAST(o.order_estimated_delivery_date AS TIMESTAMP) THEN TRUE
            ELSE FALSE
        END AS delivered_on_time,
        DATE_DIFF('day',
            CAST(o.order_purchase_timestamp AS TIMESTAMP),
            CAST(o.order_delivered_customer_date AS TIMESTAMP)
        ) AS fulfillment_days
    FROM raw_orders o;
""")

# ---- fact_order_items: one row per line item, joined to seller/product/pricing ----
con.execute("""
    CREATE OR REPLACE TABLE fact_order_items AS
    SELECT
        oi.order_id,
        oi.order_item_id,
        oi.product_id,
        oi.seller_id,
        oi.price,
        oi.freight_value,
        oi.price + oi.freight_value AS item_total,
        fo.purchase_date,
        fo.delivered_on_time,
        fo.delivery_delay_days
    FROM raw_order_items oi
    JOIN fact_orders fo ON oi.order_id = fo.order_id;
""")

# ---- fact_reviews: review score per order (dedup: keep latest review per order) ----
con.execute("""
    CREATE OR REPLACE TABLE fact_reviews AS
    SELECT order_id, review_score, review_creation_date
    FROM (
        SELECT
            order_id, review_score, review_creation_date,
            ROW_NUMBER() OVER (
                PARTITION BY order_id ORDER BY review_creation_date DESC
            ) AS rn
        FROM raw_reviews
    )
    WHERE rn = 1;
""")

# ---- fact_payments: total paid per order (sum across installments/methods) ----
con.execute("""
    CREATE OR REPLACE TABLE fact_payments AS
    SELECT order_id, SUM(payment_value) AS total_payment_value,
           COUNT(*) AS payment_row_count
    FROM raw_payments
    GROUP BY order_id;
""")

print("\nStar schema row counts:")
for t in ["dim_seller", "dim_product", "dim_customer", "dim_date",
          "fact_orders", "fact_order_items", "fact_reviews", "fact_payments"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n:,}")

# ---- Join integrity check: every fact_order_items.seller_id resolves to dim_seller ----
orphan_sellers = con.execute("""
    SELECT COUNT(*) FROM fact_order_items foi
    LEFT JOIN dim_seller ds ON foi.seller_id = ds.seller_id
    WHERE ds.seller_id IS NULL
""").fetchone()[0]
orphan_products = con.execute("""
    SELECT COUNT(*) FROM fact_order_items foi
    LEFT JOIN dim_product dp ON foi.product_id = dp.product_id
    WHERE dp.product_id IS NULL
""").fetchone()[0]
print(f"\nOrphan seller_id in fact_order_items: {orphan_sellers}")
print(f"Orphan product_id in fact_order_items: {orphan_products}")

# ---- Export to Parquet (staging for S3 upload / Redshift COPY) ----
for t in ["dim_seller", "dim_product", "dim_customer", "dim_date",
          "fact_orders", "fact_order_items", "fact_reviews", "fact_payments"]:
    con.execute(f"COPY {t} TO '{OUT}/{t}.parquet' (FORMAT PARQUET)")

# ---- Persist warehouse as a DuckDB file too, for the FastAPI layer to query ----
con.execute(f"EXPORT DATABASE '{OUT}/duckdb_export' (FORMAT PARQUET)")

print(f"\nParquet files written to {OUT}/")
con.close()
