#!/usr/bin/env python3
"""
Fetch Product Hunt daily data for the past 7 days.
Strategy:
  1. Try Playwright (non-headless Chrome) to scrape /leaderboard/daily pages
  2. Fallback to Atom Feed for partial data
  3. Merge with existing ph_products.json to preserve historical data
  4. Translate descriptions to Chinese via Google Translate
  5. Output ph_products.json with date-keyed structure
"""
import json, os, re, sys, html, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_PATH = PROJECT_DIR / "public" / "ph_products.json"
FEED_URL = "https://www.producthunt.com/feed"


# ─── Google Translate ───
def translate_text(text, src='en', tgt='zh-CN'):
    if not text or len(text.strip()) < 3:
        return text
    try:
        encoded = urllib.parse.quote(text[:500])
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={tgt}&dt=t&q={encoded}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            result = ''.join(part[0] for part in data[0] if part[0])
            return result if result and result != text else text
    except Exception:
        return text


# ─── Atom Feed Parser ───
def fetch_from_feed():
    """Parse PH Atom feed and group by date"""
    print("[Feed] Fetching Atom feed...")
    try:
        req = urllib.request.Request(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode()
    except Exception as e:
        print(f"[Feed] Error: {e}")
        return {}

    entries = re.findall(r'<entry>(.*?)</entry>', data, re.DOTALL)
    print(f"[Feed] Found {len(entries)} entries")

    by_date = {}
    for entry in entries:
        title_m = re.search(r'<title>(.*?)</title>', entry)
        pub_m = re.search(r'<published>(.*?)</published>', entry)
        link_m = re.search(r'<link rel="alternate".*?href="(.*?)"', entry)
        content_m = re.search(r'<content.*?>(.*?)</content>', entry, re.DOTALL)

        if not (title_m and pub_m and link_m):
            continue

        name = html.unescape(title_m.group(1).strip())
        pub_date = pub_m.group(1)[:10]
        ph_link = link_m.group(1).split('?')[0]
        slug = ph_link.rstrip('/').split('/')[-1]

        desc = ''
        if content_m:
            desc_match = re.search(r'<p>\s*(.*?)\s*</p>', html.unescape(content_m.group(1)))
            if desc_match:
                desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()

        post_id_match = re.search(r'/r/p/(\d+)', entry)
        product_link = f"https://www.producthunt.com/r/p/{post_id_match.group(1)}?app_id=339" if post_id_match else ph_link

        product = {
            'name': name,
            'slug': slug,
            'desc': desc,
            'desc_zh': '',
            'image': '',
            'ph_link': ph_link,
            'product_link': product_link,
            'source': 'feed'
        }

        if pub_date not in by_date:
            by_date[pub_date] = []
        by_date[pub_date].append(product)

    return by_date


# ─── Playwright Scraper ───
def fetch_from_playwright():
    """Scrape PH leaderboard pages using Playwright (non-headless)"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[Playwright] Not installed, skipping")
        return {}

    print("[Playwright] Starting browser (non-headless)...")
    by_date = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 900}
            )

            for i in range(7):
                d = datetime.now() - timedelta(days=i)
                date_key = d.strftime('%Y-%m-%d')
                url = f"https://www.producthunt.com/leaderboard/daily/{d.year}/{d.month}/{d.day}"
                print(f"[Playwright] Scraping {date_key}: {url}")

                try:
                    page = context.new_page()
                    page.goto(url, wait_until='networkidle', timeout=30000)
                    page.wait_for_timeout(3000)

                    # Scroll to load all images
                    for _ in range(4):
                        page.evaluate("window.scrollBy(0, 600)")
                        page.wait_for_timeout(800)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(1000)
                    for _ in range(4):
                        page.evaluate("window.scrollBy(0, 600)")
                        page.wait_for_timeout(800)

                    products = page.evaluate("""
                    () => {
                        const products = [];
                        const imgMap = {};
                        document.querySelectorAll('img').forEach(img => {
                            if (img.alt && img.src.includes('ph-files.imgix.net')) {
                                imgMap[img.alt] = img.src.replace(/w=\\d*/, 'w=128').replace(/h=\\d*/, 'h=128');
                            }
                        });
                        const seen = new Set();
                        document.querySelectorAll('a').forEach(a => {
                            const href = a.getAttribute('href') || '';
                            const text = a.textContent.trim();
                            if (!href.startsWith('/products/') || text.length < 2 || text.length > 80) return;
                            if (['Featured','All','Daily','Weekly','Monthly','Yearly'].includes(text)) return;

                            // Extract name (may have "N. " prefix)
                            const name = text.replace(/^\\d+\\.\\s*/, '');
                            const slug = href.replace('/products/', '');
                            if (seen.has(slug)) return;
                            seen.add(slug);

                            let desc = '';
                            const parent = a.closest('div')?.parentElement;
                            if (parent) {
                                const allText = parent.innerText.split('\\n').filter(t => t.trim().length > 15);
                                for (const t of allText) {
                                    const trimmed = t.trim();
                                    if (trimmed !== name && trimmed !== text && trimmed.length > 15 && trimmed.length < 200) {
                                        desc = trimmed;
                                        break;
                                    }
                                }
                            }

                            let upvotes = 0;
                            const container = a.closest('div')?.parentElement?.parentElement;
                            if (container) {
                                const buttons = container.querySelectorAll('button');
                                buttons.forEach(btn => {
                                    const num = parseInt(btn.textContent.trim());
                                    if (num > 5 && num < 10000) upvotes = Math.max(upvotes, num);
                                });
                            }

                            products.push({
                                name, slug,
                                image: imgMap[name] || '',
                                desc, upvotes,
                                ph_link: 'https://www.producthunt.com/products/' + slug,
                                product_link: 'https://www.producthunt.com/products/' + slug,
                                source: 'playwright'
                            });
                        });
                        return products;
                    }
                    """)

                    if products and len(products) > 1:
                        by_date[date_key] = products[:20]
                        print(f"  -> {len(products)} products found")

                        # Visit each product page to get external website link (top 20)
                        for idx, prod in enumerate(by_date[date_key]):
                            slug = prod['slug']
                            prod_url = f"https://www.producthunt.com/products/{slug}"
                            try:
                                prod_page = context.new_page()
                                prod_page.goto(prod_url, wait_until='domcontentloaded', timeout=20000)
                                prod_page.wait_for_timeout(2000)
                                ext_link = prod_page.evaluate("""
                                () => {
                                    const links = document.querySelectorAll('a');
                                    for (const a of links) {
                                        if (a.textContent.trim() === 'Visit website') {
                                            return a.getAttribute('href') || '';
                                        }
                                    }
                                    return '';
                                }
                                """)
                                if ext_link and not ext_link.startswith('/') and 'producthunt.com' not in ext_link:
                                    # Remove ?ref=producthunt tracking param
                                    clean_link = ext_link.split('?ref=producthunt')[0]
                                    prod['product_link'] = clean_link
                                    print(f"    [{idx+1}] {prod['name']}: {clean_link}")
                                else:
                                    print(f"    [{idx+1}] {prod['name']}: no external link")
                                prod_page.close()
                            except Exception as e:
                                print(f"    [{idx+1}] {prod['name']}: error - {e}")
                                try:
                                    prod_page.close()
                                except:
                                    pass
                    else:
                        print(f"  -> No products (possibly blocked)")

                    page.close()
                except Exception as e:
                    print(f"  -> Error: {e}")
                    try:
                        page.close()
                    except:
                        pass

            browser.close()
    except Exception as e:
        print(f"[Playwright] Fatal error: {e}")

    return by_date


# ─── Merge & Translate ───
def merge_data(playwright_data, feed_data, existing_data):
    """Merge data sources, preferring Playwright (has images) over Feed"""
    merged = {}

    # Start with existing data (preserve history)
    if existing_data and 'days' in existing_data:
        for date_key, products in existing_data['days'].items():
            merged[date_key] = products

    # Add feed data (for dates not in existing)
    for date_key, products in feed_data.items():
        if date_key not in merged:
            merged[date_key] = products
        else:
            existing_slugs = {p['slug'] for p in merged[date_key]}
            for p in products:
                if p['slug'] not in existing_slugs:
                    merged[date_key].append(p)

    # Playwright data overrides (has images)
    for date_key, products in playwright_data.items():
        if date_key not in merged or not merged[date_key]:
            merged[date_key] = products
        else:
            slug_map = {p['slug']: p for p in products}
            for existing_p in merged[date_key]:
                if existing_p['slug'] in slug_map:
                    pw_p = slug_map[existing_p['slug']]
                    if pw_p.get('image'):
                        existing_p['image'] = pw_p['image']
                    if pw_p.get('desc') and not existing_p.get('desc'):
                        existing_p['desc'] = pw_p['desc']
                    if pw_p.get('upvotes'):
                        existing_p['upvotes'] = pw_p['upvotes']
            existing_slugs = {p['slug'] for p in merged[date_key]}
            for p in products:
                if p['slug'] not in existing_slugs:
                    merged[date_key].append(p)

    # Keep only last 7 days
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    merged = {k: v for k, v in merged.items() if k >= cutoff}

    return merged


def translate_all(data):
    """Translate all descriptions that haven't been translated yet"""
    total = sum(len(v) for v in data.values())
    done = 0
    for date_key in sorted(data.keys(), reverse=True):
        for p in data[date_key]:
            done += 1
            if p.get('desc') and not p.get('desc_zh'):
                p['desc_zh'] = translate_text(p['desc'])
                print(f"  [{done}/{total}] {p['name']}: {p['desc_zh'][:50]}")
            elif p.get('desc_zh'):
                print(f"  [{done}/{total}] {p['name']}: (cached)")
            else:
                print(f"  [{done}/{total}] {p['name']}: (no desc)")
    return data


# ─── External Link Extraction ───
def fetch_external_links(data):
    """Fetch external website links from PH product pages using HTTP requests"""
    import time as _time
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    updated = 0
    errors = 0
    for date_key in sorted(data.keys(), reverse=True):
        for p in data[date_key]:
            current = p.get('product_link', '')
            # Skip if already has external link
            if current and 'producthunt.com' not in current:
                continue
            slug = p.get('slug', '')
            if not slug:
                continue
            url = f"https://www.producthunt.com/products/{slug}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    page_html = resp.read().decode('utf-8', errors='ignore')
                match = re.search(r'href="(https?://[^"]+)"[^>]*>\s*Visit website\s*</a>', page_html)
                if not match:
                    match = re.search(r'href="(https?://[^"]*)">Visit website', page_html)
                if match:
                    ext_url = match.group(1)
                    clean = ext_url.split('?ref=producthunt')[0].replace('&amp;', '&')
                    if 'producthunt.com' not in clean:
                        p['product_link'] = clean
                        updated += 1
                        print(f"    [LINK] {p['name']}: {clean}")
                _time.sleep(0.5)
            except Exception:
                errors += 1
                _time.sleep(1)
    print(f"  -> Updated {updated} external links ({errors} errors)")
    return data


# ─── Main ───
def main():
    # Load existing data
    existing = {}
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, encoding='utf-8') as f:
                existing = json.load(f)
            total = sum(len(v) for v in existing.get('days', {}).values())
            print(f"[Existing] Loaded {total} products from {len(existing.get('days', {}))} days")
        except:
            pass

    # Try Playwright first (best data with images)
    pw_data = fetch_from_playwright()

    # Always get feed data as supplement
    feed_data = fetch_from_feed()

    # Merge all sources
    merged = merge_data(pw_data, feed_data, existing)
    total = sum(len(v) for v in merged.values())
    print(f"\n[Merge] Total: {total} products across {len(merged)} days")

    # Fetch external website links
    print("\n[Links] Fetching external website links...")
    merged = fetch_external_links(merged)

    # Translate
    print("\n[Translate] Translating descriptions...")
    merged = translate_all(merged)

    # Output
    output = {
        'updated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'days': merged
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[Done] Saved to {OUTPUT_PATH}")
    for date_key in sorted(merged.keys(), reverse=True):
        print(f"  {date_key}: {len(merged[date_key])} products")


if __name__ == '__main__':
    main()
