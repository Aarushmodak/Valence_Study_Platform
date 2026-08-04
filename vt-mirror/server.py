#!/usr/bin/env python3
"""Valence - Vibrant Academy mirror server.

Serves the vt-mirror static files and proxies video/PDF requests to the
live RolexCoderZ /VT/ backend (rolexcoderz.com). The live site validates a
per-session token and grants 24h access via a cookie; this proxy manages
both automatically so the mirror behaves like the real site.
"""
import base64
import http.server
import json
import os
import re
import threading
import urllib.parse
import urllib.request

HOST = "127.0.0.1"
PORT = 8090
ROOT = os.path.dirname(os.path.abspath(__file__))

LIVE_BASE = "https://rolexcoderz.com/VT/index.php"
LIVE_API = "https://rolexcoderz.com/VT/api.php"
BATCH = "1"
BATCH_URL = LIVE_BASE + "?batch=1&f=3929"
# rcz_tok rotates; the gate page leaks the current one via
# localStorage 'rcz_dest'. FIXED_TOK is a fast-path fallback only.
FIXED_TOK = "9a37fbd3cb0a1db1"          # token baked into the site's gate pages
XOR_KEY = "638udh3829162018"            # matches PHP encVid()
COURSE_ID = "35"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_lock = threading.Lock()
_state = {
    "cookies": None,      # cookie jar string
    "k": None,            # current _K token
    "pdf_tokens": [],     # per-session PDF tokens from latest render
    "synced": False,
}


def _enc_vid(vid):
    out = bytes([ord(ch) ^ ord(XOR_KEY[i % len(XOR_KEY)])
                 for i, ch in enumerate(str(vid))])
    b64 = base64.b64encode(out).decode().rstrip("=")
    return b64.replace("+", "-").replace("/", "_")


def _http_get(url, extra_headers=None):
    headers = {"User-Agent": UA}
    if extra_headers:
        headers.update(extra_headers)
    with _lock:
        cookies = _state["cookies"]
    if cookies:
        headers["Cookie"] = cookies
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            cookie = resp.headers.get("Set-Cookie")
            if cookie:
                with _lock:
                    merged = _state["cookies"] or ""
                    new_parts = []
                    for part in cookie.split(","):
                        seg = part.split(";")[0].strip()
                        name = seg.split("=")[0]
                        kept = [p for p in merged.split(";") if p.strip().split("=")[0] != name]
                        new_parts.append(seg)
                    _state["cookies"] = "; ".join(kept + new_parts)
            return 200, body
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 502, str(e).encode()


def _parse_tokens(html):
    k = re.search(r"_K='([0-9a-fA-F]{32})'", html)
    tokens = re.findall(r'data-token="([^"]+)"', html)
    return (k.group(1) if k else None), tokens


def _get_gate_token():
    status, body = _http_get(LIVE_BASE + "?batch=%s&f=3929" % BATCH)
    if status != 200:
        return None
    html = body.decode("utf-8", "ignore")
    m = re.search(r"rcz_tok=([0-9a-f]{16})", html, re.I)
    return m.group(1) if m else None


def _sync():
    for attempt in range(2):
        tok = FIXED_TOK if attempt == 0 else _get_gate_token()
        if not tok:
            break
        status, body = _http_get(BATCH_URL + "&rcz_tok=" + tok)
        html = body.decode("utf-8", "ignore")
        k, tokens = _parse_tokens(html)
        if status == 200 and k and len(tokens) >= 3:
            with _lock:
                _state["k"] = k
                _state["pdf_tokens"] = tokens
                _state["synced"] = True
            return True
    return False


def _video(vid):
    for _ in range(2):
        with _lock:
            k = _state["k"]
        if not k:
            if not _sync():
                continue
            with _lock:
                k = _state["k"]
        status, body = _http_get(LIVE_BASE + "?batch=%s&_v=%s&_t=%s" % (BATCH, _enc_vid(vid), k))
        try:
            data = json.loads(body.decode("utf-8", "ignore"))
        except Exception:
            data = {"error": "bad response", "http": status}
        if status != 200 or data.get("error"):
            if not _sync():
                return json.dumps(data).encode()
            with _lock:
                k = _state["k"]
            status, body = _http_get(LIVE_BASE + "?batch=%s&_v=%s&_t=%s" % (BATCH, _enc_vid(vid), k))
            try:
                data = json.loads(body.decode("utf-8", "ignore"))
            except Exception:
                data = {"error": "bad response", "http": status}
        nt = data.get("_nt")
        if nt:
            with _lock:
                _state["k"] = nt
        return json.dumps(data).encode()
    return b'{"error":"sync failed"}'


def _transform(html):
    """Rebrand and repoint a live-rendered VT page so it works on the mirror."""
    html = html.replace("<title>RolexCoderZ", "<title>Valence")
    html = html.replace("RolexCoderZ", "Valence")
    html = html.replace(
        '<div class="nmark">\u26a1</div>',
        '<div class="nmark" style="padding:6px;background:linear-gradient(135deg,#f9e7b3,#d4af37)">'
        '<svg viewBox="0 0 48 56" fill="none" width="100%" height="100%">'
        '<path d="M24 2L42 18L24 54L6 18Z" fill="url(#nk)" stroke="rgba(249,231,179,.9)" stroke-width="1"/>'
        '<path d="M17 23L24 41L31 23" stroke="#120d02" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<defs><linearGradient id="nk" x1="6" y1="2" x2="42" y2="54">'
        '<stop offset="0" stop-color="#f9e7b3"/><stop offset=".5" stop-color="#d4af37"/><stop offset="1" stop-color="#8a6d1f"/>'
        '</linearGradient></defs></svg></div>')
    html = html.replace(">Valence</a>", "><span class=\"nb-gold\">Valence</span></a>")
    html = re.sub(r'<link rel="icon" href="[^"]*">',
                  '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 48 56\'%3E%3Cpath d=\'M24 2L42 18L24 54L6 18Z\' fill=\'%23d4af37\'/%3E%3Cpath d=\'M17 23L24 41L31 23\' stroke=\'%23050408\' stroke-width=\'3\' fill=\'none\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/svg%3E">', html)
    style = ('<style>'
             '.nb-gold{font-family:\'Cinzel\',serif;font-weight:800;letter-spacing:.1em;'
             'background:linear-gradient(110deg,#f9e7b3,#fff8e0 45%,#d4af37 70%,#f9e7b3);background-size:220%;'
             '-webkit-background-clip:text;background-clip:text;color:transparent;animation:brandShine 6s linear infinite}'
             '@keyframes brandShine{to{background-position:220% center}}'
             '.nmark{background:linear-gradient(135deg,#f9e7b3,#d4af37)!important;box-shadow:0 0 22px rgba(212,175,55,.5)!important;color:#1c1506!important}'
             '.nlogo{font-family:\'Cinzel\',serif!important}'
             '</style>')
    html = html.replace("</head>", style + "</head>")
    html = re.sub(r'href="\?"', 'href="/"', html)
    html = re.sub(r'href="\?batch=1&f=(\d+)[^"]*"', r'href="/content?f=\1"', html)
    html = html.replace("var _S=window.location.pathname", "var _S='/proxy'")
    html = html.replace(
        "fetch(_S+'?batch='+_B+'&_v='+_encVid(id)+'&_t='+_NK)",
        "fetch(_S+'/video?v='+id)")
    html = html.replace("base=_S.replace(/\\/[^\\/]*$/,'');", "base=_S;")
    html = html.replace("base = _S.replace(/\\/[^\\/]*$/, '');", "base = _S;")
    html = html.replace("base + '/api.php?action=pdfurl'", "base + '/pdf?'")
    html = html.replace("base+'/api.php?action=pdf'", "base+'/pdf-legacy?'")
    return html


def _render_content(folder):
    for _ in range(2):
        status, body = _http_get(LIVE_BASE + "?batch=%s&f=%s" % (BATCH, folder))
        html = body.decode("utf-8", "ignore")
        if status == 200 and "Get Access" not in html:
            k, tokens = _parse_tokens(html)
            if k:
                with _lock:
                    _state["k"] = k
                    if tokens:
                        _state["pdf_tokens"] = tokens
            return _transform(html)
        if not _sync():
            break
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/content":
            q = urllib.parse.parse_qs(parsed.query)
            folder = q.get("f", ["3929"])[0]
            html = _render_content(folder)
            if html is None:
                self._json({"error": "content unavailable"}, 502)
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/proxy/sync":
            ok = _sync()
            with _lock:
                self._json({"ok": ok, "tokens": _state["pdf_tokens"]})
            return
        if parsed.path == "/proxy/video":
            q = urllib.parse.parse_qs(parsed.query)
            vid = q.get("v", [""])[0]
            self._json(json.loads(_video(vid).decode()))
            return
        if parsed.path == "/proxy/pdf":
            q = urllib.parse.parse_qs(parsed.query)
            t = q.get("t", [""])[0]
            title = q.get("title", ["document"])[0]
            url = "%s?action=pdfurl&t=%s&title=%s" % (
                LIVE_API, urllib.parse.quote(t), urllib.parse.quote(title))
            status, body = _http_get(url)
            if status != 200:
                self._json({"error": "upstream %s" % status}, 502)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition",
                             "inline; filename=\"%s.pdf\"" % title[:40])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/proxy/pdf-legacy":
            q = urllib.parse.parse_qs(parsed.query)
            url = "%s?action=pdf&video_id=%s&course_id=%s&title=%s" % (
                LIVE_API,
                urllib.parse.quote(q.get("video_id", [""])[0]),
                urllib.parse.quote(q.get("course_id", [COURSE_ID])[0]),
                urllib.parse.quote(q.get("title", ["document"])[0]))
            status, body = _http_get(url)
            if status != 200:
                self._json({"error": "upstream %s" % status}, 502)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        print("[vt-mirror] " + fmt % args)


if __name__ == "__main__":
    print("Valence / Vibrant Academy mirror on http://%s:%d" % (HOST, PORT))
    try:
        http.server.ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("stopped")
