# tracker.py
import os
import time
import threading
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from scraper import fetch_amazon_details
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram import Update

load_dotenv()
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Render provides this
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))  # seconds

# runtime maps to avoid duplicate threads: entry_id -> threading.Thread
active_threads = {}
updater = None
bot = None

# --- DB helpers ---
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
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

def find_pending_by_token(token):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT id, title, url, image, current_price, target_price, status, chat_id, notification_count FROM tracks WHERE token = %s", (token,))
            return c.fetchone()

def activate_track(entry_id, chat_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE tracks SET status = 'active', chat_id = %s, notification_count = 0 WHERE id = %s", (chat_id, entry_id))
        conn.commit()

def mark_stopped(entry_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE tracks SET status = 'stopped' WHERE id = %s", (entry_id,))
        conn.commit()

def get_active_tracks():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT id, title, url, image, target_price, notification_count, chat_id FROM tracks WHERE status = 'active'")
            return c.fetchall()

def increment_notification(entry_id):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE tracks SET notification_count = notification_count + 1 WHERE id = %s RETURNING notification_count", (entry_id,))
            new_val = c.fetchone()[0]
        conn.commit()
        return new_val

# --- Bot messaging ---
def send_message(chat_id, text, image_url=None):
    try:
        if image_url:
            bot.send_photo(chat_id=chat_id, photo=image_url, caption=text)
        else:
            bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print("Telegram send error:", e)

# --- Tracker thread ---
def tracker_loop(entry_id, title, url, image, target_price, chat_id):
    print(f"[Tracker] started for id={entry_id} target={target_price} chat={chat_id}")
    while True:
        # check if still active
        with get_conn() as conn:
            with conn.cursor() as c:
                c.execute("SELECT status, notification_count FROM tracks WHERE id = %s", (entry_id,))
                row = c.fetchone()
                if not row or row[0] != 'active':
                    print(f"[Tracker] stopping id={entry_id} (status not active)")
                    return
                notification_count = row[1]

        data = fetch_amazon_details(url)
        if data and data.get("price") is not None:
            current_price = data["price"]
            print(f"[Tracker] {title} current {current_price} target {target_price}")
            if current_price <= float(target_price):
                # notify and increment count
                n = increment_notification(entry_id)
                send_message(chat_id, f"🎉 Good news!\n\n{title}\nPrice: ₹{current_price}\nTarget: ₹{target_price}\n{url}", image)
                if n >= 5:
                    send_message(chat_id, f"🔔 Reached {n} notifications. Stopping tracking for this product.")
                    mark_stopped(entry_id)
                    return
        else:
            print("[Tracker] couldn't parse price this round.")

        time.sleep(CHECK_INTERVAL)

# --- Bot commands ---
def start_command(update: Update, context: CallbackContext):
    global bot
    user = update.effective_user
    args = context.args
    if args:
        token = args[0]
        row = find_pending_by_token(token)
        if not row:
            update.message.reply_text("No pending tracking found for that link/token.")
            return
        entry_id, title, url, image, current_price, target_price, status, chat_id, notification_count = row
        if status == 'active':
            update.message.reply_text("This item is already being tracked.")
            return

        # activate and start thread
        activate_track(entry_id, user.id)
        update.message.reply_text(f"✅ Tracking started for:\n{title}\nTarget: ₹{target_price}\nYou will receive updates here.")
        # start thread
        t = threading.Thread(target=tracker_loop, args=(entry_id, title, url, image, target_price, user.id), daemon=True)
        t.start()
        active_threads[entry_id] = t
    else:
        update.message.reply_text("Welcome! Use /track <URL> to track a product or open via the web app link to start tracking.")

def track_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not context.args:
        update.message.reply_text("Usage: /track <product-url>")
        return
    url = context.args[0]
    data = fetch_amazon_details(url)
    if not data:
        update.message.reply_text("Couldn't fetch product data. Paste a valid Amazon product URL.")
        return
    # insert a DB row in pending (so we have record)
    token = uuid.uuid4().hex
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO tracks (token, title, url, image, current_price, status)
                VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id
            """, (token, data["title"], url, data.get("image"), data.get("price")))
            entry_id = c.fetchone()[0]
        conn.commit()

    update.message.reply_text(f"Product found:\n{data['title']}\nPrice: ₹{data['price']}\n\nReply with /confirm {entry_id} <target_price> to start tracking or open this bot link to confirm via web:\nhttps://t.me/{context.bot.username}?start={token}")

def confirm_cmd(update: Update, context: CallbackContext):
    try:
        if len(context.args) == 1:
            target = float(context.args[0])
            with get_conn() as conn:
                with conn.cursor() as c:
                    c.execute("SELECT id, title, url, image FROM tracks WHERE status='pending' ORDER BY created_at DESC LIMIT 1")
                    row = c.fetchone()
                    if not row:
                        update.message.reply_text("No pending track found. Use /track <URL> first.")
                        return
                    entry_id, title, url, image = row
        else:
            entry_id = int(context.args[0])
            target = float(context.args[1])
            with get_conn() as conn:
                with conn.cursor() as c:
                    c.execute("SELECT title, url, image FROM tracks WHERE id = %s", (entry_id,))
                    row = c.fetchone()
                    if not row:
                        update.message.reply_text("Entry not found.")
                        return
                    title, url, image = row

        activate_track(entry_id, update.effective_chat.id)
        with get_conn() as conn:
            with conn.cursor() as c:
                c.execute("UPDATE tracks SET target_price = %s WHERE id = %s", (target, entry_id))
            conn.commit()

        t = threading.Thread(target=tracker_loop, args=(entry_id, title, url, image, target, update.effective_chat.id), daemon=True)
        t.start()
        active_threads[entry_id] = t

        update.message.reply_text(f"✅ Tracking started for:\n{title}\nTarget: ₹{target}\nYou will receive updates here.")
    except Exception as e:
        update.message.reply_text("Error: please use /confirm <entry_id> <target_price> or /confirm <target_price>.")
        print("confirm error:", e)

def cancel_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT id FROM tracks WHERE chat_id = %s AND status = 'active' ORDER BY created_at DESC LIMIT 1", (chat_id,))
            row = c.fetchone()
            if not row:
                update.message.reply_text("No active tracking found for your chat.")
                return
            entry_id = row[0]
    mark_stopped(entry_id)
    update.message.reply_text("Stopped tracking.")

def list_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT id, title, target_price, status FROM tracks WHERE chat_id = %s ORDER BY created_at DESC", (chat_id,))
            rows = c.fetchall()
            if not rows:
                update.message.reply_text("No tracks found for this chat.")
                return
            msg = "Your tracks:\n"
            for r in rows:
                msg += f"#{r[0]} {r[1][:50]} ... | target ₹{r[2]} | {r[3]}\n"
            update.message.reply_text(msg)

def background_active_checker():
    rows = get_active_tracks()
    for r in rows:
        entry_id, title, url, image, target_price, notification_count, chat_id = r
        if entry_id not in active_threads:
            t = threading.Thread(target=tracker_loop, args=(entry_id, title, url, image, target_price, chat_id), daemon=True)
            t.start()
            active_threads[entry_id] = t

def main():
    global updater, bot
    if not BOT_TOKEN:
        print("BOT_TOKEN not set in env.")
        return
    init_db()
    updater = Updater(BOT_TOKEN, use_context=True)
    bot = updater.bot

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("track", track_cmd))
    dp.add_handler(CommandHandler("confirm", confirm_cmd))
    dp.add_handler(CommandHandler("cancel", cancel_cmd))
    dp.add_handler(CommandHandler("list", list_cmd))

    updater.start_polling()
    print("Bot polling started.")
    background_active_checker()
    updater.idle()

if __name__ == "__main__":
    main()
