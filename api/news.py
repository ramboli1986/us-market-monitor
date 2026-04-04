"""
Vercel Serverless Function: /api/news
Real-time fetch of CNBC RSS feeds with Chinese translation via MyMemory API.
Each call fetches fresh data directly from CNBC RSS.
"""

import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# ── RSS Sources ───────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "category": "综合", "source": "CNBC TOP NEWS"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",  "category": "经济", "source": "CNBC ECONOMY"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",  "category": "金融", "source": "CNBC FINANCE"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",  "category": "科技", "source": "CNBC TECHNOLOGY"},
]

MAX_PER_FEED = 15


def fetch_rss(url: str, timeout: int = 10) -> list:
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            desc = re.sub(r"<[^>]+>", "", desc).strip()
            if title:
                items.append({"title": title, "desc": desc[:200], "link": link, "pubDate": pub})
    except Exception as e:
        print(f"RSS error {url[:60]}: {e}")
    return items


def translate_mymemory(text: str) -> str:
    if not text or not text.strip():
        return text
    text = text[:480]
    encoded = urllib.parse.quote(text)
    url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|zh"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        if data.get("responseStatus") == 200:
            translated = data["responseData"]["translatedText"]
            if translated and translated != text:
                return translated
    except Exception as e:
        print(f"Translation error: {e}")
    return text


def parse_pub_date(pub_date: str) -> str:
    if not pub_date:
        return datetime.now(timezone.utc).isoformat()
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"]:
        try:
            return datetime.strptime(pub_date, fmt).isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()


def relative_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:    return "刚刚"
        if diff < 3600:  return f"{diff // 60}分钟前"
        if diff < 86400: return f"{diff // 3600}小时前"
        return f"{diff // 86400}天前"
    except Exception:
        return ""


def build_news() -> dict:
    all_items = []
    seen_links = set()

    for feed in RSS_FEEDS:
        raw_items = fetch_rss(feed["url"])
        for raw in raw_items[:MAX_PER_FEED]:
            link = raw["link"]
            if link in seen_links:
                continue
            seen_links.add(link)

            pub_iso = parse_pub_date(raw["pubDate"])
            title_zh = translate_mymemory(raw["title"])
            time.sleep(0.2)
            desc_zh = translate_mymemory(raw["desc"]) if raw["desc"] else ""
            time.sleep(0.2)

            all_items.append({
                "title_en": raw["title"],
                "title_zh": title_zh,
                "desc_en": raw["desc"],
                "desc_zh": desc_zh,
                "link": link,
                "pubDate": pub_iso,
                "relativeTime": relative_time(pub_iso),
                "category": feed["category"],
                "source": feed["source"],
            })

    all_items.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_items),
        "items": all_items,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = build_news()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
