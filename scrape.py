"""
Wholesale catalogue scraper — daily refresh
--------------------------------------------
Fill in the CONFIG section below once you know:
  1. The login URL and form field names
  2. The product listing URL(s)
  3. Whether products load in plain HTML or via JavaScript

Run once manually to test, then schedule it (see bottom of this file / README).
"""

import json
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# =========================== CONFIG — EDIT THIS ===========================

LOGIN_URL = "https://www.banksiaglen.com/home.php"
LOGIN_PAYLOAD = {
    "Operation[0]": "LoginSellerUserOrBuyerUser",
    "SellerUserCheckField": "AccountManager",
    "Operation[1]": "Redirect",
    "UserName": os.environ.get("BANKSIA_USERNAME", ""),
    "Password": os.environ.get("BANKSIA_PASSWORD", ""),
    "LoginSubmit": "Login",
}

# One or more pages that list products. If the site paginates, list every
# page URL, or better, find the "?page=" pattern and generate them in a loop.
CATALOGUE_URLS = [
    "https://www.banksiaglen.com/pl.php",
]

# Site-specific selectors for banksiaglen.com — confirmed from actual page HTML:
#   - Item number sits in: <input type="hidden" name="productcode" value="...">
#   - Image sits in:       <img src="https://www.banksiaglen.com/productimages/thumbnails/....jpg">
#     (no unique class/itemprop on the listing page — matched by the URL path instead,
#     which reliably targets product thumbnails and excludes logos/icons/etc.)
# These aren't nested inside a shared container we've seen yet, so we pair
# them up by their order of appearance on the page (assumes 1 image + 1
# productcode per product, in matching order — true for most simple catalogues).
ITEM_NUMBER_ATTR_SELECTOR = 'input[name="productcode"]'
IMAGE_ATTR_SELECTOR = 'img[src*="/productimages/"]'

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
DATA_FILE = os.path.join(OUTPUT_DIR, "catalogue.json")

# ============================================================================


def login(session):
    resp = session.post(LOGIN_URL, data=LOGIN_PAYLOAD)
    resp.raise_for_status()
    return resp


def scrape_static_page(session, url):
    """Use this if the product list is present in the raw HTML (view-source
    shows the products). Fast and reliable — try this first."""
    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    codes = soup.select(ITEM_NUMBER_ATTR_SELECTOR)
    images = soup.select(IMAGE_ATTR_SELECTOR)

    if len(codes) != len(images):
        print(f"  ! Warning: found {len(codes)} product codes but {len(images)} "
              f"images on {url} — counts don't match, pairing may be wrong. "
              f"Send me the full product-card HTML so I can fix the pairing logic.")

    items = []
    for code_el, img_el in zip(codes, images):
        item_number = code_el.get("value", "").strip()
        img_src = img_el.get("src")

        if img_src:
            img_src = urljoin(url, img_src)  # handle relative/spaces in URLs

        if item_number and img_src:
            items.append({"item_number": item_number, "image_url": img_src})

    return items


def scrape_js_page(url):
    """Use this instead if products only appear after JavaScript runs
    (e.g. you view-source and see an empty <div id='products'></div>).
    Requires: pip install playwright && playwright install chromium
    """
    from playwright.sync_api import sync_playwright

    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # If login is needed and it's a simple form:
        page.goto(LOGIN_URL)
        # page.fill("input[name=username]", LOGIN_PAYLOAD["username"])
        # page.fill("input[name=password]", LOGIN_PAYLOAD["password"])
        # page.click("button[type=submit]")
        # page.wait_for_load_state("networkidle")

        page.goto(url)
        page.wait_for_load_state("networkidle")  # wait for JS to finish loading products

        # If the site uses "load more" / infinite scroll, scroll + click here:
        # for _ in range(10):
        #     page.mouse.wheel(0, 3000)
        #     page.wait_for_timeout(1000)

        cards = page.query_selector_all(PRODUCT_CARD_SELECTOR)
        for card in cards:
            item_el = card.query_selector(ITEM_NUMBER_SELECTOR)
            img_el = card.query_selector(IMAGE_SELECTOR)

            item_number = item_el.inner_text().strip() if item_el else None
            img_src = img_el.get_attribute("src") if img_el else None

            if img_src:
                img_src = urljoin(url, img_src)

            if item_number and img_src:
                items.append({"item_number": item_number, "image_url": img_src})

        browser.close()
    return items


def sanitize_filename(name):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def download_image(session, url, item_number):
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    filename = sanitize_filename(item_number) + ext
    filepath = os.path.join(IMAGES_DIR, filename)

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return os.path.join("images", filename)  # relative path for HTML
    except Exception as e:
        print(f"  ! Failed to download image for {item_number}: {e}")
        return url  # fall back to remote URL


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    session = requests.Session()

    print("Logging in...")
    login(session)

    all_items = []
    for url in CATALOGUE_URLS:
        print(f"Scraping {url} ...")
        items = scrape_static_page(session, url)
        # If scrape_static_page returns nothing, the site is likely JS-rendered.
        # Comment the line above and uncomment below instead:
        # items = scrape_js_page(url)
        all_items.extend(items)
        time.sleep(1)  # be polite, avoid hammering the server

    print(f"Found {len(all_items)} products. Downloading images...")
    for item in all_items:
        item["local_image"] = download_image(session, item["image_url"], item["item_number"])

    with open(DATA_FILE, "w") as f:
        json.dump(all_items, f, indent=2)

    print(f"Done. Saved {len(all_items)} items to {DATA_FILE}")


if __name__ == "__main__":
    main()
