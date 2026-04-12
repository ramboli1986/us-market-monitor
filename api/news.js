/**
 * Vercel Serverless Function: /api/news
 * Real-time fetch of international news + Product Hunt with Chinese translation.
 * Sources: BBC World, Google News, CNBC, BBC Tech, Product Hunt Atom Feed
 * maxDuration: 60s (set in vercel.json)
 */

const https = require('https');
const http = require('http');

const RSS_FEEDS = [
  { url: 'https://feeds.bbci.co.uk/news/world/rss.xml', category: '国际', source: 'BBC World' },
  { url: 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en', category: '头条', source: 'Google News' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114', category: '财经', source: 'CNBC' },
  { url: 'https://feeds.bbci.co.uk/news/technology/rss.xml', category: '科技', source: 'BBC Tech' },
];

const PH_FEED_URL = 'https://www.producthunt.com/feed';
const MAX_PER_FEED = 15;
const MAX_PH = 20;

// ── HTTP helper ──────────────────────────────────────────────
function fetchUrl(url, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return fetchUrl(res.headers.location, timeout).then(resolve).catch(reject);
      }
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    });
    req.setTimeout(timeout, () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
  });
}

// ── Google Translate (unofficial, no key needed) ─────────────
async function translateGoogle(text) {
  if (!text || !text.trim()) return text;
  const decoded = text
    .replace(/&apos;/g, "'").replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
  const truncated = decoded.slice(0, 500);
  const encoded = encodeURIComponent(truncated);
  const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=${encoded}`;
  try {
    const body = await fetchUrl(url, 8000);
    const parsed = JSON.parse(body);
    if (Array.isArray(parsed) && Array.isArray(parsed[0])) {
      const parts = parsed[0].map(seg => (Array.isArray(seg) && seg[0]) ? seg[0] : '');
      const result = parts.join('').trim();
      if (result && result !== truncated) return result;
    }
  } catch (e) {}
  return decoded;
}

// ── RSS Parser ───────────────────────────────────────────────
function parseRSS(xml) {
  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let match;
  while ((match = itemRegex.exec(xml)) !== null) {
    const block = match[1];
    const title = (block.match(/<title[^>]*><!\[CDATA\[([\s\S]*?)\]\]><\/title>/) ||
                   block.match(/<title[^>]*>([\s\S]*?)<\/title>/) || [])[1] || '';
    const desc  = (block.match(/<description[^>]*><!\[CDATA\[([\s\S]*?)\]\]><\/description>/) ||
                   block.match(/<description[^>]*>([\s\S]*?)<\/description>/) || [])[1] || '';
    const link  = (block.match(/<link[^>]*>([\s\S]*?)<\/link>/) || [])[1] || '';
    const pub   = (block.match(/<pubDate[^>]*>([\s\S]*?)<\/pubDate>/) || [])[1] || '';
    // Try to extract image from media:thumbnail or media:content
    const imgMatch = block.match(/<media:thumbnail[^>]*url="([^"]+)"/) ||
                     block.match(/<media:content[^>]*url="([^"]+)"/) ||
                     block.match(/<enclosure[^>]*url="([^"]+)"[^>]*type="image/);
    const image = imgMatch ? imgMatch[1] : '';
    const cleanDesc = desc.replace(/<[^>]+>/g, '').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&').replace(/&apos;/g,"'").replace(/&quot;/g,'"').trim();
    const cleanTitle = title.replace(/<[^>]+>/g, '').trim();
    if (cleanTitle) {
      items.push({ title: cleanTitle, desc: cleanDesc.slice(0, 200), link: link.trim(), pubDate: pub.trim(), image });
    }
  }
  return items;
}

// ── Atom Feed Parser (Product Hunt) ──────────────────────────
function parseAtom(xml) {
  const items = [];
  const entryRegex = /<entry>([\s\S]*?)<\/entry>/g;
  let match;
  while ((match = entryRegex.exec(xml)) !== null) {
    const block = match[1];
    const title = (block.match(/<title[^>]*>([\s\S]*?)<\/title>/) || [])[1] || '';
    const linkMatch = block.match(/<link[^>]*href="([^"]+)"/);
    const link = linkMatch ? linkMatch[1] : '';
    const pub = (block.match(/<published[^>]*>([\s\S]*?)<\/published>/) || [])[1] || '';
    const content = (block.match(/<content[^>]*>([\s\S]*?)<\/content>/) || [])[1] || '';
    const desc = content.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&')
                        .replace(/<[^>]+>/g, '').trim().split('\n')[0].trim();
    // Extract post ID
    const idMatch = block.match(/Post\/(\d+)/);
    const postId = idMatch ? idMatch[1] : '';
    const badgeUrl = postId ? `https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=${postId}&theme=dark` : '';
    if (title.trim()) {
      items.push({
        title: title.trim(),
        desc: desc.slice(0, 200),
        link: link.trim(),
        pubDate: pub.trim(),
        image: badgeUrl,
        post_id: postId,
        type: 'product',
      });
    }
  }
  return items;
}

function parsePubDate(pubDate) {
  if (!pubDate) return new Date().toISOString();
  try {
    const d = new Date(pubDate);
    if (!isNaN(d.getTime())) return d.toISOString();
  } catch (e) {}
  return new Date().toISOString();
}

function relativeTime(isoStr) {
  try {
    const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    if (diff < 0)     return '刚刚';
    if (diff < 60)    return '刚刚';
    if (diff < 3600)  return `${Math.floor(diff / 60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
    return `${Math.floor(diff / 86400)}天前`;
  } catch (e) { return ''; }
}

// ── Main handler ─────────────────────────────────────────────
module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  try {
    // Step 1: Fetch all RSS feeds + Product Hunt in parallel
    const [feedResults, phXml] = await Promise.all([
      Promise.all(
        RSS_FEEDS.map(async (feed) => {
          try {
            const xml = await fetchUrl(feed.url, 10000);
            return { feed, items: parseRSS(xml) };
          } catch (e) {
            return { feed, items: [] };
          }
        })
      ),
      fetchUrl(PH_FEED_URL, 10000).catch(() => ''),
    ]);

    // Step 2: Collect unique news items
    const rawItems = [];
    const seenLinks = new Set();
    for (const { feed, items } of feedResults) {
      for (const raw of items.slice(0, MAX_PER_FEED)) {
        if (!raw.link || seenLinks.has(raw.link)) continue;
        seenLinks.add(raw.link);
        rawItems.push({ ...raw, category: feed.category, source: feed.source, type: 'news' });
      }
    }

    // Step 3: Parse Product Hunt items
    const phItems = phXml ? parseAtom(phXml).slice(0, MAX_PH) : [];
    for (const ph of phItems) {
      if (!ph.link || seenLinks.has(ph.link)) continue;
      seenLinks.add(ph.link);
      rawItems.push({ ...ph, category: 'Product Hunt', source: 'Product Hunt' });
    }

    // Step 4: Translate all titles and descs in parallel
    const [titleZhList, descZhList] = await Promise.all([
      Promise.all(rawItems.map(item => translateGoogle(item.title))),
      Promise.all(rawItems.map(item => translateGoogle(item.desc))),
    ]);

    // Step 5: Build final items
    const allItems = rawItems.map((raw, i) => {
      const base = {
        title_en: raw.title,
        title_zh: titleZhList[i] || raw.title,
        desc_en:  raw.desc,
        desc_zh:  descZhList[i] || raw.desc,
        link:     raw.link,
        pubDate:  parsePubDate(raw.pubDate),
        relativeTime: relativeTime(parsePubDate(raw.pubDate)),
        category: raw.category,
        source:   raw.source,
        image:    raw.image || '',
        type:     raw.type || 'news',
      };
      if (raw.type === 'product') {
        base.post_id = raw.post_id || '';
      }
      return base;
    });

    allItems.sort((a, b) => (b.pubDate > a.pubDate ? 1 : -1));

    res.status(200).json({
      updated_at: new Date().toISOString(),
      count: allItems.length,
      items: allItems,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
