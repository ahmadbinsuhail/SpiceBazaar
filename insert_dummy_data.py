import sqlite3, os, hashlib, random
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spiceflow.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Get all users
users = conn.execute("SELECT * FROM users").fetchall()
if not users:
    print("No users found! Please register first then run this script.")
    conn.close()
    exit()

print("Found users:")
for u in users:
    print(f"  ID:{u['id']} Email:{u['email']}")

user_id = int(input("\nEnter user ID to add dummy data for: "))

# Check spices
spices = conn.execute("SELECT * FROM spices WHERE user_id=?", (user_id,)).fetchall()
if not spices:
    print("No spices found for this user!")
    conn.close()
    exit()

customers = [
    ("Ali Hassan",      "03001234567", "Lahore"),
    ("Fatima Khan",     "03111234567", "Karachi"),
    ("Usman Malik",     "03211234567", "Islamabad"),
    ("Ayesha Raza",     "03311234567", "Faisalabad"),
    ("Bilal Ahmed",     "03411234567", "Multan"),
    ("Sara Qureshi",    "03501234567", "Lahore"),
    ("Hamza Sheikh",    "03601234567", "Rawalpindi"),
    ("Zara Hussain",    "03701234567", "Sialkot"),
    ("Omar Farooq",     "03211111111", "Gujranwala"),
    ("Nida Butt",       "03111111111", "Lahore"),
    ("Tariq Jameel",    "03001111111", "Karachi"),
    ("Sana Mirza",      "03311111111", "Peshawar"),
    ("Kamran Akbar",    "03451234567", "Lahore"),
    ("Hina Shahid",     "03211234568", "Karachi"),
    ("Zubair Iqbal",    "03331234567", "Islamabad"),
]
salesmen  = ["Ahmed Raza", "Zain Ali", "Hassan Butt", "Imran Shah"]
statuses  = ["Delivered","Delivered","Delivered","Delivered","Dispatched","Packing","Pending"]
dates = [
    "2026-04-02 10:15:00","2026-04-05 11:30:00","2026-04-09 14:20:00",
    "2026-04-14 09:45:00","2026-04-19 16:10:00","2026-04-24 13:00:00",
    "2026-05-03 10:00:00","2026-05-08 13:25:00","2026-05-13 15:40:00",
    "2026-05-18 11:55:00","2026-05-23 14:30:00","2026-05-28 09:10:00",
    "2026-06-01 09:20:00","2026-06-03 12:45:00","2026-06-05 15:30:00",
]

count = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
inserted = 0

for i, date in enumerate(dates):
    cust    = customers[i % len(customers)]
    salesman = salesmen[i % len(salesmen)]
    status  = statuses[i % len(statuses)]
    count  += 1
    order_num = f"#ORD-U{user_id}-{9900 + count}"

    chosen = random.sample(list(spices), min(random.randint(2,4), len(spices)))
    total  = 0
    items  = []
    for sp in chosen:
        q20 = random.randint(1, 8)
        q50 = random.randint(0, 4)
        total += q20 * 20 + q50 * 50
        items.append((sp["id"], q20, q50))

    conn.execute("""INSERT INTO orders
        (user_id,order_number,customer_name,phone,city,salesman,total_amount,status,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, order_num, cust[0], cust[1], cust[2], salesman, total, status, date))
    oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for spice_id, q20, q50 in items:
        conn.execute("INSERT INTO order_items (order_id,spice_id,qty_20,qty_50) VALUES (?,?,?,?)",
                     (oid, spice_id, q20, q50))
    inserted += 1

conn.commit()
conn.close()
print(f"\n✅ Done! Inserted {inserted} orders for Apr, May, Jun into your database.")
print("Restart your Flask app and refresh the dashboard.")
