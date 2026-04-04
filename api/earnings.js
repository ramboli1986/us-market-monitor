/**
 * Vercel Serverless Function: /api/earnings
 * Fetches upcoming earnings dates for key companies from Alpha Vantage.
 */

const https = require('https');

// Key companies to track (Magnificent 7 + Major Banks + others)
const WATCH_LIST = {
  // Magnificent 7
  AAPL:  { name: 'Apple',           sector: 'tech',    logo: 'A', color: '#4f9cf9' },
  MSFT:  { name: 'Microsoft',       sector: 'tech',    logo: 'M', color: '#34d399' },
  GOOGL: { name: 'Alphabet',        sector: 'tech',    logo: 'G', color: '#f87171' },
  AMZN:  { name: 'Amazon',          sector: 'tech',    logo: 'A', color: '#4f9cf9' },
  META:  { name: 'Meta',            sector: 'tech',    logo: 'M', color: '#a78bfa' },
  NVDA:  { name: 'NVIDIA',          sector: 'tech',    logo: 'N', color: '#34d399' },
  TSLA:  { name: 'Tesla',           sector: 'tech',    logo: 'T', color: '#fbbf24' },
  // Major Banks
  JPM:   { name: 'JPMorgan Chase',  sector: 'finance', logo: 'J', color: '#34d399' },
  GS:    { name: 'Goldman Sachs',   sector: 'finance', logo: 'G', color: '#4f9cf9' },
  BAC:   { name: 'Bank of America', sector: 'finance', logo: 'B', color: '#4f9cf9' },
  MS:    { name: 'Morgan Stanley',  sector: 'finance', logo: 'M', color: '#a78bfa' },
  WFC:   { name: 'Wells Fargo',     sector: 'finance', logo: 'W', color: '#fbbf24' },
  C:     { name: 'Citigroup',       sector: 'finance', logo: 'C', color: '#f87171' },
};

const SECTOR_LABELS = { tech: '科技', finance: '金融' };
const TIME_LABELS   = { 'pre-market': '盘前', 'post-market': '盘后', '': '待定' };

function fetchUrl(url, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
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

function parseCSV(csv) {
  const lines = csv.trim().split('\n');
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim());
  return lines.slice(1).map(line => {
    const vals = line.split(',');
    const obj = {};
    headers.forEach((h, i) => { obj[h] = (vals[i] || '').trim(); });
    return obj;
  });
}

function daysUntil(dateStr) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  return Math.round((target - today) / 86400000);
}

function formatDate(dateStr) {
  const d = new Date(dateStr);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  return `${month}月${day}日（周${weekdays[d.getDay()]}）`;
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Cache-Control', 'public, max-age=3600, stale-while-revalidate=7200');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  try {
    const csv = await fetchUrl(
      'https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=demo',
      12000
    );

    const rows = parseCSV(csv);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const results = [];
    const seenSymbols = new Set();

    for (const row of rows) {
      const symbol = row.symbol || row.Symbol || '';
      if (!WATCH_LIST[symbol] || seenSymbols.has(symbol)) continue;
      seenSymbols.add(symbol);

      const reportDate = row.reportDate || row.reportdate || '';
      const days = daysUntil(reportDate);
      if (days < -1 || days > 90) continue; // skip past or too far

      const info = WATCH_LIST[symbol];
      const timeRaw = (row.timeOfTheDay || '').toLowerCase();
      const timeLabel = TIME_LABELS[timeRaw] !== undefined ? TIME_LABELS[timeRaw] : timeRaw || '待定';
      const eps = row.estimate ? parseFloat(row.estimate).toFixed(2) : null;

      results.push({
        symbol,
        name: info.name,
        sector: info.sector,
        sectorLabel: SECTOR_LABELS[info.sector] || info.sector,
        logo: info.logo,
        color: info.color,
        reportDate,
        dateLabel: formatDate(reportDate),
        daysUntil: days,
        timeLabel,
        epsEstimate: eps,
        fiscalQuarter: row.fiscalDateEnding || '',
      });
    }

    // Sort by date
    results.sort((a, b) => a.reportDate.localeCompare(b.reportDate));

    res.status(200).json({
      updated_at: new Date().toISOString(),
      count: results.length,
      items: results,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
