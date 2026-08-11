-- VendorPulse star schema on Redshift
-- Run in Redshift Serverless / a provisioned cluster's query editor.

CREATE SCHEMA IF NOT EXISTS vendorpulse;

-- Dimension tables: small, replicated to every node (ALL distribution)
-- so joins against them never require a network shuffle.

CREATE TABLE vendorpulse.dim_seller (
    seller_id               VARCHAR(64) NOT NULL,
    seller_zip_code_prefix  VARCHAR(16),
    seller_city             VARCHAR(128),
    seller_state            VARCHAR(4)
)
DISTSTYLE ALL
SORTKEY (seller_id);

CREATE TABLE vendorpulse.dim_product (
    product_id           VARCHAR(64) NOT NULL,
    product_category_name VARCHAR(128),
    category_english      VARCHAR(128),
    product_weight_g      INT,
    product_length_cm     INT,
    product_height_cm     INT,
    product_width_cm      INT
)
DISTSTYLE ALL
SORTKEY (product_id);

CREATE TABLE vendorpulse.dim_customer (
    customer_id             VARCHAR(64) NOT NULL,
    customer_unique_id      VARCHAR(64),
    customer_zip_code_prefix VARCHAR(16),
    customer_city            VARCHAR(128),
    customer_state            VARCHAR(4)
)
DISTSTYLE ALL
SORTKEY (customer_id);

CREATE TABLE vendorpulse.dim_date (
    date_key    DATE NOT NULL,
    year        INT,
    month       INT,
    day         INT,
    day_of_week INT
)
DISTSTYLE ALL
SORTKEY (date_key);

-- Fact tables: large, high-cardinality. DISTKEY on seller_id/order_id
-- co-locates rows that get joined together (fact_order_items <-> dim_seller,
-- fact_order_items <-> fact_orders) on the same node slice, avoiding
-- cross-node shuffles on the join. SORTKEY on purchase_date/order_id
-- lets Redshift's zone maps skip whole blocks on date-range predicates --
-- measured locally at a 27.9% median latency improvement on a one-month
-- range scan (see kpis_and_keys.py; local DuckDB approximation of
-- Redshift's block-skipping behavior, not a production Redshift benchmark).

CREATE TABLE vendorpulse.fact_orders (
    order_id                     VARCHAR(64) NOT NULL,
    customer_id                  VARCHAR(64),
    order_status                 VARCHAR(32),
    purchase_date                DATE,
    order_purchase_timestamp     TIMESTAMP,
    order_approved_at            TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP,
    delivery_delay_days          INT,
    delivered_on_time            BOOLEAN,
    fulfillment_days             INT
)
DISTKEY (order_id)
SORTKEY (purchase_date);

CREATE TABLE vendorpulse.fact_order_items (
    order_id           VARCHAR(64) NOT NULL,
    order_item_id       INT,
    product_id          VARCHAR(64),
    seller_id           VARCHAR(64),
    price                DECIMAL(10,2),
    freight_value        DECIMAL(10,2),
    item_total            DECIMAL(10,2),
    purchase_date          DATE,
    delivered_on_time       BOOLEAN,
    delivery_delay_days      INT
)
DISTKEY (seller_id)
SORTKEY (purchase_date);

CREATE TABLE vendorpulse.fact_reviews (
    order_id             VARCHAR(64) NOT NULL,
    review_score          INT,
    review_creation_date   TIMESTAMP
)
DISTKEY (order_id)
SORTKEY (review_creation_date);

CREATE TABLE vendorpulse.fact_payments (
    order_id            VARCHAR(64) NOT NULL,
    total_payment_value   DECIMAL(12,2),
    payment_row_count      INT
)
DISTKEY (order_id)
SORTKEY (order_id);

CREATE TABLE vendorpulse.seller_kpis (
    seller_id        VARCHAR(64) NOT NULL,
    seller_state      VARCHAR(4),
    seller_city        VARCHAR(128),
    order_count          INT,
    total_revenue          DECIMAL(14,2),
    avg_item_price           DECIMAL(10,2),
    on_time_rate               DECIMAL(6,4),
    avg_delay_days               DECIMAL(8,2),
    avg_review_score               DECIMAL(4,2)
)
DISTSTYLE ALL
SORTKEY (total_revenue);
