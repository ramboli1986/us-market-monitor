#!/usr/bin/env python3
"""
Fetch upcoming US economic events and earnings dates, generate events.json.
Sources:
  - OpenAI API (gpt-4.1-mini): economic calendar events (FOMC, CPI, PPI, NFP, PCE, GDP, Retail, PMI)
  - Alpha Vantage: earnings dates for key companies
Run via GitHub Actions every 5 days.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from openai import OpenAI

# ── Config ──────────────────────────────────────────────────
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'public', 'events.json')
MONTHS_AHEAD = 4  # generate events for next 4 months

WATCH_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA',
    'JPM', 'GS', 'BAC', 'MS', 'WFC', 'C'
]

TICKER_NAMES = {
    'AAPL': 'Apple（AAPL）', 'MSFT': 'Microsoft（MSFT）',
    'GOOGL': 'Alphabet（GOOGL）', 'GOOG': 'Alphabet（GOOG）',
    'AMZN': 'Amazon（AMZN）', 'META': 'Meta（META）',
    'NVDA': 'NVIDIA（NVDA）', 'TSLA': 'Tesla（TSLA）',
    'JPM': '摩根大通（JPM）', 'GS': '高盛（GS）',
    'BAC': '美国银行（BAC）', 'MS': '摩根士丹利（MS）',
    'WFC': '富国银行（WFC）', 'C': '花旗集团（C）',
}

TIME_MAP = {
    'pre-market': '盘前', 'post-market': '盘后', '': '待定'
}


def fetch_economic_events():
    """Use OpenAI API to generate accurate economic calendar events."""
    client = OpenAI()
    today = datetime.now()
    start = today.strftime('%Y-%m-%d')
    end = (today + timedelta(days=30 * MONTHS_AHEAD)).strftime('%Y-%m-%d')

    prompt = f"""You are a financial data expert. Generate a JSON array of major US economic events from {start} to {end}.

IMPORTANT RULES:
1. Use the ACTUAL scheduled dates based on known patterns:
   - NFP (Non-Farm Payrolls): First Friday of each month, 08:30 ET
   - CPI: Usually around 10th-13th of each month, 08:30 ET
   - PPI: Usually 1-2 days before or after CPI, 08:30 ET
   - PCE: Last Friday of each month (or near end), 08:30 ET
   - FOMC: Check the 2026 FOMC schedule (Jan 28-29, Mar 18-19, May 6-7, Jun 17-18, Jul 29-30, Sep 16-17, Nov 4-5, Dec 16-17)
   - GDP: End of month (advance/preliminary/final), 08:30 ET
   - Retail Sales: Around 15th of each month, 08:30 ET
   - ISM PMI: First business day of each month, 10:00 ET
2. FOMC meetings are 2-day meetings; use the second day (announcement day) as the date.
3. Only include events that fall within the date range.

For each event provide these exact fields:
- "date": "YYYY-MM-DD"
- "type": one of "fomc", "cpi", "ppi", "nfp", "pce", "gdp", "retail", "pmi"
- "title": Chinese title (e.g. "非农就业报告（4月）")
- "desc": Chinese brief description
- "time": time string (e.g. "08:30 ET") or empty string for FOMC

Output ONLY the raw JSON array, no markdown, no explanation."""

    resp = client.chat.completions.create(
        model='gpt-4.1-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.2,
        max_tokens=4000,
    )

    content = resp.choices[0].message.content.strip()
    # Remove markdown code fences if present
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()

    events = json.loads(content)
    print(f"  [Economic] Generated {len(events)} events")
    return events


def fetch_earnings_events():
    """Fetch earnings dates from Alpha Vantage for key companies."""
    import urllib.request

    url = 'https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=demo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            csv_data = resp.read().decode('utf-8')
    except Exception as e:
        print(f"  [Earnings] Error fetching: {e}")
        return []

    lines = csv_data.strip().split('\n')
    if len(lines) < 2:
        print("  [Earnings] No data returned")
        return []

    headers = lines[0].split(',')
    events = []
    seen = set()

    for line in lines[1:]:
        fields = line.split(',')
        if len(fields) < len(headers):
            continue
        row = dict(zip(headers, fields))
        symbol = row.get('symbol', '').strip()

        if symbol not in WATCH_TICKERS or symbol in seen:
            continue
        # Skip GOOG if GOOGL already added
        if symbol == 'GOOG' and 'GOOGL' in seen:
            continue
        if symbol == 'GOOGL' and 'GOOG' in seen:
            continue
        seen.add(symbol)

        report_date = row.get('reportDate', '').strip()
        time_raw = row.get('timeOfTheDay', '').strip().lower()
        time_label = TIME_MAP.get(time_raw, time_raw or '待定')
        name = TICKER_NAMES.get(symbol, symbol)
        eps = row.get('estimate', '').strip()

        desc = f"财报发布，{time_label}"
        if eps:
            desc += f"，预期EPS: ${eps}"

        events.append({
            'date': report_date,
            'type': 'earnings',
            'title': f'{name}财报',
            'desc': desc,
            'time': time_label,
        })

    print(f"  [Earnings] Found {len(events)} upcoming earnings")
    return events


def main():
    print("Fetching economic events...")
    econ_events = fetch_economic_events()

    print("Fetching earnings events...")
    earnings_events = fetch_earnings_events()

    # Merge and sort
    all_events = econ_events + earnings_events
    all_events.sort(key=lambda e: e['date'])

    # Remove duplicates (same date + same type)
    seen_keys = set()
    unique = []
    for e in all_events:
        key = f"{e['date']}_{e['type']}_{e.get('title', '')[:10]}"
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(e)

    output = {
        'updated_at': datetime.now().isoformat(),
        'count': len(unique),
        'events': unique,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done! Wrote {len(unique)} events to {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
