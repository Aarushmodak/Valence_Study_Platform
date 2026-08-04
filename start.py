#!/usr/bin/env python3
"""Valence Platform - one command launcher.

Starts the static site server (port 8080) serving the Valence hub and the
NextToppers + Mission Jeet mirrors, then the Vibrant Academy mirror server
(port 8090) with its live proxy, and opens the Valence hub in the browser.
"""
import http.server
import os
import subprocess
import sys
import threading
import time
import webbrowser
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
HUB_URL = "http://localhost:8080/valence/index.html"


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        print("[http:8080] " + fmt % args)


def wait_for(url, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    ports = []
    try:
        static = http.server.ThreadingHTTPServer(("127.0.0.1", 8080), StaticHandler)
        ports.append(8080)
        print("Valence hub + NextToppers/Mission Jeet mirrors: %s" % HUB_URL)
    except OSError as e:
        print("WARNING: port 8080 busy (%s) - assuming site already running" % e)
        static = None

    vt = None
    if static is not None or True:
        try:
            vt = subprocess.Popen(
                [sys.executable, os.path.join(ROOT, "vt-mirror", "server.py")],
                cwd=os.path.join(ROOT, "vt-mirror"))
            print("Vibrant Academy mirror: http://localhost:8090/")
        except OSError as e:
            print("WARNING: could not start VT mirror (%s)" % e)

    threading.Thread(target=lambda: static.serve_forever() if static else None,
                     daemon=True).start() if static else None

    if wait_for(HUB_URL):
        webbrowser.open(HUB_URL)
    else:
        print("WARNING: could not reach %s - is port 8080 already in use?" % HUB_URL)

    print("Press Ctrl+C to stop all servers.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if static:
            static.shutdown()
            static.server_close()
        if vt:
            vt.terminate()
        print("stopped")


if __name__ == "__main__":
    main()
