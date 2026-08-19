#!/usr/bin/env python3
# Copyright (c) 2026 The Sequentia developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Read-only JSON feed for the Sequentia staking pool board.

The board is a static page; this is the one thing it needs that a static page
cannot do, which is talk to a node. It exposes exactly one RPC, `listpools`,
over plain HTTP as `GET /pools.json`, and nothing else: no wallet, no method the
caller chooses, no parameter that reaches the node unchecked. A public page must
not be a proxy to an RPC socket, so this is a fixed query rather than a
forwarder.

`listpools` walks the whole stake registry and a window of the block index, which
is cheap but not free, and a public board is polled by every viewer at once. The
response is therefore cached for SEQ_POOLS_TTL seconds and computed at most once
at a time: a burst of viewers arriving together produces one node call, not one
each, so a slow node cannot be turned into a queue of concurrent RPCs.

Configuration, all optional:
  SEQ_RPC_URL       node RPC endpoint (default http://127.0.0.1:7041)
  SEQ_RPC_COOKIE    path to the node's .cookie file (preferred over user/pass)
  SEQ_RPC_USER      RPC username, when not using a cookie
  SEQ_RPC_PASSWORD  RPC password, when not using a cookie
  SEQ_POOLS_WINDOW  blocks to measure production reliability over (default 500)
  SEQ_POOLS_TTL     seconds to cache the answer for (default 15)
  SEQ_POOLS_PORT    listen port (default 8091)
  SEQ_POOLS_BIND    listen address (default 127.0.0.1; keep it loopback behind
                    a front-end server)
  SEQ_POOLS_PAGE    directory holding index.html (default: next to this file)

Run it and leave it open:  python3 pool-board-server.py
"""

import http.server
import json
import os
import socketserver
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

RPC_URL = os.environ.get("SEQ_RPC_URL", "http://127.0.0.1:7041")
RPC_COOKIE = os.environ.get("SEQ_RPC_COOKIE", "")
RPC_USER = os.environ.get("SEQ_RPC_USER", "")
RPC_PASSWORD = os.environ.get("SEQ_RPC_PASSWORD", "")
WINDOW = int(os.environ.get("SEQ_POOLS_WINDOW", "500"))
TTL = float(os.environ.get("SEQ_POOLS_TTL", "15"))
PORT = int(os.environ.get("SEQ_POOLS_PORT", "8091"))
BIND = os.environ.get("SEQ_POOLS_BIND", "127.0.0.1")
PAGE_DIR = Path(os.environ.get("SEQ_POOLS_PAGE", Path(__file__).resolve().parent))

#: How long a stale answer may still be served when the node is unreachable. A
#: board frozen for a few minutes, stamped with when it was read, is far more
#: useful than an error page: the reader can still see which pools announced a
#: change, which is the time-critical part.
STALE_OK = 300.0


def _auth_header():
    """Basic-auth value for the node, from the cookie file or user/password.

    The cookie is read on every miss rather than cached: the node rewrites it on
    every restart, and a feed that keeps serving errors until someone restarts
    it too is a worse failure than one extra file read per cache miss."""
    if RPC_COOKIE:
        secret = Path(RPC_COOKIE).read_text().strip()
    elif RPC_USER:
        secret = f"{RPC_USER}:{RPC_PASSWORD}"
    else:
        return None
    return "Basic " + b64encode(secret.encode()).decode()


def rpc(method, params):
    body = json.dumps({"jsonrpc": "1.0", "id": "pool-board",
                       "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    auth = _auth_header()
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        # The node reports an RPC-level refusal with a non-2xx status AND a JSON
        # body; the body is the useful half, so prefer it over "HTTP 500".
        try:
            payload = json.load(e)
        except Exception:
            raise RuntimeError(f"node returned HTTP {e.code}") from None
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", str(payload["error"])))
    return payload["result"]


_lock = threading.Lock()
_cache = {"at": 0.0, "body": None}


def pools_json():
    """The board's payload, cached.

    Held under one lock for the whole miss, so a crowd of viewers arriving
    together costs the node a single call rather than one each. If the node is
    unreachable and a recent answer is in hand, serve that instead of failing:
    the page stamps every reading with its time, so a stale board is honest."""
    with _lock:
        now = time.time()
        if _cache["body"] is not None and now - _cache["at"] < TTL:
            return _cache["body"]
        try:
            # listpools carries everything the board renders, the chain's block
            # cadence included, so this stays one call.
            #
            # include_undeclared: the PAGE shows only signers that declared
            # themselves a pool, but a wallet reading this same feed also has to
            # describe the signer its stake is lent to, which may have declared
            # nothing at all. One fetch serves both; every entry carries
            # `declared`, and the page filters on it.
            data = rpc("listpools", [None, WINDOW, False, True])
        except Exception:
            if _cache["body"] is not None and now - _cache["at"] < STALE_OK:
                return _cache["body"]
            raise
        data["generated_at"] = int(now)
        body = json.dumps(data).encode()
        _cache["at"], _cache["body"] = now, body
        return body


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "sequentia-pool-board"
    sys_version = ""

    def _send(self, code, body, ctype, cache=True):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Read-only public data. The board may be served from the site root
        # while this runs on another port or host.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control",
                         f"public, max-age={int(TTL)}" if cache else "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/pools.json", "/pools/pools.json"):
            try:
                self._send(200, pools_json(), "application/json")
            except Exception as e:
                # Never hand a public caller the node's URL, its credentials or a
                # stack trace; the operator gets the detail from this process's log.
                self._send(503, json.dumps({"error": "pool data unavailable"}).encode(),
                           "application/json", cache=False)
                self.log_error("listpools failed: %s", e)
            return
        if path in ("/", "/index.html", "/pools", "/pools/index.html"):
            index = PAGE_DIR / "index.html"
            if index.is_file():
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"board page not found; set SEQ_POOLS_PAGE",
                           "text/plain", cache=False)
            return
        if path == "/healthz":
            self._send(200, b"ok", "text/plain", cache=False)
            return
        self._send(404, b"not found", "text/plain", cache=False)

    # HEAD is what uptime checks use, and BaseHTTPRequestHandler answers 501
    # without this. _send omits the body for it.
    do_HEAD = do_GET

    def log_message(self, fmt, *args):
        pass  # a public board's access log belongs to the front-end server


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"pool board on http://{BIND}:{PORT}/  (feed at /pools.json, node {RPC_URL})")
    Server((BIND, PORT), Handler).serve_forever()
