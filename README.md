# Weather Dashboard — IMILLM1 Cypress Gardens

A personal weather dashboard for the Weather Underground personal weather
station **IMILLM1** (Cypress Gardens, Queensland). A Python script pulls the
station's daily history into a CSV, a second script embeds that CSV into a
single self-contained `index.html`, and the page is published with GitHub
Pages.

Live site: <https://freo1995.github.io/weather-dashboard>

## How it works

```
Weather Underground API
        │  wunderground_scraper.py
        ▼
IMILLM1_weather_data.csv
        │  embed_data.py
        ▼
index.html  ──git push──▶  GitHub Pages
```

`update_weather.command` runs all three steps in one go.

## Files

| File | Purpose |
| --- | --- |
| `wunderground_scraper.py` | Fetches daily summaries from the Weather Underground API and merges them into the CSV. |
| `embed_data.py` | Rewrites the `const EMBEDDED = {...};` line in `index.html` with the CSV contents as compact JSON. |
| `update_weather.command` | Double-clickable macOS script: scrape, embed, commit, push. |
| `IMILLM1_weather_data.csv` | The data set — one row per day, from 18/06/2021 onwards. |
| `index.html` | The dashboard. Data is embedded, so it needs no server or build step. |
| `.wu_api_key_cache` | Locally cached API key (gitignored, created automatically). |

## Setup

Requires Python 3.9 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas python-dateutil
chmod +x update_weather.command
```

`embed_data.py` uses only the standard library.

## Updating the data

### The usual way

Double-click `update_weather.command` in Finder. It will:

1. Activate `.venv`
2. Run the scraper, accepting the default start date
3. Embed the refreshed CSV into `index.html`
4. Commit `IMILLM1_weather_data.csv` and `index.html` as
   `Update weather data YYYY-MM-DD` and push to `origin main`

If nothing changed, it skips the commit. The live site updates about a minute
after the push.

### Step by step

```bash
source .venv/bin/activate
python wunderground_scraper.py   # prompts for a start date
python embed_data.py
git add IMILLM1_weather_data.csv index.html
git commit -m "Update weather data $(date +%Y-%m-%d)"
git push origin main
```

The scraper asks for a start date in `DD/MM/YYYY` format. Pressing Enter uses
the default: the first of the month containing the last date already in the
CSV, or five years ago if there is no CSV yet. Whatever date you enter is
rounded back to the first of its month, and data is fetched from there to
today.

Fetched days overwrite any existing rows with the same date, so re-running is
safe and a partial month gets filled in on the next run.

## Data source

The scraper calls the JSON API that the Weather Underground website itself
uses:

```
https://api.weather.com/v2/pws/history/daily
    ?stationId=IMILLM1&format=json&units=e
    &startDate=YYYYMMDD&endDate=YYYYMMDD&apiKey=...
```

- **One request per calendar month.** The API rejects ranges much longer than
  a month. Requests are spaced one second apart.
- **Units.** Values are requested in imperial units and converted to metric in
  the script, which keeps the CSV consistent with data collected by the
  earlier table-scraping version.
- **API key.** The key is not stored in this repository. The scraper reads it
  from the Weather Underground station page source (`SUN_API_KEY`), checks
  that it works, and caches it in `.wu_api_key_cache`. If the cached key is
  later rejected, it looks up the current one automatically.

## CSV format

Dates are `DD/MM/YYYY`. Missing readings are left blank.

| Column | Unit |
| --- | --- |
| `Date`, `Year`, `Month` | — |
| `Temp_High_C`, `Temp_Avg_C`, `Temp_Low_C` | °C |
| `DewPoint_High_C`, `DewPoint_Avg_C`, `DewPoint_Low_C` | °C |
| `Humidity_High_pct`, `Humidity_Avg_pct`, `Humidity_Low_pct` | % |
| `WindSpeed_High_kmh`, `WindSpeed_Avg_kmh`, `WindSpeed_Low_kmh` | km/h |
| `Pressure_High_hPa`, `Pressure_Low_hPa` | hPa |
| `Precip_Total_mm` | mm |

## The dashboard

`index.html` is a single file that loads Chart.js and PapaParse from cdnjs and
has six tabs: Overview, Temperature Trends, Rainfall, Wind, Records &
Anomalies, and Climate Report.

The **Update with new CSV** button loads a CSV into the page in your browser
for that session only. To change what the published site shows, run the
update above.

## Using a different station

Change `STATION_ID` and `OUTPUT_FILE` at the top of `wunderground_scraper.py`,
and `CSV_FILE` in `embed_data.py` to match. The CSV filename is also
referenced in `update_weather.command`, and the station name appears in the
`index.html` title and headings.

## Troubleshooting

- **"Could not find a working Weather Underground API key"** — the site has
  probably changed how it exposes the key. Open
  <https://www.wunderground.com/dashboard/pws/IMILLM1> in a browser, view
  source, and search for `SUN_API_KEY`. A working 32-character key can be
  saved in `.wu_api_key_cache`.
- **"Could not find 'const EMBEDDED = ' in index.html"** — the embedded data
  line was removed or reformatted. It must start a line of its own.
- **A month shows `○ no data`** — the station reported nothing for that month.
- **Git push failed** — check your GitHub credentials with `git remote -v`.
