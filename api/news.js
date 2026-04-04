/**
 * Vercel Serverless Function: /api/news
 * Real-time fetch of CNBC RSS feeds with Chinese translation via MyMemory API.
 */

const https = require('https');
const http = require('http');

const RSS_FEEDS = [
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114', category: '综合', source: 'CNBC TOP NEWS' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258',  category: '经济', source: 'CNBC ECONOMY' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664',  category: '金融', source: 'CNBC FINANCE' },
  { url: 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910',  category: '科技', source: 'CNBC TECHNOLOGY' },
];

const MAX_PER_FEED = 15;

function fetchUrl(url, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith('https') ? https : http;
    const req = lib.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

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
    const cleanDesc = desc.replace(/<[^>]+>/g, '').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&').trim();
    const cleanTitle = title.replace(/<[^>]+>/g, '').trim();
    if (cleanTitle) {
      items.push({ title: cleanTitle, desc: cleanDesc.slice(0, 200), link: link.trim(), pubDate: pub.trim() });
    }
  }
  return items;
}

async function translate(text) {
  if (!text || !text.trim()) return text;
  const truncated = text.slice(0, 480);
  const encoded = encodeURIComponent(truncated);
  const url = `https://api.mymemory.translated.net/get?q=${encoded}&langpair=en|zh`;
  try {
    const body = await fetchUrl(url, 8000);
    const data = JSON.parse(body);
    if (data.responseStatus === 200) {
      const t = data.responseData.translatedText;
      if (t && t !== text) return t;
    }
  } catch (e) {
    // fallback to original
  }
  return text;
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
    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
    return `${Math.floor(diff / 86400)}天前`;
  } catch (e) { return ''; }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

module.exports = async function handler(req, res) {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  try {
    const allItems = [];
    const seenLinks = new Set();

    for (const feed of RSS_FEEDS) {
      let xml = '';
      try { xml = await fetchUrl(feed.url, 10000); } catch (e) { continue; }
      const rawItems = parseXML(xml);

      for (const raw of rawItems.slice(0, MAX_PER_FEED)) {
        if (!raw.link || seenLinks.has(raw.link)) continue;
        seenLinks.add(raw.link);

        const pubIso = parsePubDate(raw.pubDate);
        const titleZh = await translate(raw.title);
        await sleep(150);
        const descZh = raw.desc ? await translate(raw.desc) : '';
        await sleep(150);

        allItems.push({
          title_en: raw.title,
          title_zh: titleZh,
          desc_en: raw.desc,
          desc_zh: descZh,
          link: raw.link,
          pubDate: pubIso,
          relativeTime: relativeTime(pubIso),
          category: feed.category,
          source: feed.source,
        });
      }
    }

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
