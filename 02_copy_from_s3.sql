-- Run after uploading the Parquet files from /warehouse to your S3 bucket:
--   aws s3 cp warehouse/ s3://<your-bucket>/vendorpulse/staging/ --recursive --exclude "duckdb_export/*"
--
-- Replace <your-bucket> and <your-redshift-role-arn> (an IAM role attached
-- to the Redshift Serverless workgroup with s3:GetObject on the bucket).

COPY vendorpulse.dim_seller
FROM 's3://<your-bucket>/vendorpulse/staging/dim_seller.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.dim_product
FROM 's3://<your-bucket>/vendorpulse/staging/dim_product.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.dim_customer
FROM 's3://<your-bucket>/vendorpulse/staging/dim_customer.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.dim_date
FROM 's3://<your-bucket>/vendorpulse/staging/dim_date.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.fact_orders
FROM 's3://<your-bucket>/vendorpulse/staging/fact_orders.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.fact_order_items
FROM 's3://<your-bucket>/vendorpulse/staging/fact_order_items.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.fact_reviews
FROM 's3://<your-bucket>/vendorpulse/staging/fact_reviews.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.fact_payments
FROM 's3://<your-bucket>/vendorpulse/staging/fact_payments.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

COPY vendorpulse.seller_kpis
FROM 's3://<your-bucket>/vendorpulse/staging/seller_kpis.parquet'
IAM_ROLE '<your-redshift-role-arn>'
FORMAT AS PARQUET;

-- Sanity check after load: row counts should match the transform.py output
-- (dim_seller 3095, dim_product 32951, dim_customer 99441, fact_orders 99441,
--  fact_order_items 112650, fact_reviews 98673, fact_payments 99440,
--  seller_kpis 3095).
SELECT 'dim_seller' AS table_name, COUNT(*) FROM vendorpulse.dim_seller
UNION ALL SELECT 'dim_product', COUNT(*) FROM vendorpulse.dim_product
UNION ALL SELECT 'dim_customer', COUNT(*) FROM vendorpulse.dim_customer
UNION ALL SELECT 'fact_orders', COUNT(*) FROM vendorpulse.fact_orders
UNION ALL SELECT 'fact_order_items', COUNT(*) FROM vendorpulse.fact_order_items
UNION ALL SELECT 'fact_reviews', COUNT(*) FROM vendorpulse.fact_reviews
UNION ALL SELECT 'fact_payments', COUNT(*) FROM vendorpulse.fact_payments
UNION ALL SELECT 'seller_kpis', COUNT(*) FROM vendorpulse.seller_kpis;
