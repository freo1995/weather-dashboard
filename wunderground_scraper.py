"""
Weather Underground PWS Scraper
Station: IMILLM1 (Cypress Gardens, Queensland)

Asks for a start date at runtime, pulls data up to today, and saves to CSV.
If an existing CSV is present it merges new data in, overwriting any days
that already exist and appending new ones.

Data source
-----------
Weather Underground replaced its website with a new single-page app in
2026. The new dashboard no longer renders the monthly "Table" view at all,
so the old approach (drive a browser, click the Table tab, parse the HTML
table) has nothing left to parse.

Instead we call the same JSON API the site itself uses:

    https://api.weather.com/v2/pws/history/daily
        ?stationId=...&format=json&units=e
        &startDate=YYYYMMDD&endDate=YYYYMMDD&apiKey=...

This needs no browser and no HTML parsing, so it is both much faster and
far less likely to break the next time the site is restyled. Values are
requested in imperial units and converted here, which reproduces exactly
what the old table-scraping code recorded.

Requirements:
    pip install pandas python-dateutil

Usage:
    python wunderground_scraper.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from calendar import monthrange
from datetime import date
from dateutil.relativedelta import relativedelta

import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────────
STATION_ID  = "IMILLM1"
OUTPUT_FILE = "IMILLM1_weather_data.csv"
DELAY_SECS  = 1

HISTORY_URL = "https://api.weather.com/v2/pws/history/daily"

# The site embeds its own API key in its page source — we scrape it rather
# than hardcode it here, since it is not ours to publish and the site can
# rotate it at any time. The key we find is cached locally (API_KEY_CACHE,
# gitignored) so normal runs don't have to re-fetch the page every time.
API_KEY_CACHE = ".wu_api_key_cache"

# The classic site is still served when this cookie is set, and its page
# source is where the API key is easiest to find.
LEGACY_PAGE   = f"https://www.wunderground.com/dashboard/pws/{STATION_ID}"
LEGACY_COOKIE = "wu_prefer_legacy=true"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

# The API rejects ranges longer than about a month, so we request one
# calendar month per call.

# ── Unit conversion ────────────────────────────────────────────────────────────
def f_to_c(v):
    return round((v - 32) * 5 / 9, 2) if v is not None else None

def mph_to_kmh(v):
    return round(v * 1.60934, 2) if v is not None else None

def inhg_to_hpa(v):
    return round(v * 33.8639, 2) if v is not None else None

def in_to_mm(v):
    return round(v * 25.4, 2) if v is not None else None

# ── HTTP ───────────────────────────────────────────────────────────────────────
def http_get(url: str, cookie: str = None, timeout: int = 30) -> str:
    """GET a URL and return the body as text. Raises on HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def api_key_works(key: str) -> bool:
    """Cheap probe: ask for a single recent day and see if we are authorised."""
    probe_day = (date.today() - relativedelta(days=2)).strftime("%Y%m%d")
    url = (
        f"{HISTORY_URL}?stationId={STATION_ID}&format=json&units=e"
        f"&date={probe_day}&apiKey={key}"
    )
    try:
        http_get(url, timeout=20)
        return True
    except urllib.error.HTTPError as e:
        # 401 means the key is no longer authorised for this product.
        # Anything else (e.g. 204 no data for that day) means the key is fine.
        return e.code != 401
    except Exception:
        return False

def discover_api_keys() -> list:
    """Scrape the current API key out of the Weather Underground page source."""
    try:
        html = http_get(LEGACY_PAGE, cookie=LEGACY_COOKIE, timeout=40)
    except Exception as e:
        print(f"  ⚠  Could not load {LEGACY_PAGE}: {e}")
        return []

    keys = []
    # The site defines it as SUN_API_KEY, and also uses it in apiKey=... URLs.
    for pattern in (r"SUN_API_KEY[^0-9a-f]{0,20}([0-9a-f]{32})",
                    r"apiKey=([0-9a-f]{32})"):
        for k in re.findall(pattern, html):
            if k not in keys:
                keys.append(k)
    return keys

def resolve_api_key() -> str:
    """
    Return a working API key. Tries the locally cached key first (so most
    runs make no extra request); if that's missing or no longer works, it
    re-scrapes the key from the site and refreshes the cache.
    """
    cached = None
    if os.path.exists(API_KEY_CACHE):
        try:
            cached = open(API_KEY_CACHE).read().strip() or None
        except Exception:
            cached = None

    if cached and api_key_works(cached):
        return cached

    if cached:
        print("  ⚠  Cached API key was rejected — looking up the current one...")
    else:
        print("  Looking up the current Weather Underground API key...")

    for key in discover_api_keys():
        if key != cached and api_key_works(key):
            try:
                with open(API_KEY_CACHE, "w") as f:
                    f.write(key)
            except Exception:
                pass
            return key

    print("\n✗  Could not find a working Weather Underground API key.")
    print("   The site may have changed again. Open this page in a browser,")
    print("   view source, and search for 'SUN_API_KEY':")
    print(f"   {LEGACY_PAGE}")
    sys.exit(1)

# ── Date prompt ────────────────────────────────────────────────────────────────
def prompt_start_date() -> date:
    """
    Ask the user for a start date.
    Accepts DD/MM/YYYY or DD/MM/YY.
    Pressing Enter with no input defaults to the last day of data in the
    existing CSV (if it exists), or 5 years ago.
    """
    default = None

    # Try to find the last date in the existing CSV
    if os.path.exists(OUTPUT_FILE):
        try:
            df_existing = pd.read_csv(OUTPUT_FILE)
            if not df_existing.empty and 'Date' in df_existing.columns:
                last = df_existing['Date'].iloc[-1]
                parts = last.split('/')
                if len(parts) == 3:
                    # Stored as DD/MM/YYYY
                    last_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
                    # Start from the month of the last date so we re-scrape it
                    # (in case that month was partial)
                    default = last_date.replace(day=1)
                    print(f"  Existing CSV found. Last date: {last} ({last_date})")
        except Exception:
            pass

    if default is None:
        default = date.today().replace(day=1) - relativedelta(years=5)

    print(f"\n  Default start date: {default.strftime('%d/%m/%Y')} (start of that month)")
    print("  Enter a date in DD/MM/YYYY format, or press Enter to use the default.")

    while True:
        raw = input("  Start date [DD/MM/YYYY]: ").strip()
        if not raw:
            print(f"  Using default: {default.strftime('%d/%m/%Y')}")
            return default.replace(day=1)
        try:
            parts = raw.split('/')
            if len(parts) != 3:
                raise ValueError
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            parsed = date(y, m, d)
            return parsed.replace(day=1)  # always scrape from the 1st of that month
        except Exception:
            print("  ✗ Invalid format. Please use DD/MM/YYYY (e.g. 01/06/2023)")

# ── Per-month fetch ────────────────────────────────────────────────────────────
def scrape_month(api_key: str, year: int, month: int) -> list:
    """Fetch one calendar month of daily summaries and map them to CSV rows."""
    first = date(year, month, 1)
    last  = date(year, month, monthrange(year, month)[1])
    # Don't ask for days that haven't happened yet.
    last  = min(last, date.today())
    if last < first:
        return []

    url = (
        f"{HISTORY_URL}?stationId={STATION_ID}&format=json&units=e"
        f"&startDate={first:%Y%m%d}&endDate={last:%Y%m%d}&apiKey={api_key}"
    )

    try:
        body = http_get(url, timeout=40)
    except urllib.error.HTTPError as e:
        if e.code == 204:           # no observations for this range
            return []
        raise

    if not body.strip():
        return []

    observations = json.loads(body).get("observations") or []

    rows = []
    for obs in observations:
        imp = obs.get("imperial") or {}

        def i(field):
            return imp.get(field)

        # obsTimeLocal looks like "2026-09-09 23:59:59"
        local = obs.get("obsTimeLocal") or ""
        try:
            y, m, d = local[:10].split("-")
            au_date = f"{int(d):02d}/{int(m):02d}/{y}"
            row_year, row_month = int(y), int(m)
        except Exception:
            continue

        rows.append({
            "Date":               au_date,
            "Year":               row_year,
            "Month":              row_month,
            "Temp_High_C":        f_to_c(i("tempHigh")),
            "Temp_Avg_C":         f_to_c(i("tempAvg")),
            "Temp_Low_C":         f_to_c(i("tempLow")),
            "DewPoint_High_C":    f_to_c(i("dewptHigh")),
            "DewPoint_Avg_C":     f_to_c(i("dewptAvg")),
            "DewPoint_Low_C":     f_to_c(i("dewptLow")),
            "Humidity_High_pct":  obs.get("humidityHigh"),
            "Humidity_Avg_pct":   obs.get("humidityAvg"),
            "Humidity_Low_pct":   obs.get("humidityLow"),
            "WindSpeed_High_kmh": mph_to_kmh(i("windspeedHigh")),
            "WindSpeed_Avg_kmh":  mph_to_kmh(i("windspeedAvg")),
            "WindSpeed_Low_kmh":  mph_to_kmh(i("windspeedLow")),
            "Pressure_High_hPa":  inhg_to_hpa(i("pressureMax")),
            "Pressure_Low_hPa":   inhg_to_hpa(i("pressureMin")),
            "Precip_Total_mm":    in_to_mm(i("precipTotal")),
        })

    return rows

# ── Merge with existing CSV ────────────────────────────────────────────────────
def merge_with_existing(new_rows: list) -> pd.DataFrame:
    """
    Load existing CSV (if any), merge new rows in.
    New data overwrites existing rows with the same date.
    """
    new_df = pd.DataFrame(new_rows)

    if not os.path.exists(OUTPUT_FILE):
        return new_df

    try:
        existing_df = pd.read_csv(OUTPUT_FILE)
        print(f"\n  Merging with existing CSV ({len(existing_df)} rows)...")

        # Use Date as the key — new rows overwrite old ones
        combined = pd.concat([existing_df, new_df])
        combined = combined.drop_duplicates(subset='Date', keep='last')

        # Sort by date (DD/MM/YYYY → parse for sorting)
        def parse_au_date(d):
            try:
                parts = str(d).split('/')
                return pd.Timestamp(int(parts[2]), int(parts[1]), int(parts[0]))
            except Exception:
                return pd.NaT

        combined['_sort'] = combined['Date'].apply(parse_au_date)
        combined = combined.sort_values('_sort').drop(columns='_sort')
        combined = combined.reset_index(drop=True)

        added   = len(combined) - len(existing_df)
        updated = len(new_df) - max(0, added)
        print(f"  ✓ {updated} days updated, {max(0,added)} new days added")
        return combined

    except Exception as e:
        print(f"  ⚠  Could not merge with existing CSV: {e}")
        print("     Saving new data only.")
        return new_df

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"  Weather Underground Scraper")
    print(f"  Station : {STATION_ID}")
    print(f"  Output  : {OUTPUT_FILE}")
    print(f"{'='*60}")

    start_date = prompt_start_date()
    end_date   = date.today().replace(day=1)

    # Count months
    total_months = 0
    c = start_date
    while c <= end_date:
        total_months += 1
        c += relativedelta(months=1)

    print(f"\n  Scraping : {start_date.strftime('%d/%m/%Y')} → today")
    print(f"  Months   : {total_months}")
    print(f"  Units    : Metric (°C, km/h, hPa, mm)")
    print(f"{'='*60}\n")

    print("  Checking Weather Underground API access...")
    api_key = resolve_api_key()
    print("  ✓ API access OK\n")

    all_rows = []
    current  = start_date

    month_num = 0
    while current <= end_date:
        month_num += 1
        print(f"[{month_num:02d}/{total_months}] {current.year}-{current.month:02d} ...", end=" ", flush=True)

        try:
            rows = scrape_month(api_key, current.year, current.month)
            all_rows.extend(rows)
            print(f"✓ {len(rows)} days" if rows else "○ no data")
        except Exception as e:
            print(f"✗ {e}")

        current += relativedelta(months=1)
        if current <= end_date:
            time.sleep(DELAY_SECS)

    if not all_rows:
        print("\n⚠  No data collected.")
        return

    # Merge and save
    df = merge_with_existing(all_rows)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"\n{'='*60}")
    print(f"✅  Done!  {len(df)} total rows saved to '{OUTPUT_FILE}'")
    print(f"{'='*60}")
    print(f"\nPreview (last 3 rows):\n{df.tail(3).to_string()}")

if __name__ == "__main__":
    main()
