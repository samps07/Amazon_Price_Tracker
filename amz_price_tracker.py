import requests
import os
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv()
print("Loaded BOT_TOKEN:", os.environ.get('BOT_TOKEN'))

def send_telegram_message(message, image_url=None):
    # Telegram bot credentials
    bot_token = os.environ.get('BOT_TOKEN')
    chat_id = os.environ.get('CHAT_ID')
    if not bot_token or not chat_id:
        print("❌ Error: BOT_TOKEN or CHAT_ID environment variable is missing")
        return
    
    # Send photo if image_url provided, else send text
    url = f'https://api.telegram.org/bot{bot_token}/sendPhoto' if image_url else f'https://api.telegram.org/bot{bot_token}/sendMessage'
    data = {'chat_id': chat_id, 'caption': message} if image_url else {'chat_id': chat_id, 'text': message}
    if image_url:
        data['photo'] = image_url
    
    response = requests.post(url, data=data)
    print("📩 Telegram Response:", response.status_code, response.text)
    if response.status_code != 200:
        print(f"❌ Error: {response.text}")

def fetch_amazon_price(url):
    # Headers for Amazon scraping
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }

    try:
        # Fetch and parse Amazon page
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title, price, and image
        title_tag = soup.find(id="productTitle")
        price_tag = soup.find("span", class_="a-offscreen") or soup.find("span", class_="a-price-whole")
        image_url = soup.find("img", id="landingImage")['src'] if soup.find("img", id="landingImage") else None

        if title_tag and price_tag:
            title = title_tag.text.strip()
            price_text = price_tag.text.strip().replace(',', '').replace('₹', '')
            price_value = float(price_text)

            print(f"🔍 Image URL: {image_url}")
            print(f"🛒 Product: {title}")
            print(f"💰 Price: ₹{price_text}")

            # Confirm product and set target price
            if input("\n✅ Correct product? (Y/N): ").strip().upper() == "Y":
                price_limit = float(input("🎯 Target price: ₹"))
                send_telegram_message(
                    f"🛒 Tracking Started!\n\n{title}\nPrice: ₹{price_text}\nTarget: ₹{price_limit}",
                    image_url
                )
                print(f"✅ Tracking started for ₹{price_limit}")
                return title, price_limit, url
            else:
                print("🔁 Restart with correct URL.")
        else:
            print("❌ Missing title or price.")
            send_telegram_message("⚠️ Error: Missing product data.")
    except Exception as e:
        print(f"❌ Error: {e}")
        send_telegram_message(f"⚠️ Error: {e}")

    return None, None, None

def recurring_tracker(title, price_limit, url):
    # Headers for recurring checks
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }

    try:
        # Fetch and parse page
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract price and image
        price_tag = soup.find("span", class_="a-offscreen") or soup.find("span", class_="a-price-whole")
        image_url = soup.find("img", id="landingImage")['src'] if soup.find("img", id="landingImage") else None

        if price_tag:
            price_text = price_tag.text.strip().replace(',', '').replace('₹', '')
            current_price = float(price_text)

            # Check if price is at or below target
            if current_price <= price_limit:
                print(f"🔍 Image URL: {image_url}")
                send_telegram_message(f"🎉 Good news!\n\n{title} is now ₹{current_price}!\nBelow target ₹{price_limit}.\nBUY NOW : {url}",image_url)
                print(f"📢 Alert: ₹{current_price} <= ₹{price_limit}")
                return True
            else:
                print(f"ℹ️ Price: ₹{current_price} (target ₹{price_limit})")
        else:
            print("❌ No price found.")
    except Exception as e:
        print(f"❌ Error: {e}")

    return False

# Start tracking
url = input("\n🔗 Enter Amazon product URL:\n> ")
title, price_limit, url = fetch_amazon_price(url)

# Recurring price checks
if title and price_limit and url:
    runs = 0
    while True:
        stop = recurring_tracker(title, price_limit, url)
        runs += 1
        if runs == 5:
            if input("5 checks done, continue? (Y/N): ").strip().upper() == 'N':
                break
        time.sleep(300)  # Check every 5 minutes

#things to add
#1.product picture scraping - done
#2.deploy 24/7 using render
#3.complete standalone telegram bot
#4.multi product support
#4.earnkaro referral links generation
#random link : https://amzn.in/d/ahaEHli