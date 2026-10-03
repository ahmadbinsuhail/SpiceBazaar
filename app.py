from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, session, flash, Response
)
import sqlite3
import os
import hashlib
import csv
import io
import random
from datetime import datetime, timedelta
from functools import wraps


#  APP SETUP 
app = Flask(__name__)
app.secret_key = "satrang_spiceflow_pk_2024_secret"

# Path to the SQLite database file (same folder as this script)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spiceflow.db")

# Month number → short name (used for charts)
MONTH_NAMES = {
    '01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr',
    '05': 'May', '06': 'Jun', '07': 'Jul', '08': 'Aug',
    '09': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec'
}


# DATABASE HELPERS 

def get_db():
    """Open a connection to the database and return it.
    Using row_factory=sqlite3.Row lets us access columns by name (e.g. row['name'])."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(plain_text):
    """Hash a password using SHA-256 before storing it."""
    return hashlib.sha256(plain_text.encode()).hexdigest()


def get_current_time():
    """Return the current date and time as a formatted string."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


#  JINJA TEMPLATE FILTER 
@app.template_filter('pkt')
def format_pakistan_time(datetime_string):
    """Convert a UTC datetime string to Pakistan Standard Time (UTC+5)
    and return it in a readable format like '09 Jun 2026, 03:30 PM'."""
    if not datetime_string:
        return ''

    # Only take the first 19 characters (YYYY-MM-DD HH:MM:SS)
    clean = str(datetime_string).strip()[:19]
    parsed = None

    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            parsed = datetime.strptime(clean, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return clean[:16]  # Return as-is if we can't parse it

    pakistan_time = parsed + timedelta(hours=5)
    return pakistan_time.strftime('%d %b %Y, %I:%M %p')


#  AUTH HELPER

def login_required(route_function):
    """Decorator: redirect to login page if the user is not logged in.
    Wrap any route with @login_required to protect it."""
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access Spice Bazaar.', 'error')
            return redirect(url_for('login'))
        return route_function(*args, **kwargs)
    return wrapper


def current_user_id():
    """Return the ID of the currently logged-in user from the session."""
    return session['user_id']


def generate_order_number():
    """Generate the next order number for the current user.
    Format: #ORD-U{user_id}-{sequential_number}"""
    conn = get_db()
    user_id = current_user_id()
    total_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return f"#ORD-U{user_id}-{9900 + total_orders + 1}"


#  DATABASE SETUP 

def init_db():
    """Create all database tables if they don't already exist.
    Safe to run every time the app starts."""
    conn = get_db()
    c = conn.cursor()

    # Store user accounts
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            email          TEXT UNIQUE NOT NULL,
            password_hash  TEXT NOT NULL,
            full_name      TEXT,
            phone          TEXT,
            role           TEXT DEFAULT 'Staff',
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Each user has their own spice products
    c.execute("""
        CREATE TABLE IF NOT EXISTS spices (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            name      TEXT NOT NULL,
            category  TEXT,
            img_url   TEXT,
            stock_20  INTEGER DEFAULT 0,
            stock_50  INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Each user has their own orders
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            order_number   TEXT UNIQUE,
            customer_name  TEXT,
            phone          TEXT,
            city           TEXT,
            salesman       TEXT,
            total_amount   REAL DEFAULT 0,
            status         TEXT DEFAULT 'Pending',
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Each order contains one or more spice items
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id  INTEGER,
            spice_id  INTEGER,
            qty_20    INTEGER DEFAULT 0,
            qty_50    INTEGER DEFAULT 0,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(spice_id) REFERENCES spices(id)
        )
    """)

    # History log of all stock changes (restocks and sales)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stock_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            spice_id    INTEGER,
            spice_name  TEXT,
            packet_type TEXT,
            adjustment  INTEGER,
            action      TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(spice_id) REFERENCES spices(id)
        )
    """)

    conn.commit()
    conn.close()


#  STARTER SPICE DATA 

# Default spices every new user gets when they first sign up
STARTER_SPICES = [
    ("Lal Mirch (Red Chili)",     "Hot & Spicy",  "https://lh3.googleusercontent.com/aida-public/AB6AXuBFOCFh1ax1pTd9xmgrS5keeMDfqxyuDaizFOpMyYt0gKyMZbPPH49pPwk-AouubAkr9CQQi_i4Cnhd-9X2zn2L8bO7FdCYlGP0nA6YZvxKpYHn_IHdh6jeRZF5nyS1279sOc25PeK02FfHpaaSdaDpoyyuY7vcBC6g4aCd7PZOtfr3YwQ8r2xeVpXnXyT8UsU9ZgI6D1YBF9G48B9wGruFLkmixI7Q_F9zPOssNHmp1MDb9S-QIIolTIeXPDw0OWnU81Otn9Oa3YDh", 50, 30),
    ("Haldi (Turmeric)",          "Essentials",   "https://lh3.googleusercontent.com/aida-public/AB6AXuBTy77q_WZW1jUHmzXl3H6Y6R2MbEmen0nhsnQYzROSfk4VK4NSdPL8-tmrwbzFZ3ebMHepmkMblIqfTVZsJNC--AqWL-0kg7RR_2DhreYYCj6xM2T1JqSXdSHft94We3JQQoh14dK3eWF2FgVUGiTkC-1_i2vJ6J_5uydTkquRC_oNR6-InPCjBDLJUKqevaJIu-LtDy4SjxSD76HLEINRBfHzqYztOYrWe46eFmaAZPrhBQjFEEMpNqIJThZ659w9aQTINjTUvPug", 12, 4),
    ("Zeera (Cumin)",             "Seeds",        "https://lh3.googleusercontent.com/aida-public/AB6AXuC1Y-gfX_PLPb8xAZZpdG0SFAGEaj8gSp-ksLQ9ZXMR0KHUdrdkCxUeJM_v1sqQD071FMxe3vHxlEcICeDOzMnZ78_NtSk3xZBlrKxtwQv7wfwmiAfX-04Um5BZBJB4YVuRvCOOWCOu1mKh_YJgDJiznup9Yy-PS7XTexXL0HJqbq0SKWLa_nTCShkTFYWwaMzt2J9Txcey68Hn9SnrncQiylulNMthHXkowjwZzflMcZNhO03v4_kfBbuDx5GVRqXwY29_jDjoG6jO", 124, 88),
    ("Dhaniya (Coriander)",       "Seeds",        "https://lh3.googleusercontent.com/aida-public/AB6AXuCL9ZY2TcdxkIlu92ZlrQ41RmC-uS1X78IJegWYzAPn3m_pdO4y7iCw0zjXwy6plgCB9WhZnh7BWRQpHGp_vAn_H2DKSIL_MXy0Pkus4Be9v8Y7b4TYcWyB9pKbLJCW4RQg9t4Ptr-vEXFNQ6nEisvdEeXZ0w2HJ1f_gXPXkFgbiM81V1_rHLY0cc_mWjnqh8bLwqbsVz_pJIZEeH6qaAaQMLs9zn6KY0yl6mTFCZArSo59UOE3dEXrITChs7-jPDs0ZFd3NGBR_xHG", 80, 45),
    ("Garam Masala",              "Blends",       "https://lh3.googleusercontent.com/aida-public/AB6AXuBFOCFh1ax1pTd9xmgrS5keeMDfqxyuDaizFOpMyYt0gKyMZbPPH49pPwk-AouubAkr9CQQi_i4Cnhd-9X2zn2L8bO7FdCYlGP0nA6YZvxKpYHn_IHdh6jeRZF5nyS1279sOc25PeK02FfHpaaSdaDpoyyuY7vcBC6g4aCd7PZOtfr3YwQ8r2xeVpXnXyT8UsU9ZgI6D1YBF9G48B9wGruFLkmixI7Q_F9zPOssNHmp1MDb9S-QIIolTIeXPDw0OWnU81Otn9Oa3YDh", 35, 20),
    ("Kali Mirch (Black Pepper)", "Spices",       "https://lh3.googleusercontent.com/aida-public/AB6AXuCfMmqtp2TZZpD0c3NO3BUZ-GPVxF1br1ro4uegqRnfiZQz3znhxr9BRR1E9zeLI7B4TpMi6MfKLhiRfjRN_beYwlgrvL1YWDqdjKIzKIWWH8K1MWoTntBU70GzaUXJ4svKfvcQfLf-mPmxDo6DVIVzGPTHxS6ic2MqKDh_Dgz7Z8kWDdfb2YlmGJ3tbrJNab6lLHHHvjZNfkqH3hIFLJtXtnYX0GgB8ytBcgpDxnBkD9wMWsA6N9f9AP4kP2O0ip4rI2vf6VmV4yhX", 2, 110),
    ("Kashmiri Mirch",            "Hot & Spicy",  "https://lh3.googleusercontent.com/aida-public/AB6AXuCmJtb_oTMD92yJ_E4tD1GXdTpSPS1TOMCA4nuxfmrcp9NH_dRPTHh7uA6z7mQKDcvBnGlzJsOaCuru-thTk8ndljADSNAi2nHjQHnhqSuQiWn3xwmgZNQqxn0Brhi0JxXIHVzAeBdki9u2FvxQe3n_onGKyop1JFjbhQcqbk1qhDs5SY0H6hTYWv1lS1kzTWxZVr0BboXSu5lu0TJEmLaR6RxXPNXdOfpDmwVFwfvHI2fMjNWiSiP0RSDvzzMxrPFMwqE6pb8EQeTU_c", 8, 45),
    ("Hari Elaichi (Cardamom)",   "Aromatics",    "https://lh3.googleusercontent.com/aida-public/AB6AXuB5TvX8Ju3gfo6EwEV6mnZfB96ewAPf83cEsOS-t4H9hZAJcUwHus2w5rhMr8TjAoWLU92edCnxyhxTkKjpRlR2jPKN3cyl3mELmtaSM-TpAsO5RshZIL0SYUV_KkWPp5xibsv-8KruJzhZ60-I0r3GoesVY5A3ptNCpzMlObE1OGANuf3MHF5M6qG27RR9t6xKT_DL9WFVuWNEyypGYuRsR6waPIe-G_O1UapdEAuXv4ILSn3XTqcD84plKBXUE_ReNA_4_nGFB0Lk", 56, 32),
]


def seed_spices_for_user(conn, user_id):
    """Insert the default 8 spices into the database for a new user."""
    rows = [(user_id,) + spice for spice in STARTER_SPICES]
    conn.executemany(
        "INSERT INTO spices (user_id, name, category, img_url, stock_20, stock_50) VALUES (?,?,?,?,?,?)",
        rows
    )


#  DEMO ACCOUNT SETUP 

def seed_demo_account():
    """Create the demo account (spicebazaar@gmail.com) with sample orders.
    Only runs once — skipped if the account already exists."""
    conn = get_db()

    # Don't create it again if it already exists
    already_exists = conn.execute(
        "SELECT id FROM users WHERE email=?", ('spicebazaar@gmail.com',)
    ).fetchone()
    if already_exists:
        conn.close()
        return

    # Create the demo user
    conn.execute(
        "INSERT INTO users (email, password_hash, full_name, phone, role) VALUES (?,?,?,?,?)",
        ('spicebazaar@gmail.com', hash_password('bazaar123'), 'Spice Bazaar', '03001234567', 'Admin')
    )
    conn.commit()

    demo_user = conn.execute(
        "SELECT * FROM users WHERE email=?", ('spicebazaar@gmail.com',)
    ).fetchone()
    user_id = demo_user['id']

    # Give the demo user spices
    seed_spices_for_user(conn, user_id)
    conn.commit()

    # Sample customers for demo orders
    sample_customers = [
        ("Ali Hassan",     "03001234567", "Lahore"),
        ("Fatima Khan",    "03111234567", "Karachi"),
        ("Usman Malik",    "03211234567", "Islamabad"),
        ("Ayesha Raza",    "03311234567", "Faisalabad"),
        ("Bilal Ahmed",    "03411234567", "Multan"),
        ("Sara Qureshi",   "03501234567", "Lahore"),
        ("Hamza Sheikh",   "03601234567", "Rawalpindi"),
        ("Zara Hussain",   "03701234567", "Sialkot"),
        ("Omar Farooq",    "03211111111", "Gujranwala"),
        ("Nida Butt",      "03111111111", "Lahore"),
        ("Tariq Jameel",   "03001111111", "Karachi"),
        ("Sana Mirza",     "03311111111", "Peshawar"),
        ("Kamran Akbar",   "03451234567", "Lahore"),
        ("Hina Shahid",    "03211234568", "Karachi"),
        ("Zubair Iqbal",   "03331234567", "Islamabad"),
    ]
    salesmen = ["Ahmed Raza", "Zain Ali", "Hassan Butt", "Imran Shah"]
    statuses = ["Delivered", "Delivered", "Delivered", "Delivered", "Dispatched", "Packing", "Pending"]
    order_dates = [
        "2026-04-02 10:15:00", "2026-04-05 11:30:00", "2026-04-09 14:20:00",
        "2026-04-14 09:45:00", "2026-04-19 16:10:00", "2026-04-24 13:00:00",
        "2026-05-03 10:00:00", "2026-05-08 13:25:00", "2026-05-13 15:40:00",
        "2026-05-18 11:55:00", "2026-05-23 14:30:00", "2026-05-28 09:10:00",
        "2026-06-01 09:20:00", "2026-06-03 12:45:00", "2026-06-05 15:30:00",
    ]

    all_spices = conn.execute("SELECT * FROM spices WHERE user_id=?", (user_id,)).fetchall()

    for i, order_date in enumerate(order_dates):
        customer = sample_customers[i % len(sample_customers)]
        order_number = f"#ORD-U{user_id}-{9900 + i + 1}"
        salesman = salesmen[i % len(salesmen)]
        status = statuses[i % len(statuses)]

        # Pick 2–4 random spices for this order
        chosen_spices = random.sample(list(all_spices), min(random.randint(2, 4), len(all_spices)))
        total = sum(random.randint(1, 8) * 20 + random.randint(0, 4) * 50 for _ in chosen_spices)

        conn.execute(
            """INSERT INTO orders
               (user_id, order_number, customer_name, phone, city, salesman, total_amount, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, order_number, customer[0], customer[1], customer[2], salesman, total, status, order_date)
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert line items for this order
        for spice in chosen_spices:
            conn.execute(
                "INSERT INTO order_items (order_id, spice_id, qty_20, qty_50) VALUES (?,?,?,?)",
                (order_id, spice['id'], random.randint(1, 8), random.randint(0, 4))
            )

    conn.commit()
    conn.close()
    print("✅ Demo account created: spicebazaar@gmail.com / bazaar123")


# Run setup once when the app starts
init_db()
seed_demo_account()



# AUTH ROUTES 

@app.route("/login", methods=["GET", "POST"])
def login():
    """Show the login page (GET) or process the login form (POST)."""
    # If already logged in, go straight to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND password_hash=?",
            (email, hash_password(password))
        ).fetchone()
        conn.close()

        if user:
            # Save user info in the session so we know who's logged in
            session['user_id']   = user['id']
            session['email']     = user['email']
            session['full_name'] = user['full_name'] or user['email']
            session['role']      = user['role']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
            return redirect(url_for('login'))

    return render_template("login.html", signup=False)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Show the signup page (GET) or create a new account (POST)."""
    if request.method == "POST":
        email     = request.form.get("email", "").strip().lower()
        password  = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone     = request.form.get("phone", "").strip()
        role      = request.form.get("role", "Staff") or "Staff"

        if not email or not password:
            flash('Email and password are required.', 'error')
            return render_template("login.html", signup=True)

        conn = get_db()
        try:
            # Check if this email is already registered
            existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                conn.close()
                flash('Email already registered.', 'error')
                return render_template("login.html", signup=True)

            # Create the new user
            conn.execute(
                "INSERT INTO users (email, password_hash, full_name, phone, role) VALUES (?,?,?,?,?)",
                (email, hash_password(password), full_name, phone, role)
            )
            conn.commit()

            new_user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

            # Give this new user their starter spice inventory
            seed_spices_for_user(conn, new_user['id'])
            conn.commit()
            conn.close()

            # Log them in automatically
            session['user_id']   = new_user['id']
            session['email']     = new_user['email']
            session['full_name'] = new_user['full_name'] or new_user['email']
            session['role']      = new_user['role']

            flash(f"Welcome, {new_user['full_name'] or email}! Your inventory is ready.", 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            conn.close()
            flash(f'Could not create account: {str(e)}', 'error')
            return render_template("login.html", signup=True)

    return render_template("login.html", signup=True)


@app.route("/logout")
def logout():
    """Clear the session and send the user back to the login page."""
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))



# MAIN PAGES

@app.route("/")
def home():
    """The root URL just redirects to the dashboard."""
    return redirect(url_for('dashboard'))


# ── DASHBOARD 

@app.route("/dashboard")
@login_required
def dashboard():
    """Main dashboard — shows key stats, recent orders, and chart data."""
    conn = get_db()
    user_id = current_user_id()

    # ── Summary numbers 
    
    total_orders   = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
    total_revenue  = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
    pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Pending'", (user_id,)).fetchone()[0]
    packing_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Packing'", (user_id,)).fetchone()[0]
    dispatched     = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Dispatched'", (user_id,)).fetchone()[0]
    delivered      = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Delivered'", (user_id,)).fetchone()[0]
    total_spices   = conn.execute("SELECT COUNT(*) FROM spices WHERE user_id=?", (user_id,)).fetchone()[0]
    low_stock      = conn.execute("SELECT COUNT(*) FROM spices WHERE user_id=? AND (stock_20 < 10 OR stock_50 < 10)", (user_id,)).fetchone()[0]

    # Calculate stock fill percentage (for the stock bar on the dashboard)
    total_units = conn.execute("SELECT COALESCE(SUM(stock_20 + stock_50),0) FROM spices WHERE user_id=?", (user_id,)).fetchone()[0]
    max_units   = total_spices * 200
    stock_pct   = int((total_units / max_units) * 100) if max_units else 0

    # ── Recent 5 orders 
    
    
    raw_recent = conn.execute(
        """SELECT order_number, customer_name, city, total_amount, status, created_at
           FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5""",
        (user_id,)
    ).fetchall()

    recent_orders = [
        {
            'order_number':  row['order_number'],
            'customer_name': row['customer_name'],
            'city':          row['city'],
            'total_amount':  row['total_amount'],
            'status':        row['status'],
            'display_time':  row['created_at'][:16] if row['created_at'] else '',
        }
        for row in raw_recent
    ]

    # ── Top 5 spices by revenue (for the bar chart) 
    spice_revenue_rows = conn.execute("""
        SELECT s.name, COALESCE(SUM(oi.qty_20 * 20 + oi.qty_50 * 50), 0) AS rev
        FROM spices s
        LEFT JOIN order_items oi ON s.id = oi.spice_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.user_id = ?
        WHERE s.user_id = ?
        GROUP BY s.id ORDER BY rev DESC LIMIT 5
    """, (user_id, user_id)).fetchall()

    max_spice_rev = max((row['rev'] for row in spice_revenue_rows), default=1) or 1
    spice_revenue = [
        {'name': row['name'], 'rev': row['rev'], 'pct': int((row['rev'] / max_spice_rev) * 100)}
        for row in spice_revenue_rows
    ]

    # ── Monthly revenue for the last 6 months 
    monthly_rows = conn.execute("""
        SELECT substr(created_at, 1, 7) AS year_month,
               COALESCE(SUM(total_amount), 0) AS rev
        FROM orders WHERE user_id=?
        GROUP BY substr(created_at, 1, 7)
        ORDER BY substr(created_at, 1, 7) DESC LIMIT 6
    """, (user_id,)).fetchall()

    monthly_rows  = list(reversed(monthly_rows))  # Show oldest → newest
    max_monthly   = max((row['rev'] for row in monthly_rows), default=1) or 1
    monthly_data  = [
        {
            'month': MONTH_NAMES.get(row['year_month'][5:7], row['year_month']),
            'rev':   row['rev'],
            'pct':   int((row['rev'] / max_monthly) * 100)
        }
        for row in monthly_rows
    ]

    conn.close()
    return render_template("dashboard.html",
        total_revenue=f"Rs. {total_revenue:,.0f}",
        total_revenue_raw=total_revenue,
        total_orders=total_orders,
        stock_pct=f"{stock_pct}%",
        pending_orders=pending_orders,
        packing_orders=packing_orders,
        dispatched=dispatched,
        delivered=delivered,
        low_stock=low_stock,
        recent_orders=recent_orders,
        spice_revenue=spice_revenue,
        monthly_data=monthly_data,
    )


# ── INVENTORY

@app.route("/inventory")
@login_required
def inventory():
    """Show all spices, their stock levels, and a recent stock activity log."""
    conn = get_db()
    user_id = current_user_id()

    # If somehow the user has no spices, give them the starter ones
    spice_count = conn.execute("SELECT COUNT(*) FROM spices WHERE user_id=?", (user_id,)).fetchone()[0]
    if spice_count == 0:
        seed_spices_for_user(conn, user_id)
        conn.commit()

    spices = conn.execute(
        "SELECT * FROM spices WHERE user_id=? ORDER BY id", (user_id,)
    ).fetchall()

    # Last 10 stock changes (restocks and sales)
    raw_log = conn.execute(
        """SELECT spice_name, packet_type, adjustment, action, created_at
           FROM stock_log WHERE user_id=? ORDER BY id DESC LIMIT 10""",
        (user_id,)
    ).fetchall()

    # Convert log timestamps to Pakistan time
    stock_log = []
    for row in raw_log:
        entry = dict(row)
        try:
            dt = datetime.strptime(entry['created_at'][:19], '%Y-%m-%d %H:%M:%S')
            entry['created_at'] = (dt + timedelta(hours=5)).strftime('%Y-%m-%d %H:%M')
        except ValueError:
            pass  # Keep original if it can't be parsed
        stock_log.append(entry)

    last_restock = conn.execute(
        """SELECT spice_name, created_at FROM stock_log
           WHERE user_id=? AND action='Restocked' ORDER BY id DESC LIMIT 1""",
        (user_id,)
    ).fetchone()

    total_variants  = conn.execute("SELECT COUNT(*)*2 FROM spices WHERE user_id=?", (user_id,)).fetchone()[0]
    low_stock_count = conn.execute(
        "SELECT COUNT(*) FROM spices WHERE user_id=? AND (stock_20 < 10 OR stock_50 < 10)", (user_id,)
    ).fetchone()[0]

    conn.close()
    return render_template("inventory.html",
        spices=spices,
        stock_log=stock_log,
        last_restock=last_restock,
        total_variants=total_variants,
        low_stock_count=low_stock_count,
    )


@app.route("/inventory/restock", methods=["POST"])
@login_required
def restock():
    """Add stock to a spice. Called from the restock form in inventory."""
    spice_id    = request.form.get("spice_id")
    packet_type = request.form.get("packet_type")  # "20" or "50"
    qty         = int(request.form.get("qty", 0))

    if qty <= 0:
        return redirect(url_for("inventory"))

    conn = get_db()
    user_id = current_user_id()

    # Make sure this spice belongs to the current user before updating
    spice = conn.execute(
        "SELECT * FROM spices WHERE id=? AND user_id=?", (spice_id, user_id)
    ).fetchone()

    if spice:
        if packet_type == "20":
            conn.execute(
                "UPDATE spices SET stock_20 = stock_20 + ? WHERE id=? AND user_id=?",
                (qty, spice_id, user_id)
            )
        else:
            conn.execute(
                "UPDATE spices SET stock_50 = stock_50 + ? WHERE id=? AND user_id=?",
                (qty, spice_id, user_id)
            )

        # Log this restock action
        conn.execute(
            "INSERT INTO stock_log (user_id, spice_id, spice_name, packet_type, adjustment, action) VALUES (?,?,?,?,?,?)",
            (user_id, spice_id, spice["name"], f"Rs.{packet_type}", qty, "Restocked")
        )
        conn.commit()

    conn.close()
    return redirect(url_for("inventory"))


@app.route("/inventory/add", methods=["POST"])
@login_required
def add_spice():
    """Add a brand new spice to the inventory."""
    name     = request.form.get("name")
    category = request.form.get("category")
    stock_20 = int(request.form.get("stock_20", 0))
    stock_50 = int(request.form.get("stock_50", 0))

    conn = get_db()
    conn.execute(
        "INSERT INTO spices (user_id, name, category, stock_20, stock_50) VALUES (?,?,?,?,?)",
        (current_user_id(), name, category, stock_20, stock_50)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("inventory"))


# ── ORDERS 

@app.route("/orders")
@login_required
def orders():
    """Show all orders for the current user, newest first."""
    conn = get_db()
    user_id = current_user_id()

    raw_orders = conn.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,)
    ).fetchall()

    # Convert to dicts and add a formatted display time
    order_list = []
    for row in raw_orders:
        order = dict(row)
        order['display_time'] = order['created_at'][:16] if order.get('created_at') else ''
        order_list.append(order)

    conn.close()
    return render_template("order.html", orders=order_list)


@app.route("/orders/update-status", methods=["POST"])
@login_required
def update_status():
    """Update the status of an order (e.g. Pending → Packing → Dispatched)."""
    order_id = request.form.get("order_id")
    status   = request.form.get("status")

    conn = get_db()
    conn.execute(
        "UPDATE orders SET status=? WHERE id=? AND user_id=?",
        (status, order_id, current_user_id())
    )
    conn.commit()
    conn.close()
    return redirect(url_for("orders"))


@app.route("/orders/delete", methods=["POST"])
@login_required
def delete_order():
    """Permanently delete an order and all its items."""
    order_id = request.form.get("order_id")
    conn = get_db()
    user_id = current_user_id()

    # Verify the order belongs to this user before deleting
    order = conn.execute(
        "SELECT id FROM orders WHERE id=? AND user_id=?", (order_id, user_id)
    ).fetchone()

    if order:
        conn.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
        conn.commit()

    conn.close()
    return redirect(url_for("orders"))


# ── NEW ORDER 

@app.route("/new-order")
@login_required
def new_order():
    """Show the 'create new order' form with the list of available spices."""
    conn = get_db()
    user_id = current_user_id()

    # Auto-seed spices if this user somehow has none
    spice_count = conn.execute("SELECT COUNT(*) FROM spices WHERE user_id=?", (user_id,)).fetchone()[0]
    if spice_count == 0:
        seed_spices_for_user(conn, user_id)
        conn.commit()

    spices = conn.execute(
        "SELECT * FROM spices WHERE user_id=? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return render_template("new-order.html", spices=spices)


@app.route("/new-order/submit", methods=["POST"])
@login_required
def submit_order():
    """Process the new order form and save it to the database."""
    customer = request.form.get("customer_name", "").strip()
    phone    = request.form.get("phone", "").strip()
    city     = request.form.get("city", "").strip()
    salesman = request.form.get("salesman", "").strip()

    # Don't save if required fields are missing
    if not customer or not phone or not city:
        return redirect(url_for("new_order"))

    conn = get_db()
    user_id = current_user_id()
    spices  = conn.execute("SELECT * FROM spices WHERE user_id=?", (user_id,)).fetchall()

    # Collect the quantities entered for each spice in the form
    total        = 0
    order_items  = []

    for spice in spices:
        qty_20 = int(request.form.get(f"qty_20_{spice['id']}", 0))
        qty_50 = int(request.form.get(f"qty_50_{spice['id']}", 0))

        if qty_20 > 0 or qty_50 > 0:
            total += qty_20 * 20 + qty_50 * 50
            order_items.append((spice["id"], qty_20, qty_50))

    # Don't save an empty order
    if not order_items:
        conn.close()
        return redirect(url_for("new_order"))

    # Save the order
    order_number = generate_order_number()
    conn.execute(
        """INSERT INTO orders
           (user_id, order_number, customer_name, phone, city, salesman, total_amount, status, created_at)
           VALUES (?,?,?,?,?,?,?,'Pending',?)""",
        (user_id, order_number, customer, phone, city, salesman, total, get_current_time())
    )
    order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Save each spice line item and reduce stock
    for spice_id, qty_20, qty_50 in order_items:
        conn.execute(
            "INSERT INTO order_items (order_id, spice_id, qty_20, qty_50) VALUES (?,?,?,?)",
            (order_id, spice_id, qty_20, qty_50)
        )

        # Reduce stock (minimum 0 — never go negative)
        conn.execute(
            "UPDATE spices SET stock_20 = MAX(0, stock_20 - ?) WHERE id=? AND user_id=?",
            (qty_20, spice_id, user_id)
        )
        conn.execute(
            "UPDATE spices SET stock_50 = MAX(0, stock_50 - ?) WHERE id=? AND user_id=?",
            (qty_50, spice_id, user_id)
        )

        # Log the sale in stock history
        spice = conn.execute("SELECT name FROM spices WHERE id=?", (spice_id,)).fetchone()
        if qty_20 > 0:
            conn.execute(
                "INSERT INTO stock_log (user_id, spice_id, spice_name, packet_type, adjustment, action) VALUES (?,?,?,?,?,?)",
                (user_id, spice_id, spice["name"], "Rs.20", -qty_20, "Sale")
            )
        if qty_50 > 0:
            conn.execute(
                "INSERT INTO stock_log (user_id, spice_id, spice_name, packet_type, adjustment, action) VALUES (?,?,?,?,?,?)",
                (user_id, spice_id, spice["name"], "Rs.50", -qty_50, "Sale")
            )

    conn.commit()
    conn.close()
    return redirect(url_for("orders"))


# ── ANALYSIS 

@app.route("/analysis")
@login_required
def analysis():
    """Sales analysis page — charts, stats, top spices, city breakdowns, etc."""
    conn = get_db()
    user_id = current_user_id()

    # ── Overall totals 
    total_revenue = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
    total_orders  = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
    delivered     = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Delivered'", (user_id,)).fetchone()[0]
    pending       = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='Pending'", (user_id,)).fetchone()[0]

    # ── Top 6 spices by revenue 
    top_spices_rows = conn.execute("""
        SELECT s.name,
               COALESCE(SUM(oi.qty_20 + oi.qty_50), 0)          AS total_sold,
               COALESCE(SUM(oi.qty_20 * 20 + oi.qty_50 * 50), 0) AS rev
        FROM spices s
        LEFT JOIN order_items oi ON s.id = oi.spice_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.user_id = ?
        WHERE s.user_id = ?
        GROUP BY s.id ORDER BY rev DESC LIMIT 6
    """, (user_id, user_id)).fetchall()

    max_rev = max((row['rev'] for row in top_spices_rows), default=1) or 1
    top_spices_data = [
        {'name': row['name'], 'total_sold': row['total_sold'], 'rev': row['rev'],
         'pct': int((row['rev'] / max_rev) * 100)}
        for row in top_spices_rows
    ]

    # ── Revenue by city 
    city_revenue = conn.execute("""
        SELECT city, COALESCE(SUM(total_amount),0) AS rev, COUNT(*) AS orders
        FROM orders WHERE user_id=? GROUP BY city ORDER BY rev DESC LIMIT 5
    """, (user_id,)).fetchall()

    # ── Revenue by salesman 
    salesmen = conn.execute("""
        SELECT salesman, COALESCE(SUM(total_amount),0) AS rev, COUNT(*) AS orders
        FROM orders
        WHERE user_id=? AND salesman != '' AND salesman IS NOT NULL
        GROUP BY salesman ORDER BY rev DESC LIMIT 5
    """, (user_id,)).fetchall()

    # ── Monthly revenue (last 6 months) 
    monthly_rows = conn.execute("""
        SELECT substr(created_at, 1, 7) AS year_month,
               COALESCE(SUM(total_amount), 0) AS rev
        FROM orders WHERE user_id=?
        GROUP BY substr(created_at, 1, 7)
        ORDER BY substr(created_at, 1, 7) DESC LIMIT 6
    """, (user_id,)).fetchall()

    monthly_rows = list(reversed(monthly_rows))
    max_monthly  = max((row['rev'] for row in monthly_rows), default=1) or 1
    monthly_data = [
        {'month': MONTH_NAMES.get(row['year_month'][5:7], row['year_month']),
         'rev': row['rev'],
         'pct': int((row['rev'] / max_monthly) * 100)}
        for row in monthly_rows
    ]

    # ── Rs.20 vs Rs.50 packet split 
    qty20_total = conn.execute("""
        SELECT COALESCE(SUM(oi.qty_20), 0)
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.user_id=?
    """, (user_id,)).fetchone()[0]

    qty50_total = conn.execute("""
        SELECT COALESCE(SUM(oi.qty_50), 0)
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.user_id=?
    """, (user_id,)).fetchone()[0]

    total_qty = qty20_total + qty50_total or 1
    pct_20    = int((qty20_total / total_qty) * 100)
    pct_50    = 100 - pct_20

    # ── Weekly revenue (last 7 days) 
    weekly_rows = conn.execute("""
        SELECT strftime('%d/%m', created_at) AS day,
               strftime('%Y-%m-%d', created_at) AS full_date,
               COALESCE(SUM(total_amount), 0) AS rev
        FROM orders
        WHERE user_id=? AND date(created_at) >= date('now', '-7 days')
        GROUP BY strftime('%Y-%m-%d', created_at)
        ORDER BY full_date ASC
    """, (user_id,)).fetchall()

    max_weekly = max((row['rev'] for row in weekly_rows), default=1) or 1
    weekly_data = [
        {'day': row['day'], 'rev': row['rev'], 'pct': int((row['rev'] / max_weekly) * 100)}
        for row in weekly_rows
    ]

    # ── Weekly packet counts 
    weekly_pkt = conn.execute("""
        SELECT COALESCE(SUM(oi.qty_20), 0) AS w20,
               COALESCE(SUM(oi.qty_50), 0) AS w50
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.user_id=? AND date(o.created_at) >= date('now', '-7 days')
    """, (user_id,)).fetchone()

    weekly_20 = weekly_pkt['w20'] if weekly_pkt else 0
    weekly_50 = weekly_pkt['w50'] if weekly_pkt else 0

    # ── Top spices this week                       
    weekly_spice_rows = conn.execute("""
        SELECT s.name,
               COALESCE(SUM(oi.qty_20 + oi.qty_50), 0)          AS total_sold,
               COALESCE(SUM(oi.qty_20 * 20 + oi.qty_50 * 50), 0) AS rev
        FROM spices s
        LEFT JOIN order_items oi ON s.id = oi.spice_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.user_id = ?
        WHERE s.user_id = ?
        GROUP BY s.id ORDER BY rev DESC LIMIT 6
    """, (user_id, user_id)).fetchall()

    max_w_rev    = max((row['rev'] for row in weekly_spice_rows), default=1) or 1
    weekly_spices = [
        {'name': row['name'], 'total_sold': row['total_sold'], 'rev': row['rev'],
         'pct': int((row['rev'] / max_w_rev) * 100)}
        for row in weekly_spice_rows
    ]

    # ── Per-spice packet breakdown 
    packet_rows = conn.execute("""
        SELECT s.name, s.category,
               COALESCE(SUM(oi.qty_20), 0) AS qty_20,
               COALESCE(SUM(oi.qty_50), 0) AS qty_50
        FROM spices s
        LEFT JOIN order_items oi ON s.id = oi.spice_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.user_id = ?
        WHERE s.user_id = ?
        GROUP BY s.id
        ORDER BY (COALESCE(SUM(oi.qty_20), 0) + COALESCE(SUM(oi.qty_50), 0)) DESC
    """, (user_id, user_id)).fetchall()

    max_pkt = max((row['qty_20'] + row['qty_50'] for row in packet_rows), default=1) or 1
    packet_breakdown = [
        {
            'name':     row['name'],
            'category': row['category'],
            'qty_20':   row['qty_20'],
            'qty_50':   row['qty_50'],
            'pct_20':   int((row['qty_20'] / max_pkt) * 100),
            'pct_50':   int((row['qty_50'] / max_pkt) * 100),
        }
        for row in packet_rows
    ]

    conn.close()
    return render_template("analysis.html",
        total_revenue=f"Rs. {total_revenue:,.0f}",
        total_revenue_raw=total_revenue,
        total_orders=total_orders,
        delivered=delivered,
        pending=pending,
        top_spices_data=top_spices_data,
        city_revenue=city_revenue,
        salesmen=salesmen,
        monthly_data=monthly_data,
        pct_20=pct_20,
        pct_50=pct_50,
        rev_20=qty20_total * 20,
        rev_50=qty50_total * 50,
        qty20_total=qty20_total,
        qty50_total=qty50_total,
        weekly_data=weekly_data,
        weekly_20=weekly_20,
        weekly_50=weekly_50,
        weekly_spices=weekly_spices,
        packet_breakdown=packet_breakdown,
    )


# ── CSV EXPORT 

@app.route("/analysis/export-csv")
@login_required
def export_csv():
    """Download all data as a CSV file (orders, spice performance, city stats)."""
    conn = get_db()
    user_id = current_user_id()

    orders_data = conn.execute("""
        SELECT order_number, customer_name, phone, city, salesman,
               total_amount, status, created_at
        FROM orders WHERE user_id=? ORDER BY id DESC
    """, (user_id,)).fetchall()

    spice_data = conn.execute("""
        SELECT s.name, s.category,
               COALESCE(SUM(oi.qty_20), 0)                       AS total_20,
               COALESCE(SUM(oi.qty_50), 0)                       AS total_50,
               COALESCE(SUM(oi.qty_20 * 20 + oi.qty_50 * 50), 0) AS revenue
        FROM spices s
        LEFT JOIN order_items oi ON s.id = oi.spice_id
        LEFT JOIN orders o ON oi.order_id = o.id AND o.user_id = ?
        WHERE s.user_id = ?
        GROUP BY s.id ORDER BY revenue DESC
    """, (user_id, user_id)).fetchall()

    city_data = conn.execute("""
        SELECT city, COUNT(*) AS orders, COALESCE(SUM(total_amount), 0) AS revenue
        FROM orders WHERE user_id=? GROUP BY city ORDER BY revenue DESC
    """, (user_id,)).fetchall()

    salesmen_data = conn.execute("""
        SELECT salesman, COUNT(*) AS orders, COALESCE(SUM(total_amount), 0) AS revenue
        FROM orders
        WHERE user_id=? AND salesman != '' AND salesman IS NOT NULL
        GROUP BY salesman ORDER BY revenue DESC
    """, (user_id,)).fetchall()

    conn.close()

    # Build the CSV content in memory
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== SPICEFLOW PAKISTAN - FULL ANALYSIS REPORT ==="])
    writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
    writer.writerow([f"Account: {session.get('full_name', '')} ({session.get('email', '')})"])
    writer.writerow([])

    writer.writerow(["--- ALL ORDERS ---"])
    writer.writerow(["Order No", "Customer", "Phone", "City", "Salesman", "Amount (Rs)", "Status", "Date"])
    for o in orders_data:
        writer.writerow([o['order_number'], o['customer_name'], o['phone'],
                         o['city'], o['salesman'], o['total_amount'], o['status'], o['created_at'][:10]])
    writer.writerow([])

    writer.writerow(["--- SPICE PERFORMANCE ---"])
    writer.writerow(["Spice", "Category", "20Rs Pkts Sold", "50Rs Pkts Sold", "Revenue (Rs)"])
    for s in spice_data:
        writer.writerow([s['name'], s['category'], s['total_20'], s['total_50'], s['revenue']])
    writer.writerow([])

    writer.writerow(["--- CITY-WISE REVENUE ---"])
    writer.writerow(["City", "Orders", "Revenue (Rs)"])
    for c in city_data:
        writer.writerow([c['city'], c['orders'], c['revenue']])
    writer.writerow([])

    writer.writerow(["--- SALESMAN PERFORMANCE ---"])
    writer.writerow(["Salesman", "Orders", "Revenue (Rs)"])
    for s in salesmen_data:
        writer.writerow([s['salesman'], s['orders'], s['revenue']])

    filename = f"spiceflow_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── BILL / INVOICE 

@app.route("/orders/bill/<int:order_id>")
@login_required
def view_bill(order_id):
    """Show a printable invoice for a specific order."""
    conn = get_db()
    user_id = current_user_id()

    order_raw = conn.execute(
        "SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id)
    ).fetchone()

    if not order_raw:
        conn.close()
        flash("Order not found.", "error")
        return redirect(url_for("orders"))

    order = dict(order_raw)
    order['display_time'] = order['created_at'][:16] if order.get('created_at') else ''

    # Get the items in this order, including spice names and subtotals
    items = conn.execute("""
        SELECT s.name, s.category, oi.qty_20, oi.qty_50,
               (oi.qty_20 * 20 + oi.qty_50 * 50) AS subtotal
        FROM order_items oi
        JOIN spices s ON oi.spice_id = s.id
        WHERE oi.order_id=?
    """, (order_id,)).fetchall()

    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return render_template("bill.html", order=order, items=items, user=user)


 
    conn = get_db()
    user_id = current_user_id()
    spices  = conn.execute("SELECT id, name FROM spices WHERE user_id=?", (user_id,)).fetchall()
    updated = 0

    for spice in spices:
        name_lower = spice['name'].lower()
        for keyword, url in IMAGE_MAP.items():
            if keyword in name_lower:
                conn.execute(
                    "UPDATE spices SET img_url=? WHERE id=? AND user_id=?",
                    (url, spice['id'], user_id)
                )
                updated += 1
                break

    conn.commit()
    conn.close()
    flash(f"✅ Updated images for {updated} spices!", "success")
    return redirect(url_for("inventory"))


# ── SEED DEMO DATA ────────────────────────────────────────────────────────────

@app.route("/seed-demo-data")
@login_required
def seed_demo_data():
    """Add 12 demo orders spread across Apr, May, and Jun.
    Skipped if the user already has 5 or more orders."""
    conn = get_db()
    user_id = current_user_id()

    existing_count = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)).fetchone()[0]
    if existing_count >= 5:
        conn.close()
        flash("Demo data already exists — you already have orders!", "error")
        return redirect(url_for("dashboard"))

    spices = conn.execute("SELECT * FROM spices WHERE user_id=?", (user_id,)).fetchall()
    if not spices:
        conn.close()
        flash("No spices found. Go to Inventory first.", "error")
        return redirect(url_for("dashboard"))

    customers = [
        ("Ali Hassan",     "03001234567", "Lahore"),
        ("Fatima Khan",    "03111234567", "Karachi"),
        ("Usman Malik",    "03211234567", "Islamabad"),
        ("Ayesha Raza",    "03311234567", "Faisalabad"),
        ("Bilal Ahmed",    "03411234567", "Multan"),
        ("Sara Qureshi",   "03501234567", "Lahore"),
        ("Hamza Sheikh",   "03601234567", "Rawalpindi"),
        ("Zara Hussain",   "03701234567", "Sialkot"),
        ("Omar Farooq",    "03211111111", "Gujranwala"),
        ("Nida Butt",      "03111111111", "Lahore"),
        ("Tariq Jameel",   "03001111111", "Karachi"),
        ("Sana Mirza",     "03311111111", "Peshawar"),
    ]
    salesmen = ["Ahmed Raza", "Zain Ali", "Hassan Butt", "Imran Shah"]
    statuses = ["Delivered", "Delivered", "Delivered", "Dispatched", "Packing", "Pending"]
    demo_dates = [
        "2026-04-03 10:15:00", "2026-04-07 11:30:00", "2026-04-12 14:20:00",
        "2026-04-18 09:45:00", "2026-04-23 16:10:00",
        "2026-05-02 10:00:00", "2026-05-08 13:25:00", "2026-05-14 15:40:00",
        "2026-05-20 11:55:00", "2026-05-26 14:30:00",
        "2026-06-01 09:20:00", "2026-06-04 12:45:00",
    ]

    order_count = existing_count

    for i, date in enumerate(demo_dates):
        customer     = customers[i % len(customers)]
        salesman     = salesmen[i % len(salesmen)]
        status       = statuses[i % len(statuses)]
        order_count += 1
        order_number = f"#ORD-U{user_id}-{9900 + order_count}"

        # Pick 2–4 random spices for this demo order
        chosen = random.sample(list(spices), min(random.randint(2, 4), len(spices)))
        total  = 0
        items  = []

        for spice in chosen:
            q20 = random.randint(0, 5)
            q50 = random.randint(0, 3)
            if q20 == 0 and q50 == 0:
                q20 = random.randint(1, 5)  # Make sure at least something is ordered
            total += q20 * 20 + q50 * 50
            items.append((spice['id'], q20, q50))

        conn.execute(
            """INSERT INTO orders
               (user_id, order_number, customer_name, phone, city, salesman, total_amount, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, order_number, customer[0], customer[1], customer[2], salesman, total, status, date)
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for spice_id, q20, q50 in items:
            conn.execute(
                "INSERT INTO order_items (order_id, spice_id, qty_20, qty_50) VALUES (?,?,?,?)",
                (order_id, spice_id, q20, q50)
            )

    conn.commit()
    conn.close()
    flash(f"✅ {len(demo_dates)} demo orders added for Apr, May & Jun!", "success")
    return redirect(url_for("dashboard"))


# ── DEBUG ─────────────────────────────────────────────────────────────────────

@app.route("/debug/db")
def debug_db():
    """Dev tool: dump all database tables as JSON. Remove this in production!"""
    conn = get_db()
    tables = ["users", "spices", "orders", "order_items", "stock_log"]
    data = {
        table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
        for table in tables
    }
    conn.close()
    return jsonify(data)


# ── RUN THE APP ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("\n✅ SpiceFlow Pakistan running → http://127.0.0.1:5000\n")
    app.run(debug=True)
