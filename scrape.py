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

# The site paginates results with ?pager=N (works on category/subcategory
# pages too, appended after ?filters=). Rather than hardcoding how many pages
# exist, the scraper walks pager=1, 2, 3... automatically per section and
# stops once a page returns zero products.
MAX_PAGES = 50  # safety cap per category/subcategory so a bug can't loop forever

# Any page that has the sidebar category menu — used once at the start to
# discover every category/subcategory URL automatically.
MENU_SOURCE_URL = "https://www.banksiaglen.com/pl.php"
SITE_ROOT = "https://www.banksiaglen.com/"

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


# The site's subcategory/city menu is only populated by JavaScript in a real
# browser — a plain HTTP request never sees it, no matter what headers are
# sent. Rather than running a full headless browser just to read a menu (slow,
# fragile), this structure is captured once from the real site and used
# directly. If categories are ever added/removed/renamed on the site, this
# list needs a manual update to match — but it makes every run fast and
# reliable in the meantime.
#
# Format: (category_slug, category_display_name, [
#     (subcategory_slug, subcategory_display_name, [city_slug, city_slug, ...]),
#     ...
# ])
# An empty subcategory list means the category has no subcategories (scrape
# it directly). An empty city list means that subcategory has no city
# breakdown (scrape the subcategory URL directly).
CATEGORY_TREE = [
    ("Aboriginal-Art", "Aboriginal Art", [
        ("Boomerangs", "Boomerangs", ["National"]),
        ("Coasters-and-Placements", "Coasters and Placements", ["National"]),
        ("Coffee-Mugs", "Coffee Mugs", ["National"]),
        ("Keyring-Sets", "Keyring Sets", ["National"]),
        ("Magnets", "Magnets", ["National"]),
        ("Shot-Glasses", "Shot Glasses", ["National"]),
    ]),
    ("Apparel,-Footwear-and-Beach-Towels", "Apparel, Footwear and Beach Towels", [
        ("Baby-Bibs", "Baby Bibs", []),
        ("Beach-Towels", "Beach Towels", ["Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Clothing", "Clothing", ["National", "Sydney"]),
        ("Footware", "Footware", ["Cairns", "National"]),
        ("Iron-On-Patches", "Iron On Patches", ["National"]),
    ]),
    ("Australian-Flag", "Australian Flag", []),
    ("Australian-Made", "Australian Made", [
        ("Body-care-and-Foods", "Body care and Foods", ["National"]),
        ("Boomerangs", "Boomerangs", []),
        ("Kangaroo-Scrotum-products", "Kangaroo Scrotum products", []),
        ("Plush-Toys-and-Others", "Plush Toys and Others", []),
    ]),
    ("Bags", "Bags", [
        ("Foldable-Bags", "Foldable Bags", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Other-bags", "Other bags", ["National", "Sydney"]),
        ("Premium-canvas-cotton-Bags", "Premium canvas cotton Bags", ["Brisbane", "Cairns", "Melbourne", "National", "Perth", "Sydney"]),
        ("Shopping-Bags", "Shopping Bags", ["Brisbane", "Gold-Coast", "Melbourne", "National", "Sydney"]),
    ]),
    ("Caps-and-Hats", "Caps and Hats", [
        ("Bucket-Hats-and-Cork-Hats", "Bucket Hats and Cork Hats", ["National"]),
        ("Polyester-Caps", "Polyester Caps", ["Adelaide", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Premium-Caps", "Premium Caps", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Hamilton-Island", "Melbourne", "National", "Perth", "Sydney"]),
    ]),
    ("Clocks", "Clocks", [
        ("Clocks", "Clocks", ["Brisbane", "Gold-Coast", "National", "Perth", "Sydney"]),
    ]),
    ("Display-Plates,-Frames-and-Premium-Gifts", "Display Plates, Frames and Premium Gifts", [
        ("Ash-Trays", "Ash Trays", ["Brisbane", "Cairns", "Gold-Coast", "National", "Sydney"]),
        ("Business-Card-Holders", "Business Card Holders", ["National", "Sydney"]),
        ("Desk-Decor", "Desk Decor", ["Melbourne", "National", "Sydney"]),
        ("Frames", "Frames", ["Melbourne", "National", "Sydney"]),
        ("Mirrors", "Mirrors", ["Cairns", "Melbourne", "National", "Perth", "Sydney"]),
        ("Pins", "Pins", ["Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Sydney"]),
        ("Plates", "Plates", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Shot-Glasses", "Shot Glasses", ["National", "Sydney"]),
    ]),
    ("Drink-Accessories,-Coffee-Mugs-and-Shot-Glasses", "Drink Accessories, Coffee Mugs and Shot Glasses", [
        ("Ash-Trays", "Ash Trays", ["National"]),
        ("Coasters-and-Placements", "Coasters and Placements", ["Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Coffee-Mugs", "Coffee Mugs", ["Adelaide", "Brisbane", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Espresso-Mugs", "Espresso Mugs", ["Brisbane", "Cairns", "Gold-Coast", "National", "Sydney"]),
        ("Others", "Others", ["National", "Sydney"]),
        ("Shot-Glasses", "Shot Glasses", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Stubby-Holders", "Stubby Holders", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Wine-holders-and-bottle-holders", "Wine holders and bottle holders", ["National", "Sydney"]),
    ]),
    ("Fridge-Magnets", "Fridge Magnets", [
        ("Foil-Magnets", "Foil Magnets", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Magnets", "Magnets", ["Melbourne", "National", "Sydney"]),
        ("MDF-Magnets-_and_-Keyrings", "MDF Magnets & Keyrings", ["Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Sydney"]),
        ("Metal-Magnets", "Metal Magnets", ["Adelaide", "Brisbane", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Polyresin-Magnets", "Polyresin Magnets", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Polyresin-Ornaments", "Polyresin Ornaments", ["Sydney"]),
        ("Wooden-Magnets", "Wooden Magnets", ["National"]),
    ]),
    ("Kitchen-Accessories-and-Tea-Towels", "Kitchen Accessories and Tea Towels", [
        ("Aprons,-Mittens,-Pot-holders-and-Kitchen-Accessories", "Aprons, Mittens, Pot holders and Kitchen Accessories", ["Brisbane", "Cairns", "Melbourne", "National", "Sydney"]),
        ("Tea-Towels", "Tea Towels", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
    ]),
    ("Non-Souvenir-Products", "Non Souvenir Products", [
        ("Shopping-Bags", "Shopping Bags", []),
        ("Wooden-Keyrings", "Wooden Keyrings", ["National"]),
    ]),
    ("Soft-Toys", "Soft Toys", [
        ("Backpacks", "Backpacks", ["Cairns", "National"]),
        ("Clip-On", "Clip On", []),
        ("Others", "Others", ["National"]),
        ("Plush-Toy-Koalas-and-Kangroos", "Plush Toy Koalas and Kangroos", ["National"]),
        ("Plush-Toys-and-Others", "Plush Toys and Others", ["National"]),
        ("Soft-Toy-Keyings-and-Magnets", "Soft Toy Keyings and Magnets", ["Melbourne", "National"]),
    ]),
    ("Souvenir-Keyrings-and-Keyring-Sets", "Souvenir Keyrings and Keyring Sets", [
        ("Keyring-Sets", "Keyring Sets", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Keyrings", "Keyrings", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Others", "Others", ["National", "Sydney"]),
        ("Wooden-Keyrings", "Wooden Keyrings", ["National", "Perth", "Sydney"]),
        ("Wooden-Magnets", "Wooden Magnets", ["Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
    ]),
    ("Sports-and-Accessories", "Sports and Accessories", [
        ("Christmas-Ornaments", "Christmas Ornaments", ["Gold-Coast", "National"]),
        ("Eye-Glasses-Cases", "Eye Glasses Cases", ["Brisbane", "National"]),
        ("Golf-Sets", "Golf Sets", ["National"]),
        ("Key-Holders", "Key Holders", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Others", "Others", ["Gold-Coast", "Melbourne", "National", "Sydney"]),
        ("Road-Signs-and-Car-Plates", "Road Signs and Car Plates", ["Adelaide", "Brisbane", "Melbourne", "National", "Perth", "Sydney"]),
    ]),
    ("Stationery", "Stationery", [
        ("Neoprene-Coin-Bags", "Neoprene Coin Bags", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "National", "Perth", "Sydney"]),
        ("Others", "Others", ["National", "Sydney"]),
        ("Pencil-Cases", "Pencil Cases", ["Adelaide", "Brisbane", "Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Pens-and-Pencils", "Pens and Pencils", ["Cairns", "Gold-Coast", "Melbourne", "National", "Perth", "Sydney"]),
        ("Postcards", "Postcards", ["National", "Sydney"]),
        ("Ruler-Sets", "Ruler Sets", ["Adelaide", "Melbourne", "National", "Sydney"]),
        ("Stationery-Sets", "Stationery Sets", ["Melbourne", "National", "Sydney"]),
        ("Stickers", "Stickers", ["Melbourne", "National", "Sydney"]),
    ]),
    ("Wallets-and-Leather-Products", "Wallets and Leather Products", [
        ("Coin-Purses,-Passport-Holder-and-Key-Wallets", "Coin Purses, Passport Holder and Key Wallets", ["National", "Perth", "Sydney"]),
        ("Lady's-Wallets", "Lady's Wallets", ["National", "Sydney"]),
        ("Men's-Wallets", "Men's Wallets", ["National", "Sydney"]),
        ("Other-Leather-Bags", "Other Leather Bags", ["National"]),
    ]),
    ("Water-Globes-and-Polyresin-Ornaments", "Water Globes and Polyresin Ornaments", [
        ("Polyresin-Magnets", "Polyresin Magnets", ["National"]),
        ("Polyresin-Ornaments", "Polyresin Ornaments", ["Melbourne", "National", "Perth", "Sydney"]),
        ("Salt-and-Pepper-Shakers", "Salt and Pepper Shakers", ["National"]),
        ("Water-Globes-and-Others", "Water Globes and Others", ["Adelaide", "Brisbane", "Cairns", "Melbourne", "National", "Perth", "Sydney"]),
    ]),
]


def scrape_section_pages(session, base_url):
    """Paginate a single category or subcategory URL, walking pager=1, 2,
    3... until a page returns zero products."""
    items = []
    separator = "&" if "?" in base_url else "?"
    for page_num in range(1, MAX_PAGES + 1):
        url = f"{base_url}{separator}pager={page_num}"
        page_items = scrape_static_page(session, url)

        if not page_items:
            break

        items.extend(page_items)
        time.sleep(1)  # be polite, avoid hammering the server

    return items


def scrape_all_products_fallback(session):
    """Used only if get_category_tree() finds nothing — scrapes the flat
    'All Products' listing instead, so a category-discovery failure never
    results in an empty catalogue. Items get no category/subcategory/city."""
    items = []
    for page_num in range(1, MAX_PAGES + 1):
        url = f"{MENU_SOURCE_URL}?pager={page_num}"
        page_items = scrape_static_page(session, url)
        if not page_items:
            break
        items.extend(page_items)
        time.sleep(1)

    for item in items:
        item["category"] = "All products"
        item["subcategory"] = None
        item["city"] = None

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
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    print("Logging in...")
    login(session)

    all_items = []

    for cat_slug, cat_name, subcategories in CATEGORY_TREE:
        if not subcategories:
            url = f"{SITE_ROOT}{cat_slug}/pl.php?filters="
            print(f"Scraping {cat_name} ...")
            items = scrape_section_pages(session, url)
            for item in items:
                item["category"] = cat_name
                item["subcategory"] = None
                item["city"] = None
            print(f"  -> {len(items)} products")
            all_items.extend(items)
            continue

        for sub_slug, sub_name, cities in subcategories:
            if not cities:
                url = f"{SITE_ROOT}{cat_slug}/{sub_slug}/pl.php?filters="
                print(f"Scraping {cat_name} > {sub_name} ...")
                items = scrape_section_pages(session, url)
                for item in items:
                    item["category"] = cat_name
                    item["subcategory"] = sub_name
                    item["city"] = None
                print(f"  -> {len(items)} products")
                all_items.extend(items)
                continue

            for city_slug in cities:
                city_name = city_slug.replace("-", " ")
                url = f"{SITE_ROOT}{cat_slug}/{sub_slug}/{city_slug}/pl.php?filters="
                print(f"Scraping {cat_name} > {sub_name} > {city_name} ...")
                items = scrape_section_pages(session, url)
                for item in items:
                    item["category"] = cat_name
                    item["subcategory"] = sub_name
                    item["city"] = city_name
                print(f"  -> {len(items)} products")
                all_items.extend(items)

    # A product can legitimately appear under more than one category/city on
    # the site — each combination is kept as its own row so it shows up in
    # every relevant section. This only removes exact duplicate rows.
    seen = set()
    deduped = []
    for item in all_items:
        key = (item["item_number"], item["category"], item.get("subcategory"), item.get("city"))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    all_items = deduped

    print(f"Found {len(all_items)} product-category entries. Downloading images...")
    for item in all_items:
        item["local_image"] = download_image(session, item["image_url"], item["item_number"])

    with open(DATA_FILE, "w") as f:
        json.dump(all_items, f, indent=2)

    print(f"Done. Saved {len(all_items)} items to {DATA_FILE}")


if __name__ == "__main__":
    main()
