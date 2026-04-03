#!/usr/bin/env python3
"""
Fetch financial news from CNBC RSS feeds and translate to Chinese.
Uses MyMemory free translation API (no API key required).
Outputs: public/news.json
"""

import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── RSS Sources ──────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "category": "综合", "source": "CNBC TOP NEWS"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",  "category": "经济", "source": "CNBC ECONOMY"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",  "category": "金融", "source": "CNBC FINANCE"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",  "category": "科技", "source": "CNBC TECHNOLOGY"},
]

OUTPUT_PATH = Path(__file__).parent.parent / "public" / "news.json"

# ── Helpers ──────────────────────────────────────────────────

def fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    """Parse RSS feed and return list of items."""
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            # strip HTML tags from description
            import re
            desc = re.sub(r"<[^>]+>", "", desc).strip()
            if title:
                items.append({"title": title, "desc": desc[:200], "link": link, "pubDate": pub})
    except Exception as e:
        print(f"  RSS error {url[:60]}: {e}")
    return items


def translate_mymemory(text: str, retries: int = 3) -> str:
    """Translate English text to Chinese using MyMemory free API."""
    if not text or not text.strip():
        return text
    # Truncate to avoid API limits (500 chars max per request)
    text = text[:480]
    encoded = urllib.parse.quote(text)
    url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|zh"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data.get("responseStatus") == 200:
                translated = data["responseData"]["translatedText"]
                # MyMemory sometimes returns the original if it can't translate
                if translated and translated != text:
                    return translated
        except Exception as e:
            print(f"    Translation attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return text  # fallback to original


def parse_pub_date(pub_date: str) -> str:
    """Convert RSS pubDate to ISO format string."""
    if not pub_date:
        return datetime.now(timezone.utc).isoformat()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_date, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()


def relative_time(iso_str: str) -> str:
    """Return human-readable relative time string in Chinese."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return "刚刚"
        elif diff < 3600:
            return f"{diff // 60}分钟前"
        elif diff < 86400:
            return f"{diff // 3600}小时前"
        else:
            return f"{diff // 86400}天前"
    except Exception:
        return ""


# ── Main ─────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting news fetch...")

    # Load existing cache to avoid re-translating
    existing_cache: dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        try:
            old_data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            for item in old_data.get("items", []):
                if item.get("link"):
                    existing_cache[item["link"]] = item
            print(f"  Loaded {len(existing_cache)} cached items")
        except Exception as e:
            print(f"  Cache load error: {e}")

    all_items = []
    seen_links = set()

    for feed in RSS_FEEDS:
        print(f"  Fetching {feed['source']}...")
        raw_items = fetch_rss(feed["url"])
        print(f"    Got {len(raw_items)} items")

        for raw in raw_items[:15]:  # max 15 per feed
            link = raw["link"]
            if link in seen_links:
                continue
            seen_links.add(link)

            pub_iso = parse_pub_date(raw["pubDate"])

            # Use cache if available
            if link in existing_cache:
                cached = existing_cache[link]
                cached["relativeTime"] = relative_time(pub_iso)
                all_items.append(cached)
                continue

            # Translate title and description
            print(f"    Translating: {raw['title'][:50]}...")
            title_zh = translate_mymemory(raw["title"])
            time.sleep(0.3)  # rate limit
            desc_zh = translate_mymemory(raw["desc"]) if raw["desc"] else ""
            time.sleep(0.3)

            item = {
                "title_en": raw["title"],
                "title_zh": title_zh,
                "desc_en": raw["desc"],
                "desc_zh": desc_zh,
                "link": link,
                "pubDate": pub_iso,
                "relativeTime": relative_time(pub_iso),
                "category": feed["category"],
                "source": feed["source"],
            }
            all_items.append(item)

    # Sort by pubDate descending
    all_items.sort(key=lambda x: x.get("pubDate", ""), reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_items),
        "items": all_items,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Saved {len(all_items)} items to {OUTPUT_PATH}")
    print("Done!")


if __name__ == "__main__":
    main()
