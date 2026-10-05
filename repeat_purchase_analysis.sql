-- =====================================================================
-- Customer Repeat Purchase Analysis - SQL Script
-- Task 28 - Data Analytics Track, Veda Technology
--
-- Written in standard SQL (CTEs + window functions only), so it runs on
-- PostgreSQL, SQLite 3.25+ and MySQL 8+. It was tested on SQLite; run
-- run_sql_sqlite.py to regenerate sql_output.txt.
--
-- Input: table `transactions` holding data.csv, one row per invoice line:
--   CREATE TABLE transactions (
--       InvoiceNo   VARCHAR(20),
--       StockCode   VARCHAR(20),
--       Description VARCHAR(100),
--       Quantity    INT,
--       InvoiceDate VARCHAR(30),      -- or TIMESTAMP
--       UnitPrice   DECIMAL(10,2),
--       CustomerID  VARCHAR(20),
--       Country     VARCHAR(50)
--   );
--   PostgreSQL load: \copy transactions FROM 'data.csv' CSV HEADER
--
-- Order value = SUM(Quantity * UnitPrice) per invoice. (Using UnitPrice
-- alone ignores quantity and gives wrong AOV.)
-- =====================================================================

DROP VIEW IF EXISTS customer_segments;
DROP VIEW IF EXISTS vip_threshold;
DROP VIEW IF EXISTS customer_summary;
DROP VIEW IF EXISTS orders;

-- ---------------------------------------------------------------------
-- Base view: one row per order (invoice), returns/invalid rows removed
-- ---------------------------------------------------------------------
CREATE VIEW orders AS
SELECT
    InvoiceNo                                           AS order_id,
    CustomerID                                          AS customer_id,
    SUBSTR(CAST(MIN(InvoiceDate) AS VARCHAR(30)), 1, 10) AS order_date,
    SUM(Quantity * UnitPrice)                           AS order_value
FROM transactions
WHERE CustomerID IS NOT NULL
  AND Quantity > 0
  AND UnitPrice > 0
GROUP BY InvoiceNo, CustomerID;

-- ---------------------------------------------------------------------
-- Customer view: orders, spend, AOV and repeat / one-time flag
-- ---------------------------------------------------------------------
CREATE VIEW customer_summary AS
SELECT
    customer_id,
    COUNT(*)         AS total_orders,
    SUM(order_value) AS total_value,
    AVG(order_value) AS avg_order_value,
    CASE WHEN COUNT(*) >= 2 THEN 'Repeat' ELSE 'One-time' END AS customer_type
FROM orders
GROUP BY customer_id;

-- ---------------------------------------------------------------------
-- 75th-percentile spend (linear interpolation, same as pandas quantile)
-- ---------------------------------------------------------------------
CREATE VIEW vip_threshold AS
WITH ordered AS (
    SELECT
        total_value,
        ROW_NUMBER() OVER (ORDER BY total_value)       AS rn,
        COUNT(*)     OVER ()                           AS n,
        LEAD(total_value) OVER (ORDER BY total_value)  AS next_value
    FROM customer_summary
)
SELECT
    MAX(CASE
          WHEN rn <= 1 + 0.75 * (n - 1) AND rn + 1 > 1 + 0.75 * (n - 1)
          THEN total_value
               + (1 + 0.75 * (n - 1) - rn) * (COALESCE(next_value, total_value) - total_value)
        END) AS q75_value
FROM ordered;

-- ---------------------------------------------------------------------
-- Segments: VIP / Loyal / Occasional Repeat / One-time
-- ---------------------------------------------------------------------
CREATE VIEW customer_segments AS
SELECT
    cs.customer_id,
    cs.total_orders,
    cs.total_value,
    cs.avg_order_value,
    CASE
        WHEN cs.total_orders >= 5 AND cs.total_value > t.q75_value THEN 'VIP'
        WHEN cs.total_orders >= 5                                  THEN 'Loyal'
        WHEN cs.total_orders >= 2                                  THEN 'Occasional Repeat'
        ELSE 'One-time'
    END AS segment
FROM customer_summary cs
CROSS JOIN vip_threshold t;

-- ===================================================================
-- [Q1] Define repeat customers (top 10 by orders; remove LIMIT for all)
-- ===================================================================
SELECT customer_id, total_orders, customer_type
FROM customer_summary
ORDER BY total_orders DESC, customer_id
LIMIT 10;

-- ===================================================================
-- [Q2] Repeat rate
-- ===================================================================
SELECT
    COUNT(*)                                                      AS total_customers,
    SUM(CASE WHEN customer_type = 'Repeat'   THEN 1 ELSE 0 END)   AS repeat_customers,
    SUM(CASE WHEN customer_type = 'One-time' THEN 1 ELSE 0 END)   AS one_time_customers,
    ROUND(100.0 * SUM(CASE WHEN customer_type = 'Repeat' THEN 1 ELSE 0 END) / COUNT(*), 2)
                                                                  AS repeat_rate_pct
FROM customer_summary;

-- ===================================================================
-- [Q3a] AOV: one-time customers vs repeat customers
-- ===================================================================
SELECT
    cs.customer_type,
    COUNT(DISTINCT cs.customer_id) AS customers,
    COUNT(*)                       AS orders,
    ROUND(SUM(o.order_value), 2)   AS total_value,
    ROUND(AVG(o.order_value), 2)   AS aov
FROM orders o
JOIN customer_summary cs ON o.customer_id = cs.customer_id
GROUP BY cs.customer_type
ORDER BY cs.customer_type;

-- ===================================================================
-- [Q3b] AOV: each customer's first order vs their repeat orders
-- ===================================================================
WITH ranked AS (
    SELECT
        order_id,
        customer_id,
        order_value,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date, order_id) AS order_number
    FROM orders
)
SELECT
    CASE WHEN order_number = 1 THEN 'First order' ELSE 'Repeat order' END AS order_type,
    COUNT(*)                       AS orders,
    ROUND(SUM(order_value), 2)     AS total_value,
    ROUND(AVG(order_value), 2)     AS aov
FROM ranked
GROUP BY CASE WHEN order_number = 1 THEN 'First order' ELSE 'Repeat order' END
ORDER BY order_type;

-- ===================================================================
-- [Q4a] Customer segmentation - 75th percentile spend threshold
-- ===================================================================
SELECT ROUND(q75_value, 2) AS vip_spend_threshold FROM vip_threshold;

-- ===================================================================
-- [Q4b] Segment table (customers, share of customers and revenue, AOV)
-- ===================================================================
SELECT
    segment,
    COUNT(*)                                                       AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)             AS pct_customers,
    SUM(total_orders)                                              AS total_orders,
    ROUND(SUM(total_value), 2)                                     AS total_value,
    ROUND(100.0 * SUM(total_value) / SUM(SUM(total_value)) OVER (), 1) AS pct_revenue,
    ROUND(1.0 * SUM(total_orders) / COUNT(*), 2)                   AS avg_orders_per_customer,
    ROUND(SUM(total_value) / SUM(total_orders), 2)                 AS aov
FROM customer_segments
GROUP BY segment
ORDER BY CASE segment
             WHEN 'VIP' THEN 1 WHEN 'Loyal' THEN 2
             WHEN 'Occasional Repeat' THEN 3 ELSE 4 END;

-- ===================================================================
-- [Q4c] Customer-level segment table (top 10 by spend; remove LIMIT for all)
-- ===================================================================
SELECT
    customer_id,
    total_orders,
    ROUND(total_value, 2)     AS total_value,
    ROUND(avg_order_value, 2) AS avg_order_value,
    segment
FROM customer_segments
ORDER BY total_value DESC
LIMIT 10;

-- ===================================================================
-- [Q5] Monthly returning-customer rate
--      (share of a month's active customers who ordered in an earlier month)
-- ===================================================================
WITH first_order AS (
    SELECT customer_id, SUBSTR(MIN(order_date), 1, 7) AS first_month
    FROM orders
    GROUP BY customer_id
),
monthly AS (
    SELECT
        SUBSTR(o.order_date, 1, 7) AS order_month,
        o.customer_id,
        f.first_month
    FROM orders o
    JOIN first_order f ON o.customer_id = f.customer_id
    GROUP BY SUBSTR(o.order_date, 1, 7), o.customer_id, f.first_month
)
SELECT
    order_month,
    COUNT(*)                                                         AS active_customers,
    SUM(CASE WHEN first_month < order_month THEN 1 ELSE 0 END)       AS returning_customers,
    ROUND(100.0 * SUM(CASE WHEN first_month < order_month THEN 1 ELSE 0 END) / COUNT(*), 2)
                                                                     AS returning_rate_pct
FROM monthly
GROUP BY order_month
ORDER BY order_month;

-- ===================================================================
-- [Q6] Cohort retention (month_number 1 = the cohort's first month)
-- ===================================================================
WITH first_order AS (
    SELECT customer_id, SUBSTR(MIN(order_date), 1, 7) AS cohort_month
    FROM orders
    GROUP BY customer_id
),
cohort_size AS (
    SELECT cohort_month, COUNT(*) AS cohort_customers
    FROM first_order
    GROUP BY cohort_month
),
activity AS (
    SELECT
        f.cohort_month,
        SUBSTR(o.order_date, 1, 7)  AS activity_month,
        COUNT(DISTINCT o.customer_id) AS active_customers
    FROM orders o
    JOIN first_order f ON o.customer_id = f.customer_id
    GROUP BY f.cohort_month, SUBSTR(o.order_date, 1, 7)
)
SELECT
    a.cohort_month,
    a.activity_month,
    (CAST(SUBSTR(a.activity_month, 1, 4) AS INTEGER) - CAST(SUBSTR(a.cohort_month, 1, 4) AS INTEGER)) * 12
      + CAST(SUBSTR(a.activity_month, 6, 2) AS INTEGER)
      - CAST(SUBSTR(a.cohort_month, 6, 2) AS INTEGER) + 1       AS month_number,
    a.active_customers,
    s.cohort_customers,
    ROUND(100.0 * a.active_customers / s.cohort_customers, 2)    AS retention_pct
FROM activity a
JOIN cohort_size s ON a.cohort_month = s.cohort_month
ORDER BY a.cohort_month, a.activity_month;
