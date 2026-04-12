from bs4 import BeautifulSoup
import pandas as pd
import requests, re, time, random
from urllib.parse import urljoin, urlparse

url = "https://www.gucci.com/us/en/ca/women/handbags-c-women-handbags"


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

response = requests.get(url, headers=HEADERS, timeout=30).text
soup = BeautifulSoup(response, "lxml")

print(soup.prettify())


links = []
for a in soup.select("a[href]"):
    href = a["href"]
    if "/pr/" in href and '-p-' in href:
        full = urljoin(url, href)
        last = urlparse(full).path.rstrip("/").split("/")[-1]
        links.append((href, last, a.get_text(" ", strip=True)[:80]))

print("Found links:", len(links))
for x in links:
    print(x)


SELECTED_KEYS = [
    "A0020YAAGRB1000", 
    "A0022VAAG211096", 
    "853971FAF3Y2155", 
    "866732FAFV99653", 
    "875018AAGIQ1053", 
    "875018FAFV99653", 
    "867360FAF059651",
    "875019AAGIQ1053",
    "866732AAGIQ1053",
    "863137FAFV29651"
    
]


SEEDS = {
    "US": "https://www.gucci.com/us/en/ca/women/handbags-c-women-handbags",
    "FR": "https://www.gucci.com/fr/fr/ca/women/handbags-c-women-handbags",
    "IT": "https://www.gucci.com/it/it/ca/women/handbags-c-women-handbags",
    "CN": "https://www.gucci.cn/zh/ca/women/handbags?navigation.code=0-3-2-0",
}



PRICE_RE = re.compile(r"([€$¥])\s*([0-9][0-9\.,]*)")

def polite_sleep(a=0.6, b=1.2):
    time.sleep(random.uniform(a, b))

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def parse_price(text: str):
    if not text:
        return (None, None)
    t = " ".join(text.split())
    m = PRICE_RE.search(t)
    if not m:
        return (None, None)
    cur, num_raw = m.group(1), m.group(2)

    # normalize "4,100" -> 4100 ; "3.100" -> 3100 (EU thousands)
    if "," in num_raw and "." not in num_raw:
        num = float(num_raw.replace(",", ""))
    elif "." in num_raw and "," not in num_raw:
        parts = num_raw.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            num = float("".join(parts))
        else:
            num = float(num_raw)
    else:
        # Both present: last one is decimal separator (US "1,234.56" vs EU "1.234,56")
        if num_raw.rfind(",") > num_raw.rfind("."):
            num = float(num_raw.replace(".", "").replace(",", "."))
        else:
            num = float(num_raw.replace(",", ""))
    return cur, num

def product_key(u: str) -> str:
    """
    For Gucci, use the stable product ID found after '-p-' in
    the last path segment, e.g. ...-p-853971FAF3Y2155 -> 853971FAF3Y2155.
    """
    path = urlparse(u).path.rstrip("/")
    last = path.split("/")[-1]
    if "-p-" in last:
        return last.split("-p-")[-1].upper()
    return last.upper()




def extract_products_from_category(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    out = {}

    for a in soup.select("a[href]"):
        href = a["href"]
        if "/pr/" not in href or "-p-" not in href:
            continue

        full = urljoin(base_url, href)
        key = product_key(full)

        # Prefer structured fields on the anchor for cleaner data
        name = None
        name_el = a.select_one("span.is-text-s-book")
        if name_el:
            name = name_el.get_text(" ", strip=True)

        if not name:
            aria = a.get("aria-label") or ""
            if aria:
                # e.g. "Gucci Giglio large tote bag, $2,350"
                name = aria.split(",")[0].strip()

        # Price: prefer data-price, then explicit price span, then fallback
        cur = None
        price = None
        price_str = None

        data_price = a.get("data-price")
        if data_price and data_price.isdigit():
            cents = int(data_price)
            price = cents / 100.0
            cur = "$"
            price_str = f"{cur} {price:,.0f}"
        else:
            price_el = a.select_one('[data-testid="price"]')
            if price_el:
                raw = price_el.get_text(" ", strip=True)
                cur_tmp, num_tmp = parse_price(raw)
                if cur_tmp and num_tmp is not None:
                    cur, price = cur_tmp, num_tmp
                    price_str = f"{cur} {price:,.0f}"
            if price is None:
                raw = a.get_text(" ", strip=True)
                cur_tmp, num_tmp = parse_price(raw)
                if cur_tmp and num_tmp is not None:
                    cur, price = cur_tmp, num_tmp
                    price_str = f"{cur} {price:,.0f}"

        # Color from data-colors, e.g. "#8D4F10|Brown"
        color = None
        colors_attr = a.get("data-colors")
        if colors_attr:
            parts = [p for p in colors_attr.split("|") if p]
            if len(parts) >= 2:
                color = parts[1].strip()

        # Build combined title string
        title_parts = []
        if name:
            title_parts.append(name)
        if price_str:
            title_parts.append(price_str)
        if color:
            title_parts.append(color)
        title = " ".join(title_parts) if title_parts else None

        # Store first occurrence per key
        out.setdefault(key, {
            "key": key,
            "product_name": name,
            "currency_symbol": cur,
            "price": price,
            "product_url": full,
            "color": color,
            "title": title,
        })

    return list(out.values())

def get_n_from_seed(seed_url: str, n=10, max_pages=12):
    got, seen = [], set()
    for page in range(1, max_pages + 1):
        url = seed_url if page == 1 else f"{seed_url}?page={page}"
        html = fetch(url)
        items = extract_products_from_category(html, seed_url)

        for it in items:
            if it["key"] not in seen:
                seen.add(it["key"])
                got.append(it)

        if len(got) >= n:
            break

        polite_sleep()

    return got[:n]

def build_pool(seed_url: str, target=300, max_pages=25):
    pool = {}
    for page in range(1, max_pages + 1):
        url = seed_url if page == 1 else f"{seed_url}?page={page}"
        html = fetch(url)
        items = extract_products_from_category(html, seed_url)

        for it in items:
            pool.setdefault(it["key"], it)

        if len(pool) >= target:
            break

        polite_sleep()

    return pool

# 1) Anchor 10 from US
anchors = get_n_from_seed(SEEDS["US"], n=10)
print("US anchors found:", len(anchors))
if len(anchors) == 0:
    raise RuntimeError("Still found 0 anchors. Run Cell A and paste the first few /p/ links so we can target the right markup.")

anchor_keys = SELECTED_KEYS

# 2) Match across countries
rows = []
for country, seed in SEEDS.items():
    print(f"Building pool for {country}...")
    pool = build_pool(seed, target=400, max_pages=10)
    for rank, key in enumerate(anchor_keys, start=1):
        it = pool.get(key)
        rows.append({
            "brand": "Gucci",
            "anchor_rank_us": rank,
            "key": key,
            "country": country,
            "product_name": it["product_name"] if it else None,
            "currency_symbol": it["currency_symbol"] if it else None,
            "price": it["price"] if it else None,
            "product_url": it["product_url"] if it else None,
            "status": "ok_from_category" if it else "not_found_in_country_listing",
        })

df = pd.DataFrame(rows)
out_csv = "data/gucci_10bags_4countries.csv"
df.to_csv(out_csv, index=False)

print("Saved:", out_csv)
print("Shape:", df.shape)
df.head(12)


us_pool = build_pool(SEEDS["US"], target=80, max_pages=10)

us_df = pd.DataFrame(us_pool.values())
us_df[["key", "product_name", "price"]].head(157)
out_csv = "data/gucci_157bags.csv"
us_df.to_csv(out_csv, index=False)