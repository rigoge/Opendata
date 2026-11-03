#!/usr/bin/env python3
"""ICON Grid Viewer – lokaler Helfer (nur Python-Standardbibliothek).

Die GRIB2-Dateien der MeteoSchweiz-OGD liegen auf rgw.cscs.ch. Dieser Speicher
sendet keine CORS-Header, deshalb darf ein Browser sie nicht per JavaScript laden.
Dieses Skript
  * liefert "icon grid viewer.html" unter http://127.0.0.1:8765/ aus und
  * leitet Downloads über /proxy?url=... weiter (nur erlaubte Hosts, nur HTTPS).

Start:  python3 icon_grid_proxy.py          (öffnet den Browser automatisch)
        python3 icon_grid_proxy.py --port 9000 --no-browser
Zusätzliche erlaubte Hosts: Umgebungsvariable ICON_PROXY_ALLOW="host1,host2".

MIT License
"""
import argparse
import http.server
import os
import shutil
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = "icon grid viewer.html"
ALLOWED = {"data.geo.admin.ch", "rgw.cscs.ch"} | {
    h.strip() for h in os.environ.get("ICON_PROXY_ALLOW", "").split(",") if h.strip()
}
PASS_HEADERS = ("Content-Type", "Content-Length", "Last-Modified", "ETag", "x-amz-meta-sha256")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "IconGridProxy/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, x-amz-meta-sha256")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if urllib.parse.unquote(path.path) in ("/", "/" + HTML):
            return self._serve_html()
        if path.path == "/proxy/ping":
            return self._send(200, b"ok", "text/plain")
        if path.path == "/proxy":
            return self._proxy("GET")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == "/proxy":
            return self._proxy("POST")
        self._send(404, b"not found", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        try:
            with open(os.path.join(HERE, HTML), "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, f"{HTML} nicht im Ordner {HERE} gefunden".encode(), "text/plain; charset=utf-8")
        self._send(200, body, "text/html; charset=utf-8")

    def _proxy(self, method):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = (qs.get("url") or [""])[0]
        u = urllib.parse.urlparse(url)
        if u.scheme != "https" or u.hostname not in ALLOWED:
            return self._send(403, f"Host nicht erlaubt: {u.hostname}".encode(), "text/plain; charset=utf-8")
        data, headers = None, {"User-Agent": "icon-grid-browser-proxy"}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n)
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:  # Netzwerkfehler
            return self._send(502, f"Upstream-Fehler: {e}".encode(), "text/plain; charset=utf-8")
        try:
            self.send_response(resp.status if hasattr(resp, "status") else resp.code)
            self._cors()
            for h in PASS_HEADERS:
                v = resp.headers.get(h)
                if v:
                    self.send_header(h, v)
            self.end_headers()
            shutil.copyfileobj(resp, self.wfile, 1 << 20)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browser hat abgebrochen (z. B. früher Stopp nach CLAT/CLON)
        finally:
            resp.close()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = Server(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"ICON Grid Viewer läuft auf {url}  (Beenden mit Ctrl+C)")
    print("Erlaubte Hosts:", ", ".join(sorted(ALLOWED)))
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()
