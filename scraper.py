# scraper.py
import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9"
}

def parse_price_text(price_text):
    # keep digits and dots
    cleaned = re.sub(r"[^\d.]", "", price_text)
    try:
        return float(cleaned) if cleaned else None
    except:
        return None

def fetch_amazon_details(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find(id="productTitle")
        # Amazon sometimes uses a-offscreen for full price
        price_tag = (soup.find("span", class_="a-price-whole")
                     or soup.find("span", class_="a-offscreen")
                     or soup.select_one("span#priceblock_ourprice")
                     or soup.select_one("span#priceblock_dealprice"))
        image_tag = soup.find("img", id="landingImage") or soup.select_one("#imgTagWrapperId img")

        if not title_tag or not price_tag:
            return None

        title = title_tag.text.strip()
        price_text = price_tag.text.strip()
        price_value = parse_price_text(price_text)
        image_url = image_tag['src'] if image_tag and image_tag.get('src') else None

        return {
            "title": title,
            "price": price_value,
            "image": image_url,
            "url": url
        }
    except Exception as e:
        print("Scraper error:", e)
        return None


