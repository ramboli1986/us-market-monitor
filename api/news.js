/**
 * Vercel Serverless Function: /api/news
 * Real-time fetch of CNBC RSS feeds with parallel Chinese translation via Google Translate.
 * maxDuration: 60s (set in vercel.json)
 */

const https = require('https');

const RSS_FEEDS = [
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114', category: '综合', source: 'CNBC TOP NEWS' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258',  category: '经济', source: 'CNBC ECONOMY' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664',  category: '金融', source: 'CNBC FINANCE' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910',  category: '科技', source: 'CNBC TECHNOLOGY' },
];

const MAX_PER_FEED = 15;

// ── HTTP helper ──────────────────────────────────────────────
function fetchUrl(url, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      // follow redirects
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
  // Decode HTML entities first
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
    // Result is nested array: [[["translated","original",...],...]...]
    if (Array.isArray(parsed) && Array.isArray(parsed[0])) {
      const parts = parsed[0].map(seg => (Array.isArray(seg) && seg[0]) ? seg[0] : '');
      const result = parts.join('').trim();
      if (result && result !== truncated) return result;
    }
  } catch (e) {
    // fallback to original
  }
  return decoded;
}

// ── RSS Parser ───────────────────────────────────────────────
function parseXML(xml) {
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
    const cleanDesc = desc.replace(/<[^>]+>/g, '').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&').replace(/&apos;/g,"'").replace(/&quot;/g,'"').trim();
    const cleanTitle = title.replace(/<[^>]+>/g, '').trim();
    if (cleanTitle) {
      items.push({ title: cleanTitle, desc: cleanDesc.slice(0, 200), link: link.trim(), pubDate: pub.trim() });
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
    // Step 1: Fetch all RSS feeds in parallel
    const feedResults = await Promise.all(
      RSS_FEEDS.map(async (feed) => {
        try {
          const xml = await fetchUrl(feed.url, 10000);
          return { feed, items: parseXML(xml) };
        } catch (e) {
          return { feed, items: [] };
        }
      })
    );

    // Step 2: Collect unique items
    const rawItems = [];
    const seenLinks = new Set();
    for (const { feed, items } of feedResults) {
      for (const raw of items.slice(0, MAX_PER_FEED)) {
        if (!raw.link || seenLinks.has(raw.link)) continue;
        seenLinks.add(raw.link);
        rawItems.push({ ...raw, category: feed.category, source: feed.source });
      }
    }

    // Step 3: Translate all titles and descs in parallel (batch)
    const [titleZhList, descZhList] = await Promise.all([
      Promise.all(rawItems.map(item => translateGoogle(item.title))),
      Promise.all(rawItems.map(item => translateGoogle(item.desc))),
    ]);

    // Step 4: Build final items
    const allItems = rawItems.map((raw, i) => ({
      title_en: raw.title,
      title_zh: titleZhList[i] || raw.title,
      desc_en:  raw.desc,
      desc_zh:  descZhList[i] || raw.desc,
      link:     raw.link,
      pubDate:  parsePubDate(raw.pubDate),
      relativeTime: relativeTime(parsePubDate(raw.pubDate)),
      category: raw.category,
      source:   raw.source,
    }));

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
