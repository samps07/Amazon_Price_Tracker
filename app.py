# app.py
import os
import uuid
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from scraper import fetch_amazon_details
import psycopg2

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")   # Render will provide this
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourBotUsername")
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

def get_conn():
    """Return a new psycopg2 connection (sslmode required on Render)."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create tracks table if missing."""
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id SERIAL PRIMARY KEY,
                token TEXT UNIQUE,
                title TEXT,
                url TEXT,
                image TEXT,
                current_price REAL,
                target_price REAL,
                status TEXT,        -- pending | active | stopped
                chat_id BIGINT,
                notification_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.commit()

# --- THIS IS THE FIX ---
# Ensure the DB table exists as soon as the app starts.
init_db()
# --------------------

CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))


def insert_pending_track(title, url, image, current_price, target):
    """Insert a pending track and return the token for deep-linking."""
    token = uuid.uuid4().hex
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO tracks (token, title, url, image, current_price, target_price, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """, (token, title, url, image, current_price, target))
        conn.commit()
    return token

@app.route("/", methods=["GET", "POST"])
def home():
    product = None
    if request.method == "POST":
        url = request.form.get("product_url", "").strip()
        if not url:
            flash("Paste a product link.")
        else:
            product = fetch_amazon_details(url)
            if not product:
                flash("Couldn't fetch product. Try a different link or wait a few seconds.")
    return render_template("index.html", product=product, bot_username=BOT_USERNAME)

@app.route("/track", methods=["POST"])
def track():
    url = request.form.get("url")
    target = request.form.get("price_limit")
    if not url or not target:
        flash("Missing data.")
        return redirect(url_for("home"))

    product = fetch_amazon_details(url)
    if not product:
        flash("Error fetching product details.")
        return redirect(url_for("home"))

    try:
        target_val = float(target)
    except:
        flash("Enter a valid target price.")
        return redirect(url_for("home"))

    # save pending track in Postgres
    token = insert_pending_track(product["title"], url, product.get("image"), product.get("price"), target_val)

    # deep-link to telegram bot with token
    tg_link = f"https://t.me/{BOT_USERNAME}?start={token}"
    return redirect(tg_link)

# This block is now only used for running the app on your local machine
if __name__ == "__main__":
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set. Set it in env (Render provides it).")
    port = int(os.environ.get("PORT", 5000))
    # Bind to 0.0.0.0 for hosting services
    app.run(host="0.0.0.0", port=port, debug=(os.environ.get("FLASK_DEBUG", "0") == "1"))
