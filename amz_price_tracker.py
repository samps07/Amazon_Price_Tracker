import requests
import os
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import threading

load_dotenv()

# Store tracking jobs (for multi-product support)
tracking_jobs = {}

def send_telegram_message(context, chat_id, message, image_url=None):
    bot_token = os.environ.get('BOT_TOKEN')
    if not bot_token:
        print("❌ Error: BOT_TOKEN environment variable is missing")
        return
    if image_url:
        context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=message)
    else:
        context.bot.send_message(chat_id=chat_id, text=message)

def fetch_amazon_price(url, chat_id, context):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find(id="productTitle")
        price_tag = soup.find("span", class_="a-offscreen") or soup.find("span", class_="a-price-whole")
        image_url = soup.find("img", id="landingImage")['src'] if soup.find("img", id="landingImage") else None
        if title_tag and price_tag:
            title = title_tag.text.strip()
            price_text = price_tag.text.strip().replace(',', '').replace('₹', '')
            price_value = float(price_text)
            send_telegram_message(context, chat_id, f"🛒 Product: {title}\n💰 Price: ₹{price_text}\n🔗 URL: {url}\n\nReply /confirm <target_price> to track or /cancel to discard.")
            return title, price_value, url, image_url
        else:
            send_telegram_message(context, chat_id, "⚠️ Error: Missing product data.")
    except Exception as e:
        send_telegram_message(context, chat_id, f"⚠️ Error: {e}")
    return None, None, None, None

def recurring_tracker(title, price_limit, url, chat_id, context):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }
    while tracking_jobs.get((chat_id, url), {}).get('active', False):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            price_tag = soup.find("span", class_="a-offscreen") or soup.find("span", class_="a-price-whole")
            image_url = soup.find("img", id="landingImage")['src'] if soup.find("img", id="landingImage") else None
            if price_tag:
                price_text = price_tag.text.strip().replace(',', '').replace('₹', '')
                current_price = float(price_text)
                if current_price <= price_limit:
                    send_telegram_message(context, chat_id, f"🎉 Good news!\n\n{title} is now ₹{current_price}!\nBelow target ₹{price_limit}.\nBUY NOW: {url}", image_url)
                    stop_tracking(chat_id, url)
                    return
                else:
                    print(f"ℹ️ Price for {title}: ₹{current_price} (target ₹{price_limit})")
            else:
                print("❌ No price found.")
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(300)  # Check every 5 minutes

def start(update, context):
    update.message.reply_text("Welcome to the Amazon Price Tracker Bot!\nUse /track <Amazon URL> to start tracking a product.")

def track(update, context):
    chat_id = update.message.chat_id
    try:
        url = context.args[0]
        title, price, url, image_url = fetch_amazon_price(url, chat_id, context)
        if title:
            tracking_jobs[(chat_id, url)] = {'title': title, 'price': price, 'image_url': image_url, 'confirmed': False}
    except IndexError:
        update.message.reply_text("Please provide an Amazon URL: /track <URL>")

def confirm(update, context):
    chat_id = update.message.chat_id
    try:
        price_limit = float(context.args[0])
        for (user_chat_id, url), job in list(tracking_jobs.items()):
            if user_chat_id == chat_id and not job['confirmed']:
                job['confirmed'] = True
                job['price_limit'] = price_limit
                job['active'] = True
                send_telegram_message(context, chat_id, f"🛒 Tracking Started!\n\n{job['title']}\nPrice: ₹{job['price']}\nTarget: ₹{price_limit}", job['image_url'])
                threading.Thread(target=recurring_tracker, args=(job['title'], price_limit, url, chat_id, context)).start()
                return
        update.message.reply_text("No product pending confirmation.")
    except (IndexError, ValueError):
        update.message.reply_text("Please provide a valid target price: /confirm <price>")

def cancel(update, context):
    chat_id = update.message.chat_id
    for (user_chat_id, url) in list(tracking_jobs.keys()):
        if user_chat_id == chat_id and not tracking_jobs[(user_chat_id, url)]['confirmed']:
            del tracking_jobs[(user_chat_id, url)]
            update.message.reply_text("Product tracking cancelled.")
            return
    update.message.reply_text("No product pending confirmation.")

def stop_tracking(chat_id, url):
    if (chat_id, url) in tracking_jobs:
        tracking_jobs[(chat_id, url)]['active'] = False
        del tracking_jobs[(chat_id, url)]

def stop(update, context):
    chat_id = update.message.chat_id
    try:
        url = context.args[0]
        stop_tracking(chat_id, url)
        update.message.reply_text(f"Stopped tracking {url}.")
    except IndexError:
        update.message.reply_text("Please provide the URL to stop: /stop <URL>")

def main():
    updater = Updater(os.environ.get('BOT_TOKEN'), use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("track", track))
    dp.add_handler(CommandHandler("confirm", confirm))
    dp.add_handler(CommandHandler("cancel", cancel))
    dp.add_handler(CommandHandler("stop", stop))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()