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


def get_category_tree(session):
    """Reads the sidebar category menu (present on any pl.php page) and
    builds a 3-level dict: category -> subcategory -> city. Cities are
    optional — many subcategories have no city breakdown at all."""
    resp = session.get(MENU_SOURCE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    menu = soup.select_one("#Menu_Products")
    if not menu:
        print("  ! Could not find the category menu on the page — check "
              "MENU_SOURCE_URL and whether login succeeded.")
        return {}

    tree = {}
    for a in menu.select('a[href*="pl.php?filters="]'):
        raw_href = a.get("href", "").strip()
        if not raw_href:
            continue

        # The raw HTML may use relative links (e.g. "/Aboriginal-Art/pl.php?filters=")
        # even though browser DevTools shows absolute URLs when you copy HTML —
        # browsers resolve links automatically when serializing. urljoin handles
        # both relative and already-absolute hrefs correctly.
        href = urljoin(MENU_SOURCE_URL, raw_href)
        if not href.startswith(SITE_ROOT):
            continue

        path = href[len(SITE_ROOT):]
        segments = [s for s in path.split("/") if s and s.lower() != "pl.php"]

        # 0 segments = the root "All Products" style link. 1 = category,
        # 2 = subcategory, 3 = city/region.
        if len(segments) == 0 or len(segments) > 3:
            continue

        name_el = a.select_one(".menu_item")
        name = name_el.get_text(strip=True) if name_el else segments[-1].replace("-", " ")

        cat_slug = segments[0]
        tree.setdefault(cat_slug, {"name": None, "url": None, "subcategories": {}})

        if len(segments) == 1:
            tree[cat_slug]["name"] = name
            tree[cat_slug]["url"] = href
        elif len(segments) == 2:
            sub_slug = segments[1]
            tree[cat_slug]["subcategories"].setdefault(
                sub_slug, {"name": None, "url": None, "cities": {}}
            )
            tree[cat_slug]["subcategories"][sub_slug]["name"] = name
            tree[cat_slug]["subcategories"][sub_slug]["url"] = href
        else:
            sub_slug, city_slug = segments[1], segments[2]
            tree[cat_slug]["subcategories"].setdefault(
                sub_slug, {"name": None, "url": None, "cities": {}}
            )
            tree[cat_slug]["subcategories"][sub_slug]["cities"][city_slug] = {
                "name": name,
                "url": href,
            }

    if not tree:
        sample_links = menu.select('a[href*="pl.php?filters="]')[:3]
        all_links = menu.select('a')
        print(f"  ! Found the menu but built 0 categories. "
              f"Menu contained {len(sample_links)} links matching the pattern "
              f"out of {len(all_links)} total <a> tags inside the menu. "
              f"Sample of first 3 hrefs found in menu: "
              f"{[a.get('href') for a in all_links[:3]]}")

    # Fall back to a slug-derived name for anything only ever seen via a
    # deeper link (shouldn't normally happen, but just in case).
    for cat_slug, cat_data in tree.items():
        if not cat_data["name"]:
            cat_data["name"] = cat_slug.replace("-", " ")
        for sub_data in cat_data["subcategories"].values():
            if not sub_data["name"]:
                sub_data["name"] = "General"

    return tree


def scrape_section_pages(session, base_url):
    """Paginate a single category or subcategory URL, walking pager=1, 2,
    3... until a page returns zero products."""
    items = []
    for page_num in range(1, MAX_PAGES + 1):
        url = f"{base_url}&pager={page_num}"
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

    print("Reading category menu...")
    tree = get_category_tree(session)
    print(f"Found {len(tree)} top-level categories.")

    all_items = []

    if not tree:
        print("  ! No categories found — falling back to a flat 'all products' "
              "scrape so the catalogue isn't left empty. Category navigation "
              "won't work until the category-discovery issue is fixed.")
        all_items = scrape_all_products_fallback(session)
    else:
        for cat_slug, cat_data in tree.items():
            cat_name = cat_data["name"]
            subcats = cat_data["subcategories"]

            if subcats:
                for sub_slug, sub_data in subcats.items():
                    sub_name = sub_data["name"]
                    cities = sub_data["cities"]

                    if cities:
                        for city_slug, city_data in cities.items():
                            city_name = city_data["name"]
                            print(f"Scraping {cat_name} > {sub_name} > {city_name} ...")
                            items = scrape_section_pages(session, city_data["url"])
                            for item in items:
                                item["category"] = cat_name
                                item["subcategory"] = sub_name
                                item["city"] = city_name
                            print(f"  -> {len(items)} products")
                            all_items.extend(items)
                    else:
                        print(f"Scraping {cat_name} > {sub_name} ...")
                        items = scrape_section_pages(session, sub_data["url"])
                        for item in items:
                            item["category"] = cat_name
                            item["subcategory"] = sub_name
                            item["city"] = None
                        print(f"  -> {len(items)} products")
                        all_items.extend(items)
            else:
                print(f"Scraping {cat_name} ...")
                items = scrape_section_pages(session, cat_data["url"])
                for item in items:
                    item["category"] = cat_name
                    item["subcategory"] = None
                    item["city"] = None
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
