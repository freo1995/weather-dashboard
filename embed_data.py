"""
embed_data.py — Rebuild index.html with fresh weather data embedded

Reads IMILLM1_weather_data.csv, converts it to compact JSON,
and replaces the const EMBEDDED = {...}; line in index.html.

Usage:
    python embed_data.py

Both files must be in the same folder as this script.
"""

import json
import os
import re
import sys
from datetime import datetime

CSV_FILE    = "IMILLM1_weather_data.csv"
HTML_FILE   = "index.html"
EMBED_MARKER = "const EMBEDDED = "

def parse_value(v):
    """Convert a CSV string value to float or None."""
    v = v.strip()
    if v in ("", "None", "nan", "NaN", "--", "N/A"):
        return None
    try:
        return float(v)
    except ValueError:
        return v  # keep as string (e.g. Date)

def read_csv(path):
    """Read CSV manually to avoid pandas dependency."""
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\n\r") for l in f if l.strip()]

    if not lines:
        raise ValueError(f"CSV file is empty: {path}")

    # Header row
    cols = [c.strip() for c in lines[0].split(",")]

    rows = []
    for line in lines[1:]:
        parts = line.split(",")
        # Pad if row is short
        while len(parts) < len(cols):
            parts.append("")
        row = []
        for i, col in enumerate(cols):
            raw = parts[i].strip()
            if col == "Date":
                row.append(raw)
            elif col in ("Year", "Month"):
                try:
                    row.append(int(float(raw)))
                except (ValueError, TypeError):
                    row.append(None)
            else:
                row.append(parse_value(raw))
        rows.append(row)

    return cols, rows

def main():
    # ── Check files exist ──────────────────────────────────────────────────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path   = os.path.join(script_dir, CSV_FILE)
    html_path  = os.path.join(script_dir, HTML_FILE)

    if not os.path.exists(csv_path):
        print(f"✗  CSV not found: {csv_path}")
        sys.exit(1)
    if not os.path.exists(html_path):
        print(f"✗  HTML not found: {html_path}")
        sys.exit(1)

    # ── Read CSV ───────────────────────────────────────────────────────────
    print(f"  Reading {CSV_FILE} ...")
    cols, rows = read_csv(csv_path)
    print(f"  ✓ {len(rows)} rows · {len(cols)} columns")

    # ── Build compact JSON ─────────────────────────────────────────────────
    embedded = {"cols": cols, "rows": rows}
    json_str  = json.dumps(embedded, separators=(",", ":"), ensure_ascii=False)
    new_line  = f"const EMBEDDED = {json_str};\n"

    # ── Read existing HTML ─────────────────────────────────────────────────
    print(f"  Reading {HTML_FILE} ...")
    with open(html_path, "r", encoding="utf-8") as f:
        html_lines = f.readlines()

    # ── Find and replace the EMBEDDED line ────────────────────────────────
    replaced = False
    new_html  = []
    for line in html_lines:
        if line.lstrip().startswith(EMBED_MARKER):
            new_html.append(new_line)
            replaced = True
        else:
            new_html.append(line)

    if not replaced:
        print(f"✗  Could not find '{EMBED_MARKER}' in {HTML_FILE}")
        print("   Make sure index.html still contains the embedded data block.")
        sys.exit(1)

    # ── Write updated HTML ─────────────────────────────────────────────────
    with open(html_path, "w", encoding="utf-8") as f:
        f.writelines(new_html)

    kb = len(new_line) / 1024
    print(f"  ✓ Embedded data updated ({kb:.0f} KB of JSON)")

    # ── Show date range ────────────────────────────────────────────────────
    dates = [r[0] for r in rows if r[0]]
    if dates:
        print(f"  ✓ Date range: {dates[0]} → {dates[-1]}")

    print(f"\n✅ {HTML_FILE} is ready to commit to GitHub.")
    print(f"   Run:\n   git add index.html && git commit -m \"Update weather data $(date +'%Y-%m-%d')\" && git push")

if __name__ == "__main__":
    print(f"\n{'='*55}")
    print(f"  embed_data.py — Weather Dashboard Data Embedder")
    print(f"{'='*55}\n")
    main()
    print()
