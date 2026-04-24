"""
Weather Underground PWS Scraper
Station: IMILLM1 (Cypress Gardens, Queensland)

Asks for a start date at runtime, scrapes to today, and saves to CSV.
If an existing CSV is provided it merges new data in, overwriting any
days that already exist and appending new ones.

Requirements:
    pip install playwright beautifulsoup4 pandas python-dateutil
    playwright install chromium

Usage:
    python wunderground_scraper.py
"""

import re
import sys
import time
from datetime import date
from dateutil.relativedelta import relativedelta

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ── Configuration ──────────────────────────────────────────────────────────────
STATION_ID  = "IMILLM1"
OUTPUT_FILE = "IMILLM1_weather_data.csv"
DELAY_SECS  = 3

# ── Helpers ────────────────────────────────────────────────────────────────────
def parse_num(text: str):
    text = text.replace("\xa0", "").strip()
    if text in ("--", "", "N/A"):
        return None
    m = re.search(r"[-+]?\d+\.?\d*", text)
    return float(m.group()) if m else None

def f_to_c(v):
    return round((v - 32) * 5 / 9, 2) if v is not None else None

def mph_to_kmh(v):
    return round(v * 1.60934, 2) if v is not None else None

def inhg_to_hpa(v):
    return round(v * 33.8639, 2) if v is not None else None

def in_to_mm(v):
    return round(v * 25.4, 2) if v is not None else None

def count_date_rows(page) -> int:
    return page.evaluate("""
        () => {
            let count = 0;
            document.querySelectorAll('td').forEach(td => {
                if (td.textContent.includes('/')) count++;
            });
            return count;
        }
    """)

def wait_for_stable_rows(page, timeout=30) -> int:
    prev_count   = -1
    stable_ticks = 0
    deadline     = time.time() + timeout
    while time.time() < deadline:
        count = count_date_rows(page)
        if count > 0 and count == prev_count:
            stable_ticks += 1
            if stable_ticks >= 2:
                return count
        else:
            stable_ticks = 0
        prev_count = count
        time.sleep(1)
    return prev_count

# ── Date prompt ────────────────────────────────────────────────────────────────
def prompt_start_date() -> date:
    """
    Ask the user for a start date.
    Accepts DD/MM/YYYY or DD/MM/YY.
    Pressing Enter with no input defaults to the last day of data in the
    existing CSV (if it exists), or 5 years ago.
    """
    import os

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

# ── Per-month scraper ──────────────────────────────────────────────────────────
def scrape_month(page, year: int, month: int) -> list[dict]:
    url = (
        f"https://www.wunderground.com/dashboard/pws/{STATION_ID}"
        f"/table/{year}-{month:02d}-01/{year}-{month:02d}-01/monthly"
    )

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(5)

    # Click the Table tab
    try:
        tab = page.locator("a", has_text="Table").first
        tab.scroll_into_view_if_needed()
        tab.click(force=True)
    except Exception:
        try:
            page.evaluate("""
                const links = Array.from(document.querySelectorAll('a'));
                const tab = links.find(l => l.textContent.trim() === 'Table');
                if (tab) tab.click();
            """)
        except Exception:
            pass

    stable_count = wait_for_stable_rows(page, timeout=30)
    if stable_count == 0:
        return []

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Find Table 4 — must have a date AND many data columns
    daily_table = None
    for table in soup.find_all("table"):
        data_rows = [r for r in table.find_all("tr") if r.find("td")]
        if not data_rows:
            continue
        cells = data_rows[0].find_all("td")
        if len(cells) < 10:
            continue
        if "/" in cells[0].get_text():
            daily_table = table
            break

    if daily_table is None:
        return []

    rows = []
    for tr in daily_table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        values = [td.get_text(strip=True).replace("\xa0", "") for td in cells]
        if not values or "/" not in values[0]:
            continue

        nums = [parse_num(v) for v in values]
        def n(i): return nums[i] if i < len(nums) else None

        # Convert US date M/D/YYYY → DD/MM/YYYY
        raw_date = values[0]
        try:
            parts = raw_date.split('/')
            au_date = f"{int(parts[1]):02d}/{int(parts[0]):02d}/{parts[2]}"
        except Exception:
            au_date = raw_date

        rows.append({
            "Date":               au_date,
            "Year":               year,
            "Month":              month,
            "Temp_High_C":        f_to_c(n(1)),
            "Temp_Avg_C":         f_to_c(n(2)),
            "Temp_Low_C":         f_to_c(n(3)),
            "DewPoint_High_C":    f_to_c(n(4)),
            "DewPoint_Avg_C":     f_to_c(n(5)),
            "DewPoint_Low_C":     f_to_c(n(6)),
            "Humidity_High_pct":  n(7),
            "Humidity_Avg_pct":   n(8),
            "Humidity_Low_pct":   n(9),
            "WindSpeed_High_kmh": mph_to_kmh(n(10)),
            "WindSpeed_Avg_kmh":  mph_to_kmh(n(11)),
            "WindSpeed_Low_kmh":  mph_to_kmh(n(12)),
            "Pressure_High_hPa":  inhg_to_hpa(n(13)),
            "Pressure_Low_hPa":   inhg_to_hpa(n(14)),
            "Precip_Total_mm":    in_to_mm(n(15)),
        })

    return rows

# ── Merge with existing CSV ────────────────────────────────────────────────────
def merge_with_existing(new_rows: list[dict]) -> pd.DataFrame:
    """
    Load existing CSV (if any), merge new rows in.
    New data overwrites existing rows with the same date.
    """
    import os

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
    print(f"\n  A browser window will open — you can minimise it.")
    print(f"  Do NOT close it until Done appears below.")
    print(f"{'='*60}\n")

    all_rows = []
    current  = start_date

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        month_num = 0
        while current <= end_date:
            month_num += 1
            print(f"[{month_num:02d}/{total_months}] {current.year}-{current.month:02d} ...", end=" ", flush=True)

            try:
                rows = scrape_month(page, current.year, current.month)
                all_rows.extend(rows)
                print(f"✓ {len(rows)} days" if rows else "○ no data")
            except Exception as e:
                print(f"✗ {e}")

            current += relativedelta(months=1)
            if current <= end_date:
                time.sleep(DELAY_SECS)

        browser.close()

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
