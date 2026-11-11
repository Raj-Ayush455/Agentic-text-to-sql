"""
Phase 1: Database Setup
========================
Creates a SQLite e-commerce database with three tables:
  - customers
  - orders
  - payments

The mock data is intentionally designed to surface ambiguity in natural-language
queries.  For example:
  • "best customer" is ambiguous — Alice has the highest total spend,
    but Bob has the most orders.
  • "recent orders" is ambiguous — no explicit time-frame is given.
  • "most popular payment method" could mean by count or by total value.
  • Some orders have partial / split payments, making "revenue" vs.
    "amount collected" different concepts.
"""

import sqlite3
import os
from datetime import datetime, timedelta
import random

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecommerce.db")


def create_tables(cursor: sqlite3.Cursor) -> None:
    """Create the customers, orders, and payments tables."""

    cursor.execute("DROP TABLE IF EXISTS payments")
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("DROP TABLE IF EXISTS customers")

    cursor.execute("""
        CREATE TABLE customers (
            customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            city          TEXT    NOT NULL,
            signup_date   TEXT    NOT NULL          -- ISO-8601 date
        );
    """)

    cursor.execute("""
        CREATE TABLE orders (
            order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            order_date    TEXT    NOT NULL,          -- ISO-8601 date
            total_amount  REAL    NOT NULL,          -- order total in USD
            status        TEXT    NOT NULL            -- 'completed', 'pending', 'cancelled'
                          CHECK (status IN ('completed', 'pending', 'cancelled')),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE payments (
            payment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      INTEGER NOT NULL,
            payment_date  TEXT    NOT NULL,          -- ISO-8601 date
            amount        REAL    NOT NULL,          -- amount of this payment
            method        TEXT    NOT NULL            -- 'credit_card', 'paypal', 'bank_transfer'
                          CHECK (method IN ('credit_card', 'paypal', 'bank_transfer')),
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );
    """)


def seed_customers(cursor: sqlite3.Cursor) -> list[dict]:
    """Insert 8 customers and return their records."""

    customers = [
        # Alice: fewer orders but very high spend per order  → top by revenue
        ("Alice Johnson",   "alice@example.com",    "New York",      "2024-01-15"),
        # Bob: many small orders                             → top by order count
        ("Bob Smith",       "bob@example.com",      "Los Angeles",   "2024-02-20"),
        # Carol: moderate on both axes
        ("Carol Williams",  "carol@example.com",    "Chicago",       "2024-03-10"),
        # Dave: recent burst of orders (tests "last month" ambiguity)
        ("Dave Brown",      "dave@example.com",     "Houston",       "2024-04-05"),
        # Eve: cancelled orders mixed in (tests "best" when cancellations exist)
        ("Eve Davis",       "eve@example.com",      "Phoenix",       "2024-05-12"),
        # Frank: uses only bank_transfer (tests payment-method queries)
        ("Frank Miller",    "frank@example.com",    "Philadelphia",  "2024-06-18"),
        # Grace: signed up recently, single large order
        ("Grace Wilson",    "grace@example.com",    "San Antonio",   "2025-09-01"),
        # Hank: no orders at all (edge case)
        ("Hank Moore",      "hank@example.com",     "San Diego",     "2025-10-01"),
    ]

    cursor.executemany(
        "INSERT INTO customers (name, email, city, signup_date) VALUES (?, ?, ?, ?)",
        customers,
    )

    cursor.execute("SELECT * FROM customers")
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def seed_orders(cursor: sqlite3.Cursor) -> list[dict]:
    """Insert orders carefully crafted to create ambiguity."""

    random.seed(42)  # reproducibility

    # We'll reference "last month" relative to a fixed anchor so the data is
    # always meaningful.  The anchor is October 2026 (current month per prompt).
    anchor = datetime(2026, 10, 15)
    last_month_start = datetime(2026, 10, 1)
    last_month_end   = datetime(2026, 10, 31)

    orders: list[tuple] = []

    # ---------- Alice (customer_id=1): 4 orders, high value ----------
    orders.append((1, "2026-06-10", 2500.00, "completed"))
    orders.append((1, "2026-08-22", 3200.00, "completed"))
    orders.append((1, "2026-10-05", 4100.00, "completed"))   # last month
    orders.append((1, "2026-10-18", 3800.00, "completed"))   # last month

    # ---------- Bob (customer_id=2): 12 small orders ----------
    for i in range(12):
        day = last_month_start + timedelta(days=i * 2)
        if day <= last_month_end:
            orders.append((2, day.strftime("%Y-%m-%d"), round(random.uniform(30, 90), 2), "completed"))
        else:
            orders.append((2, "2026-09-15", round(random.uniform(30, 90), 2), "completed"))

    # ---------- Carol (customer_id=3): 5 mid-range orders ----------
    orders.append((3, "2026-07-01", 600.00, "completed"))
    orders.append((3, "2026-08-15", 750.00, "completed"))
    orders.append((3, "2026-09-20", 820.00, "completed"))
    orders.append((3, "2026-10-10", 900.00, "completed"))   # last month
    orders.append((3, "2026-10-28", 670.00, "pending"))     # last month, pending

    # ---------- Dave (customer_id=4): burst in October ----------
    for d in range(1, 29, 3):
        orders.append((4, f"2026-10-{d:02d}", round(random.uniform(100, 400), 2), "completed"))

    # ---------- Eve (customer_id=5): mix of completed & cancelled ----------
    orders.append((5, "2026-10-03", 1500.00, "completed"))
    orders.append((5, "2026-10-07", 2200.00, "cancelled"))
    orders.append((5, "2026-10-14", 1800.00, "completed"))
    orders.append((5, "2026-10-21", 950.00,  "cancelled"))

    # ---------- Frank (customer_id=6): 3 orders, bank_transfer only ----------
    orders.append((6, "2026-09-05", 320.00, "completed"))
    orders.append((6, "2026-10-12", 410.00, "completed"))
    orders.append((6, "2026-10-25", 550.00, "completed"))

    # ---------- Grace (customer_id=7): single huge order ----------
    orders.append((7, "2026-10-20", 9500.00, "completed"))

    # Hank (customer_id=8): no orders at all

    cursor.executemany(
        "INSERT INTO orders (customer_id, order_date, total_amount, status) VALUES (?, ?, ?, ?)",
        orders,
    )

    cursor.execute("SELECT * FROM orders")
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def seed_payments(cursor: sqlite3.Cursor, orders: list[dict]) -> None:
    """Insert payments for each non-cancelled order.

    Some orders get a single payment; a few get split payments to create
    ambiguity around "total paid" vs. "order total".
    """

    random.seed(99)
    methods = ["credit_card", "paypal", "bank_transfer"]

    payments: list[tuple] = []

    for order in orders:
        if order["status"] == "cancelled":
            continue

        oid = order["order_id"]
        total = order["total_amount"]
        odate = order["order_date"]

        # Frank always pays by bank_transfer
        if order["customer_id"] == 6:
            method = "bank_transfer"
        else:
            method = random.choice(methods)

        # ~20 % of orders get a split payment (two payments summing to total)
        if random.random() < 0.20 and total > 100:
            split = round(total * random.uniform(0.3, 0.7), 2)
            remainder = round(total - split, 2)
            payments.append((oid, odate, split, method))
            # second payment a day later, possibly different method
            next_day = (datetime.fromisoformat(odate) + timedelta(days=1)).strftime("%Y-%m-%d")
            payments.append((oid, next_day, remainder, random.choice(methods)))
        else:
            payments.append((oid, odate, total, method))

    cursor.executemany(
        "INSERT INTO payments (order_id, payment_date, amount, method) VALUES (?, ?, ?, ?)",
        payments,
    )


def print_summary(conn: sqlite3.Connection) -> None:
    """Print a quick summary so the user can verify the data."""

    cur = conn.cursor()

    print("\n" + "=" * 60)
    print("DATABASE SUMMARY")
    print("=" * 60)

    cur.execute("SELECT COUNT(*) FROM customers")
    print(f"  Customers : {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM orders")
    print(f"  Orders    : {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM payments")
    print(f"  Payments  : {cur.fetchone()[0]}")

    print("\n--- Top customers by TOTAL SPEND (completed orders) ---")
    cur.execute("""
        SELECT c.name,
               COUNT(o.order_id)        AS order_count,
               ROUND(SUM(o.total_amount), 2) AS total_spend
        FROM   customers c
        JOIN   orders o ON c.customer_id = o.customer_id
        WHERE  o.status = 'completed'
        GROUP  BY c.customer_id
        ORDER  BY total_spend DESC
        LIMIT  5;
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:<20s}  orders: {row[1]:<4d}  spend: ${row[2]:>10,.2f}")

    print("\n--- Top customers by ORDER COUNT (completed orders) ---")
    cur.execute("""
        SELECT c.name,
               COUNT(o.order_id)        AS order_count,
               ROUND(SUM(o.total_amount), 2) AS total_spend
        FROM   customers c
        JOIN   orders o ON c.customer_id = o.customer_id
        WHERE  o.status = 'completed'
        GROUP  BY c.customer_id
        ORDER  BY order_count DESC
        LIMIT  5;
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:<20s}  orders: {row[1]:<4d}  spend: ${row[2]:>10,.2f}")

    print("\n--- Payment method distribution ---")
    cur.execute("""
        SELECT method,
               COUNT(*)               AS txn_count,
               ROUND(SUM(amount), 2)  AS total_amount
        FROM   payments
        GROUP  BY method
        ORDER  BY txn_count DESC;
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:<16s}  txns: {row[1]:<4d}  total: ${row[2]:>10,.2f}")

    print("\n--- Orders with status breakdown ---")
    cur.execute("""
        SELECT status, COUNT(*) AS cnt
        FROM   orders
        GROUP  BY status
        ORDER  BY cnt DESC;
    """)
    for row in cur.fetchall():
        print(f"    {row[0]:<12s}  {row[1]}")

    print("=" * 60 + "\n")


def main() -> None:
    # Remove existing DB to start fresh
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    create_tables(cur)
    seed_customers(cur)
    orders = seed_orders(cur)
    seed_payments(cur, orders)

    conn.commit()

    print(f"✅  Database created at: {DB_PATH}")
    print_summary(conn)

    conn.close()


if __name__ == "__main__":
    main()

