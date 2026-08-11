"""
VendorPulse self-serve KPI API.

Backed by the local DuckDB warehouse for development/demo. To point at a
real Redshift deployment, swap `get_con()` to use redshift_connector
(pip install redshift_connector) with your workgroup endpoint, and the
route bodies are unchanged -- this demonstrates the same "internal
customers self-serve their own reporting" pattern the JD asks for,
independent of which engine sits underneath.
"""
from fastapi import FastAPI, HTTPException, Query
import duckdb

WAREHOUSE = "/home/claude/vendorpulse/warehouse"
app = FastAPI(title="VendorPulse KPI API")


def get_con():
    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE seller_kpis AS SELECT * FROM read_parquet('{WAREHOUSE}/seller_kpis.parquet');
        CREATE TABLE fact_order_items AS SELECT * FROM read_parquet('{WAREHOUSE}/fact_order_items.parquet');
        CREATE TABLE fact_orders AS SELECT * FROM read_parquet('{WAREHOUSE}/fact_orders.parquet');
    """)
    return con


@app.get("/sellers/top")
def top_sellers(limit: int = Query(10, le=100), sort_by: str = "total_revenue"):
    allowed = {"total_revenue", "order_count", "on_time_rate", "avg_review_score"}
    if sort_by not in allowed:
        raise HTTPException(400, f"sort_by must be one of {allowed}")
    con = get_con()
    rows = con.execute(f"""
        SELECT seller_id, seller_state, seller_city, order_count,
               total_revenue, on_time_rate, avg_review_score
        FROM seller_kpis
        ORDER BY {sort_by} DESC
        LIMIT ?
    """, [limit]).fetchall()
    cols = ["seller_id", "seller_state", "seller_city", "order_count",
            "total_revenue", "on_time_rate", "avg_review_score"]
    con.close()
    return [dict(zip(cols, r)) for r in rows]


@app.get("/sellers/{seller_id}")
def seller_detail(seller_id: str):
    con = get_con()
    row = con.execute(
        "SELECT * FROM seller_kpis WHERE seller_id = ?", [seller_id]
    ).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, "seller not found")
    cols = ["seller_id", "seller_state", "seller_city", "order_count",
            "total_revenue", "avg_item_price", "on_time_rate",
            "avg_delay_days", "avg_review_score"]
    return dict(zip(cols, row))


@app.get("/kpis/fulfillment")
def fulfillment_summary(state: str | None = None):
    con = get_con()
    where = ""
    params = []
    if state:
        where = "WHERE ds.seller_state = ?"
        params = [state]
        con.execute(f"""
            CREATE TABLE dim_seller AS SELECT * FROM read_parquet('{WAREHOUSE}/dim_seller.parquet');
        """)
        row = con.execute(f"""
            SELECT
                AVG(CASE WHEN foi.delivered_on_time THEN 1.0 ELSE 0.0 END) AS on_time_rate,
                AVG(foi.delivery_delay_days) AS avg_delay_days,
                COUNT(DISTINCT foi.order_id) AS order_count
            FROM fact_order_items foi
            JOIN dim_seller ds ON foi.seller_id = ds.seller_id
            {where}
        """, params).fetchone()
    else:
        row = con.execute("""
            SELECT
                AVG(CASE WHEN delivered_on_time THEN 1.0 ELSE 0.0 END) AS on_time_rate,
                AVG(delivery_delay_days) AS avg_delay_days,
                COUNT(*) AS order_count
            FROM fact_order_items
        """).fetchone()
    con.close()
    return {
        "scope": state or "all",
        "on_time_rate": row[0],
        "avg_delay_days": row[1],
        "order_count": row[2],
    }


@app.get("/health")
def health():
    return {"status": "ok"}
