"""
VendorPulse: seller KPI rollups + sort-key latency justification.

Part 1: build the seller-level KPI table the self-serve API will expose.
Part 2: honestly measure whether a purchase_date-sorted fact table speeds up
a realistic date-range query, using DuckDB's row-scan behavior as a proxy
for Redshift's SORTKEY zone-map pruning. This is a real, rerunnable
measurement, not a borrowed industry benchmark.
"""
import duckdb
import time

OUT = "/home/claude/vendorpulse/warehouse"
con = duckdb.connect()

con.execute(f"""
    CREATE TABLE fact_order_items AS SELECT * FROM read_parquet('{OUT}/fact_order_items.parquet');
    CREATE TABLE fact_orders AS SELECT * FROM read_parquet('{OUT}/fact_orders.parquet');
    CREATE TABLE fact_reviews AS SELECT * FROM read_parquet('{OUT}/fact_reviews.parquet');
    CREATE TABLE dim_seller AS SELECT * FROM read_parquet('{OUT}/dim_seller.parquet');
""")

# ---- Seller KPI rollup ----
con.execute("""
    CREATE OR REPLACE TABLE seller_kpis AS
    SELECT
        ds.seller_id,
        ds.seller_state,
        ds.seller_city,
        COUNT(DISTINCT foi.order_id) AS order_count,
        SUM(foi.item_total) AS total_revenue,
        AVG(foi.price) AS avg_item_price,
        AVG(CASE WHEN foi.delivered_on_time THEN 1.0 ELSE 0.0 END) AS on_time_rate,
        AVG(foi.delivery_delay_days) AS avg_delay_days,
        AVG(fr.review_score) AS avg_review_score
    FROM fact_order_items foi
    JOIN dim_seller ds ON foi.seller_id = ds.seller_id
    LEFT JOIN fact_reviews fr ON foi.order_id = fr.order_id
    GROUP BY ds.seller_id, ds.seller_state, ds.seller_city
""")

n_sellers = con.execute("SELECT COUNT(*) FROM seller_kpis").fetchone()[0]
overall_on_time = con.execute(
    "SELECT AVG(CASE WHEN delivered_on_time THEN 1.0 ELSE 0.0 END) FROM fact_order_items"
).fetchone()[0]
overall_review = con.execute("SELECT AVG(review_score) FROM fact_reviews").fetchone()[0]
print(f"Sellers with KPIs: {n_sellers:,}")
print(f"Overall on-time delivery rate: {overall_on_time:.4f}")
print(f"Overall avg review score: {overall_review:.4f}")

top5 = con.execute("""
    SELECT seller_id, seller_state, order_count, total_revenue, on_time_rate, avg_review_score
    FROM seller_kpis ORDER BY total_revenue DESC LIMIT 5
""").fetchall()
print("\nTop 5 sellers by revenue:")
for row in top5:
    print(f"  {row}")

con.execute(f"COPY seller_kpis TO '{OUT}/seller_kpis.parquet' (FORMAT PARQUET)")

# ---- Sort-key latency measurement ----
# Build two physical copies of fact_order_items: one in natural (unsorted)
# load order, one explicitly sorted by purchase_date -- the column a
# Redshift SORTKEY on purchase_date would zone-map on. Compare a realistic
# date-range scan against both, several times, and report the median.

con.execute("""
    CREATE OR REPLACE TABLE unsorted_items AS
    SELECT * FROM fact_order_items ORDER BY random();
""")
con.execute("""
    CREATE OR REPLACE TABLE sorted_items AS
    SELECT * FROM fact_order_items ORDER BY purchase_date;
""")

QUERY_TMPL = """
    SELECT seller_id, SUM(item_total) AS revenue, COUNT(*) AS n
    FROM {table}
    WHERE purchase_date BETWEEN '2018-01-01' AND '2018-02-01'
    GROUP BY seller_id
"""

def time_query(table, runs=7):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(QUERY_TMPL.format(table=table)).fetchall()
        times.append(time.perf_counter() - t0)
    times.sort()
    return times[len(times) // 2]  # median

med_unsorted = time_query("unsorted_items")
med_sorted = time_query("sorted_items")
pct_improvement = (med_unsorted - med_sorted) / med_unsorted * 100

print(f"\nDate-range query, median of 7 runs:")
print(f"  unsorted table: {med_unsorted*1000:.2f} ms")
print(f"  sorted table:   {med_sorted*1000:.2f} ms")
print(f"  improvement:    {pct_improvement:.1f}%")

con.close()
