#!/usr/bin/env python3
"""Static file server with HTTP Basic Auth, stdlib only.

Serves the directory it lives in (index.html, data.json) on $PORT (Railway
sets this; defaults to 8080 for local testing). Refuses to start if
DASH_USER / DASH_PASSWORD are not both set -- a password-protected dashboard
that silently serves world-readable is worse than one that fails to boot.
"""
from __future__ import annotations

import base64
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


def _required_env() -> tuple[str, str]:
    user = os.environ.get("DASH_USER")
    password = os.environ.get("DASH_PASSWORD")
    if not user or not password:
        sys.stderr.write(
            "FATAL: DASH_USER and DASH_PASSWORD must both be set. "
            "Refusing to start an unauthenticated dashboard.\n"
        )
        sys.exit(1)
    return user, password


class AuthHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self._authorized():
            return self._deny()
        super().do_GET()

    def do_HEAD(self):
        if not self._authorized():
            return self._deny()
        super().do_HEAD()

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        got = self.headers.get("Authorization", "")
        return got == expected

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Loci Dashboard"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    USER, PASSWORD = _required_env()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AuthHandler)
    sys.stderr.write(f"serving on 0.0.0.0:{port} (basic auth: user={USER!r})\n")
    server.serve_forever()
