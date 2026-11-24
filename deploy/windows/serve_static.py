#!/usr/bin/env python3
"""Static server for the deployed sites: /<variant>/... is served from <base>/<env>/<variant>/current/...

Usage: python serve_static.py --base C:\\knowledge-hub\\www      (UAT on 8080, Dev on 8081)
"""
import argparse
import os
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ENVS = {"uat": 8080, "dev": 8081}


def make_handler(root):
    class Handler(SimpleHTTPRequestHandler):
        def _redirect(self):
            path = urlsplit(self.path).path
            location = "/default/" if path == "/" else path + "/" if re.fullmatch(r"/[a-z0-9_-]+", path) else None
            if location:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
            return bool(location)

        def do_GET(self):
            if not self._redirect():
                super().do_GET()

        def do_HEAD(self):
            if not self._redirect():
                super().do_HEAD()

        def translate_path(self, path):
            m = re.match(r"^/([a-z0-9_-]+)(/.*)$", urlsplit(path).path)
            if not m:
                return os.path.join(root, "__missing__")
            self.directory = os.path.join(root, m.group(1), "current")
            return super().translate_path(m.group(2))

        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    args = ap.parse_args()

    servers = []
    for env, port in ENVS.items():
        root = os.path.join(args.base, env)
        os.makedirs(root, exist_ok=True)
        servers.append(ThreadingHTTPServer(("0.0.0.0", port), make_handler(root)))
        print(f"{env}: http://0.0.0.0:{port}/ -> {root}", flush=True)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
