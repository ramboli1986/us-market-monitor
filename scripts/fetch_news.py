#!/usr/bin/env python3
"""
Fetch international news + Product Hunt daily products, translate to Chinese.
Sources:
  - BBC World News RSS
  - Google News Top Stories RSS
  - CNBC Top News RSS (kept for financial coverage)
  - Product Hunt Atom Feed (daily products)
Translation: Google Translate unofficial API (free, no key needed)
Outputs: public/news.json
"""

import json
import re
import time
import html as html_mod
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── RSS Sources ──────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "国际", "source": "BBC World"},
    {"url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "category": "头条", "source": "Google News"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "category": "财经", "source": "CNBC"},
    {"url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "category": "科技", "source": "BBC Tech"},
]

PH_FEED_URL = "https://www.producthunt.com/feed"

OUTPUT_PATH = Path(__file__).parent.parent / "public" / "news.json"

# ── Translation ──────────────────────────────────────────────

def translate_google(text: str) -> str:
    """Translate English to Chinese using Google Translate unofficial API."""
    if not text or not text.strip():
        return text
    text = text[:500]
    try:
        encoded = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = "".join(seg[0] for seg in data[0] if seg[0])
        return result if result else text
    except Exception as e:
        print(f"    Translation error: {e}")
        return text


def batch_translate(texts: list[str], max_workers: int = 8) -> list[str]:
    """Translate multiple texts in parallel."""
    results = [""] * len(texts)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(translate_google, t): i for i, t in enumerate(texts)}
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = texts[idx]
    return results


# ── RSS Parsing ──────────────────────────────────────────────

def decode_html(text: str) -> str:
    """Decode HTML entities and strip tags."""
    text = html_mod.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    """Parse RSS feed and return list of items."""
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = decode_html(item.findtext("title") or "")
            desc = decode_html(item.findtext("description") or "")
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            # Try to get image from media:thumbnail or media:content
            img = ""
            for ns_prefix in ["media", "{http://search.yahoo.com/mrss/}"]:
                for tag in ["thumbnail", "content"]:
                    el = item.find(f"{ns_prefix}:{tag}" if ":" not in ns_prefix else f"{ns_prefix}{tag}")
                    if el is not None and el.get("url"):
                        img = el.get("url")
                        break
                if img:
                    break
            if title:
                items.append({
                    "title": title,
                    "desc": desc[:200],
                    "link": link,
                    "pubDate": pub,
                    "image": img,
                })
    except Exception as e:
        print(f"  RSS error {url[:60]}: {e}")
    return items


def fetch_producthunt(timeout: int = 15) -> list[dict]:
    """Fetch Product Hunt Atom feed."""
    items = []
    try:
        req = urllib.request.Request(PH_FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            published = (entry.findtext("atom:published", namespaces=ns) or "").strip()
            content_raw = entry.findtext("atom:content", namespaces=ns) or ""
            desc = decode_html(content_raw).split("\n")[0].strip()
            # Extract post ID from entry id
            entry_id = entry.findtext("atom:id", namespaces=ns) or ""
            post_id = ""
            m = re.search(r"Post/(\d+)", entry_id)
            if m:
                post_id = m.group(1)
            # Extract product link (the actual product URL)
            product_url = ""
            urls = re.findall(r'href="([^"]+)"', html_mod.unescape(content_raw))
            for u in urls:
                if "/r/p/" in u:
                    product_url = u
                    break
            # Use Product Hunt SVG badge as image
            badge_url = f"https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id={post_id}&theme=dark" if post_id else ""
            # Try to follow redirect to get real product domain for favicon
            favicon_url = ""
            if product_url:
                try:
                    req2 = urllib.request.Request(product_url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
                    with urllib.request.urlopen(req2, timeout=5) as resp2:
                        real_url = resp2.url
                    domain = urllib.parse.urlparse(real_url).netloc
                    if domain and "producthunt" not in domain:
                        favicon_url = f"https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=128"
                except Exception:
                    pass
            # Fallback: use PH favicon
            if not favicon_url:
                favicon_url = "https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://producthunt.com&size=128"
            if title:
                items.append({
                    "title": title,
                    "desc": desc,
                    "link": link,
                    "pubDate": published,
                    "image": badge_url,
                    "favicon": favicon_url,
                    "post_id": post_id,
                    "product_url": product_url,
                })
    except Exception as e:
        print(f"  Product Hunt error: {e}")
    return items


# ── Date Parsing ─────────────────────────────────────────────

def parse_pub_date(pub_date: str) -> str:
    """Convert RSS pubDate to ISO format string."""
    if not pub_date:
        return datetime.now(timezone.utc).isoformat()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_date, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    # Try ISO format with timezone offset like -07:00
    try:
        dt = datetime.fromisoformat(pub_date)
        return dt.isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def relative_time(iso_str: str) -> str:
    """Return human-readable relative time string in Chinese."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 0:
            return "刚刚"
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

    # ── Fetch RSS News ──
    for feed in RSS_FEEDS:
        print(f"  Fetching {feed['source']}...")
        raw_items = fetch_rss(feed["url"])
        print(f"    Got {len(raw_items)} items")

        # Collect items that need translation
        new_items = []
        for raw in raw_items[:15]:
            link = raw["link"]
            if link in seen_links:
                continue
            seen_links.add(link)
            pub_iso = parse_pub_date(raw["pubDate"])

            if link in existing_cache:
                cached = existing_cache[link]
                cached["relativeTime"] = relative_time(pub_iso)
                all_items.append(cached)
            else:
                new_items.append((raw, pub_iso, feed))

        if new_items:
            # Batch translate titles and descriptions
            titles = [item[0]["title"] for item in new_items]
            descs = [item[0]["desc"] for item in new_items]
            print(f"    Translating {len(titles)} new items...")
            titles_zh = batch_translate(titles)
            descs_zh = batch_translate(descs)

            for i, (raw, pub_iso, feed_info) in enumerate(new_items):
                item = {
                    "title_en": raw["title"],
                    "title_zh": titles_zh[i],
                    "desc_en": raw["desc"],
                    "desc_zh": descs_zh[i],
                    "link": raw["link"],
                    "pubDate": pub_iso,
                    "relativeTime": relative_time(pub_iso),
                    "category": feed_info["category"],
                    "source": feed_info["source"],
                    "image": raw.get("image", ""),
                    "type": "news",
                }
                all_items.append(item)

    # ── Fetch Product Hunt ──
    print(f"  Fetching Product Hunt...")
    ph_items = fetch_producthunt()
    print(f"    Got {len(ph_items)} products")

    ph_new = []
    for raw in ph_items[:20]:
        link = raw["link"]
        if link in seen_links:
            continue
        seen_links.add(link)
        pub_iso = parse_pub_date(raw["pubDate"])

        if link in existing_cache:
            cached = existing_cache[link]
            cached["relativeTime"] = relative_time(pub_iso)
            all_items.append(cached)
        else:
            ph_new.append((raw, pub_iso))

    if ph_new:
        # Only translate descriptions, keep product names in English
        descs = [item[0]["desc"] for item in ph_new]
        print(f"    Translating {len(descs)} Product Hunt descriptions...")
        descs_zh = batch_translate(descs)

        for i, (raw, pub_iso) in enumerate(ph_new):
            # Build favicon URL from product_url domain
            favicon = raw.get("favicon", "")
            if not favicon and raw.get("product_url"):
                try:
                    domain = urllib.parse.urlparse(raw["product_url"]).netloc
                    if domain:
                        favicon = f"https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=128"
                except Exception:
                    pass
            item = {
                "title_en": raw["title"],
                "title_zh": raw["title"],  # Keep product name as-is
                "desc_en": raw["desc"],
                "desc_zh": descs_zh[i],
                "link": raw["link"],
                "pubDate": pub_iso,
                "relativeTime": relative_time(pub_iso),
                "category": "Product Hunt",
                "source": "Product Hunt",
                "image": raw.get("image", ""),
                "favicon": favicon or raw.get("favicon", ""),
                "post_id": raw.get("post_id", ""),
                "product_url": raw.get("product_url", ""),
                "type": "product",
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
