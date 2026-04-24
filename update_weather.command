#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  update_weather.command
#  Double-click this file on your Mac to run the full update.
#
#  What it does:
#    1. Activates the Python virtual environment
#    2. Runs the Weather Underground scraper
#    3. Embeds the new CSV data into index.html
#    4. Commits and pushes to GitHub (live site updates)
#
#  Setup (one time only):
#    chmod +x update_weather.command
# ─────────────────────────────────────────────────────────────────

# Change into the project folder (same folder as this script)
cd "$(dirname "$0")"

echo ""
echo "========================================================"
echo "  Weather Dashboard — Full Update"
echo "  $(date '+%A %d %B %Y, %H:%M')"
echo "========================================================"
echo ""

# ── Step 1: Activate virtual environment ─────────────────────────
echo "→ Activating virtual environment..."
if [ ! -f ".venv/bin/activate" ]; then
    echo "✗  Virtual environment not found at ./venv"
    echo "   Run this first:"
    echo "   python3 -m venv venv && source venv/bin/activate"
    echo "   pip install playwright beautifulsoup4 pandas python-dateutil"
    echo "   playwright install chromium"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi
source .venv/bin/activate
echo "✓  Virtual environment active"
echo ""

# ── Step 2: Run the scraper ───────────────────────────────────────
echo "→ Running Weather Underground scraper..."
echo "   (Auto-detecting last date from CSV — no input needed)"
echo "   (A browser window will open — you can minimise it)"
echo ""

# Pipe an empty line to auto-accept the default start date.
# The scraper reads the last date from IMILLM1_weather_data.csv
# and uses the 1st of that month as the default start date.
echo "" | python wunderground_scraper.py
if [ $? -ne 0 ]; then
    echo ""
    echo "✗  Scraper failed. Check the output above."
    read -p "Press Enter to close..."
    exit 1
fi
echo ""

# ── Step 3: Embed fresh data into index.html ──────────────────────
echo "→ Embedding new data into index.html..."
python embed_data.py
if [ $? -ne 0 ]; then
    echo ""
    echo "✗  embed_data.py failed. Check the output above."
    read -p "Press Enter to close..."
    exit 1
fi
echo ""

# ── Step 4: Git commit and push ───────────────────────────────────
TODAY=$(date '+%Y-%m-%d')
COMMIT_MSG="Update weather data ${TODAY}"

echo "→ Committing and pushing to GitHub..."
echo "   Commit message: \"${COMMIT_MSG}\""
echo ""

git add IMILLM1_weather_data.csv index.html

git diff --cached --quiet
if [ $? -eq 0 ]; then
    echo "  Nothing to commit — data is already up to date."
else
    git commit -m "${COMMIT_MSG}"
    if [ $? -ne 0 ]; then
        echo "✗  Git commit failed."
        read -p "Press Enter to close..."
        exit 1
    fi

    git push
    if [ $? -ne 0 ]; then
        echo ""
        echo "✗  Git push failed."
        echo "   Check you are logged in: git remote -v"
        read -p "Press Enter to close..."
        exit 1
    fi

    echo ""
    echo "========================================================"
    echo "  ✅ Done! Live site will update in ~1 minute."
    echo "  freo1995.github.io/weather-dashboard"
    echo "========================================================"
fi

echo ""
read -p "Press Enter to close..."
