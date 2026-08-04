// Valence - Vibrant Academy proxy as a modern Netlify Function.
// Port of vt-mirror/server.py: manages the live RolexCoderZ /VT/ session
// (cookies + rotating _K token) and serves /content, /proxy/sync,
// /proxy/video, /proxy/pdf and /proxy/pdf-legacy behind netlify.toml rewrites.
// Module state survives warm invocations; a cold start just re-syncs.

const LIVE_BASE = "https://rolexcoderz.com/VT/index.php";
const LIVE_API = "https://rolexcoderz.com/VT/api.php";
const BATCH = "1";
const BATCH_URL = LIVE_BASE + "?batch=1&f=3929";
// rcz_tok rotates; the gate page leaks the current one via
// localStorage 'rcz_dest'. FIXED_TOK is a fast-path fallback only.
const FIXED_TOK = "9a37fbd3cb0a1db1";
const XOR_KEY = "638udh3829162018";
const COURSE_ID = "35";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

let cookieJar = null;
let k = null;
let pdfTokens = [];

const dec = new TextDecoder();

function encVid(vid) {
  const s = String(vid);
  let out = "";
  for (let i = 0; i < s.length; i++) {
    out += String.fromCharCode(s.charCodeAt(i) ^ XOR_KEY.charCodeAt(i % XOR_KEY.length));
  }
  return Buffer.from(out, "binary").toString("base64").replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

async function httpGet(url, extraHeaders) {
  const headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Referer": LIVE_BASE,
    "Upgrade-Insecure-Requests": "1",
  };
  if (extraHeaders) Object.assign(headers, extraHeaders);
  if (cookieJar) headers["Cookie"] = cookieJar;
  try {
    const resp = await fetch(url, { headers, redirect: "follow", signal: AbortSignal.timeout(45000) });
    const setCookies = typeof resp.headers.getSetCookie === "function" ? resp.headers.getSetCookie() : [];
    for (const sc of setCookies) {
      const seg = sc.split(";")[0].trim();
      const name = seg.split("=")[0].trim();
      const parts = cookieJar ? cookieJar.split(";") : [];
      cookieJar = parts.filter((p) => p.trim().split("=")[0] !== name).concat(seg).join("; ");
    }
    const body = new Uint8Array(await resp.arrayBuffer());
    return { status: resp.status, body, resp };
  } catch (e) {
    return { status: 502, body: Buffer.from(String(e)), resp: null };
  }
}

function parseTokens(html) {
  const m = html.match(/_K='([0-9a-fA-F]{32})'/);
  const tokens = Array.from(html.matchAll(/data-token="([^"]+)"/g), (x) => x[1]);
  return { k: m ? m[1] : null, tokens };
}

async function getGateToken() {
  const { status, body } = await httpGet(LIVE_BASE + "?batch=" + BATCH + "&f=3929");
  if (status !== 200) return null;
  const txt = dec.decode(body);
  const m = txt.match(/rcz_tok=([0-9a-f]{16})/i);
  return m ? m[1] : null;
}

async function sync() {
  for (let attempt = 0; attempt < 2; attempt++) {
    const tok = attempt === 0 ? FIXED_TOK : await getGateToken();
    if (!tok) break;
    const { status, body } = await httpGet(BATCH_URL + "&rcz_tok=" + tok);
    const html = dec.decode(body);
    const { k: nk, tokens } = parseTokens(html);
    if (status === 200 && nk && tokens.length >= 3) {
      k = nk;
      pdfTokens = tokens;
      return true;
    }
  }
  return false;
}

async function video(vid) {
  for (let attempt = 0; attempt < 2; attempt++) {
    if (!k && !(await sync())) continue;
    let r = await httpGet(LIVE_BASE + "?batch=" + BATCH + "&_v=" + encVid(vid) + "&_t=" + k);
    let data;
    try { data = JSON.parse(dec.decode(r.body)); } catch { data = { error: "bad response", http: r.status }; }
    if (r.status !== 200 || data.error) {
      if (!(await sync())) return JSON.stringify(data);
      r = await httpGet(LIVE_BASE + "?batch=" + BATCH + "&_v=" + encVid(vid) + "&_t=" + k);
      try { data = JSON.parse(dec.decode(r.body)); } catch { data = { error: "bad response", http: r.status }; }
    }
    if (data._nt) k = data._nt;
    return JSON.stringify(data);
  }
  return '{"error":"sync failed"}';
}

const NMARK_GOLD = '<div class="nmark" style="padding:6px;background:linear-gradient(135deg,#f9e7b3,#d4af37)">' +
  '<svg viewBox="0 0 48 56" fill="none" width="100%" height="100%">' +
  '<path d="M24 2L42 18L24 54L6 18Z" fill="url(#nk)" stroke="rgba(249,231,179,.9)" stroke-width="1"/>' +
  '<path d="M17 23L24 41L31 23" stroke="#120d02" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' +
  '<defs><linearGradient id="nk" x1="6" y1="2" x2="42" y2="54">' +
  '<stop offset="0" stop-color="#f9e7b3"/><stop offset=".5" stop-color="#d4af37"/><stop offset="1" stop-color="#8a6d1f"/>' +
  "</linearGradient></defs></svg></div>";

const GOLD_FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 56'%3E%3Cpath d='M24 2L42 18L24 54L6 18Z' fill='%23d4af37'/%3E%3Cpath d='M17 23L24 41L31 23' stroke='%23050408' stroke-width='3' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E";

const BRAND_STYLE = "<style>" +
  ".nb-gold{font-family:'Cinzel',serif;font-weight:800;letter-spacing:.1em;" +
  "background:linear-gradient(110deg,#f9e7b3,#fff8e0 45%,#d4af37 70%,#f9e7b3);background-size:220%;" +
  "-webkit-background-clip:text;background-clip:text;color:transparent;animation:brandShine 6s linear infinite}" +
  "@keyframes brandShine{to{background-position:220% center}}" +
  ".nmark{background:linear-gradient(135deg,#f9e7b3,#d4af37)!important;box-shadow:0 0 22px rgba(212,175,55,.5)!important;color:#1c1506!important}" +
  ".nlogo{font-family:'Cinzel',serif!important}" +
  "</style>";

function transform(html) {
  html = html.replace(/<title>RolexCoderZ/, "<title>Valence").replaceAll("RolexCoderZ", "Valence");
  html = html.replace(/<div class="nmark">⚡<\/div>/, NMARK_GOLD);
  html = html.replaceAll(">Valence</a>", '><span class="nb-gold">Valence</span></a>');
  html = html.replace(/<link rel="icon" href="[^"]*">/, '<link rel="icon" href="' + GOLD_FAVICON + '">');
  html = html.replace("</head>", BRAND_STYLE + "</head>");
  html = html.replace(/href="\?"/g, 'href="/"');
  html = html.replace(/href="\?batch=1&f=(\d+)[^"]*"/g, 'href="/content?f=$1"');
  html = html.replace("var _S=window.location.pathname", "var _S='/proxy'");
  html = html.replace(
    "fetch(_S+'?batch='+_B+'&_v='+_encVid(id)+'&_t='+_NK)",
    "fetch(_S+'/video?v='+id)");
  html = html.replace("base=_S.replace(/\\/[^\\/]*$/,'');", "base=_S;");
  html = html.replace("base = _S.replace(/\\/[^\\/]*$/, '');", "base = _S;");
  html = html.replace("base + '/api.php?action=pdfurl'", "base + '/pdf?'");
  html = html.replace("base+'/api.php?action=pdf'", "base+'/pdf-legacy?'");
  return html;
}

async function renderContent(folder) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const { status, body } = await httpGet(LIVE_BASE + "?batch=" + BATCH + "&f=" + folder);
    const html = dec.decode(body);
    if (status === 200 && !html.includes("Get Access")) {
      const { k: nk, tokens } = parseTokens(html);
      if (nk) {
        k = nk;
        if (tokens.length) pdfTokens = tokens;
      }
      return transform(html);
    }
    if (!(await sync())) break;
  }
  return null;
}

function json(status, obj) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
}

export default async (req) => {
  const url = new URL(req.url, "https://va.invalid");
  const path = url.pathname;
  const q = url.searchParams;

  if (path === "/content") {
    const html = await renderContent(q.get("f") || "3929");
    if (html === null) return json(502, { error: "content unavailable" });
    return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
  }

  if (path === "/proxy/sync") {
    const ok = await sync();
    return json(200, { ok, tokens: pdfTokens });
  }

  if (path === "/proxy/video") {
    return json(200, JSON.parse(await video(q.get("v") || "")));
  }

  if (path === "/proxy/pdf") {
    const url2 = LIVE_API + "?action=pdfurl&t=" + encodeURIComponent(q.get("t") || "") + "&title=" + encodeURIComponent(q.get("title") || "document");
    const r = await httpGet(url2);
    if (r.status !== 200) return json(502, { error: "upstream " + r.status });
    const name = (q.get("title") || "document").slice(0, 40);
    return new Response(r.body, {
      status: 200,
      headers: { "content-type": "application/pdf", "content-disposition": 'inline; filename="' + name + '.pdf"' },
    });
  }

  if (path === "/proxy/pdf-legacy") {
    const url2 = LIVE_API + "?action=pdf&video_id=" + encodeURIComponent(q.get("video_id") || "") +
      "&course_id=" + encodeURIComponent(q.get("course_id") || COURSE_ID) + "&title=" + encodeURIComponent(q.get("title") || "document");
    const r = await httpGet(url2);
    if (r.status !== 200) return json(502, { error: "upstream " + r.status });
    return new Response(r.body, { status: 200, headers: { "content-type": "application/pdf" } });
  }

  return json(404, { error: "not found" });
};
