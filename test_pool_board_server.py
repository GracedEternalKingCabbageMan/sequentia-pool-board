#!/usr/bin/env python3
# Copyright (c) 2026 The Sequentia developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Tests for the pool board feed. Plain stdlib, no pytest: python3 test_pool_board_server.py

What matters here is not that the server returns JSON, but the four things that
would hurt a public page if they broke:

  * the cache actually caches, including under a burst of concurrent viewers,
    because listpools walks the whole stake registry;
  * a node outage degrades to a stale-but-stamped board rather than an error;
  * no caller input reaches the node and no internal detail reaches the caller;
  * the feed carries every field index.html renders.
"""

import importlib.util
import json
import re
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_server(**env):
    """Import pool-board-server.py fresh, with the given environment."""
    import os
    old = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        spec = importlib.util.spec_from_file_location(
            "pool_board_server_%d" % time.monotonic_ns(), HERE / "pool-board-server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


#: A payload shaped exactly like the node's listpools answer.
SAMPLE = {
    "height": 96000,
    "network_weight": 8000000000000,
    "min_stake": 4000000000000,
    "notice_blocks": 2880,
    "block_seconds": 60,
    "window": 500,
    "pools": [{
        "signer": "02" + "ab" * 32,
        "weight": 5000000000000,
        "own_weight": 1000000000000,
        "delegated_weight": 4000000000000,
        "delegators": 3,
        "network_share": 0.625,
        "eligible": True,
        "committee_ready": True,
        "blocks_produced": 310,
        "blocks_expected": 312.5,
        "reliability": 0.992,
        "payout": "pays one delegator per block ... operator commission 5.00%",
        "policy_in_force": {"activation": 90000, "mode": "lottery", "commission_bp": 500},
        "policy_pending": [{"activation": 99000, "mode": "lottery",
                            "commission_bp": 1000, "blocks_away": 3000}],
    }],
}


class TestCache(unittest.TestCase):
    def test_caches_within_ttl(self):
        mod = load_server(SEQ_POOLS_TTL=60)
        calls = []
        mod.rpc = lambda m, p: (calls.append((m, p)), SAMPLE)[1]
        first = json.loads(mod.pools_json())
        for _ in range(20):
            mod.pools_json()
        self.assertEqual(len(calls), 1, "the board must cost the node one call, not one per viewer")
        self.assertEqual(first["height"], SAMPLE["height"])

    def test_refetches_after_ttl(self):
        mod = load_server(SEQ_POOLS_TTL=0)
        calls = []
        mod.rpc = lambda m, p: (calls.append(m), SAMPLE)[1]
        mod.pools_json()
        mod.pools_json()
        self.assertEqual(len(calls), 2)

    def test_concurrent_burst_costs_one_call(self):
        """The lock must cover the miss itself. Holding it only around the cache
        read would let a crowd arriving at an empty cache all call the node."""
        mod = load_server(SEQ_POOLS_TTL=60)
        calls = []

        def slow_rpc(m, p):
            calls.append(m)
            time.sleep(0.2)   # a real listpools on a large registry
            return SAMPLE

        mod.rpc = slow_rpc
        threads = [threading.Thread(target=mod.pools_json) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), 1, "a burst of viewers stampeded the node")

    def test_only_listpools_is_ever_called(self):
        mod = load_server(SEQ_POOLS_TTL=0, SEQ_POOLS_WINDOW=123)
        seen = []
        mod.rpc = lambda m, p: (seen.append((m, p)), SAMPLE)[1]
        mod.pools_json()
        self.assertEqual(seen, [("listpools", [None, 123, False])],
                         "the feed must issue exactly one fixed query")

    def test_generated_at_is_stamped(self):
        mod = load_server(SEQ_POOLS_TTL=60)
        mod.rpc = lambda m, p: SAMPLE
        self.assertIn("generated_at", json.loads(mod.pools_json()),
                      "the page tells the reader how old the reading is")


class TestOutage(unittest.TestCase):
    def test_serves_stale_when_node_is_down(self):
        mod = load_server(SEQ_POOLS_TTL=0)
        state = {"up": True}

        def flaky(m, p):
            if not state["up"]:
                raise RuntimeError("connection refused")
            return SAMPLE

        mod.rpc = flaky
        good = json.loads(mod.pools_json())
        state["up"] = False
        stale = json.loads(mod.pools_json())
        self.assertEqual(stale["generated_at"], good["generated_at"],
                         "a brief node outage should freeze the board, not break it")

    def test_raises_once_stale_window_passes(self):
        mod = load_server(SEQ_POOLS_TTL=0)
        mod.STALE_OK = 0
        mod.rpc = lambda m, p: SAMPLE
        mod.pools_json()

        def down(m, p):
            raise RuntimeError("connection refused")

        mod.rpc = down
        with self.assertRaises(RuntimeError):
            mod.pools_json()

    def test_cold_start_outage_raises(self):
        mod = load_server(SEQ_POOLS_TTL=60)

        def down(m, p):
            raise RuntimeError("connection refused")

        mod.rpc = down
        with self.assertRaises(RuntimeError):
            mod.pools_json()


class TestHttp(unittest.TestCase):
    """Drive the real handler over a real socket, which is the only way to catch
    a routing or header mistake."""

    def setUp(self):
        self.mod = load_server(SEQ_POOLS_TTL=60, SEQ_POOLS_PORT=0)
        self.mod.rpc = lambda m, p: SAMPLE
        self.srv = self.mod.Server(("127.0.0.1", 0), self.mod.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_feed_routes(self):
        for path in ("/pools.json", "/pools/pools.json", "/pools.json?cachebust=1"):
            status, body, headers = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(json.loads(body)["height"], SAMPLE["height"])
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_page_routes(self):
        for path in ("/", "/index.html", "/pools/", "/pools/index.html"):
            status, body, _ = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b"<title>", body)

    def test_head_is_answered(self):
        status, body, _ = self.get("/healthz", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"", "HEAD must not carry a body")

    def test_unknown_path_is_404(self):
        self.assertEqual(self.get("/../etc/passwd")[0], 404)
        self.assertEqual(self.get("/wallet")[0], 404)

    def test_node_failure_leaks_nothing(self):
        def down(m, p):
            raise RuntimeError("connect to http://user:hunter2@127.0.0.1:7041 refused")

        self.mod.rpc = down
        self.mod._cache["body"] = None
        status, body, _ = self.get("/pools.json")
        self.assertEqual(status, 503)
        self.assertNotIn(b"hunter2", body)
        self.assertNotIn(b"7041", body)
        self.assertEqual(json.loads(body), {"error": "pool data unavailable"})


class TestPageContract(unittest.TestCase):
    """The page renders a fixed set of fields. If the node's listpools is renamed
    on one side only, a column silently empties on a public page; this is what
    catches that."""

    def test_page_reads_only_fields_the_feed_provides(self):
        page = (HERE / "index.html").read_text()
        provided = set(SAMPLE) | {"generated_at"}
        for field in ("height", "network_weight", "min_stake", "notice_blocks",
                      "block_seconds", "window", "pools", "generated_at"):
            self.assertIn(field, provided)
            self.assertIn(field, page, "index.html no longer reads %s" % field)

        pool_fields = set(SAMPLE["pools"][0])
        for field in ("signer", "weight", "own_weight", "delegated_weight", "delegators",
                      "network_share", "eligible", "committee_ready", "blocks_produced",
                      "blocks_expected", "reliability", "payout", "policy_in_force",
                      "policy_pending"):
            self.assertIn(field, pool_fields)
            self.assertIn(field, page, "index.html no longer reads pool.%s" % field)

    def test_page_fetches_the_path_the_deploy_serves(self):
        page = (HERE / "index.html").read_text()
        self.assertIn("/pools/pools.json", page)
        readme = (HERE / "README.md").read_text()
        self.assertIn("/pools/pools.json", readme, "README must document the path the page fetches")

    def test_page_is_self_contained(self):
        """No external CSS, JS or images: the board must render with only the
        site's own assets, which is also what keeps it deployable anywhere."""
        page = (HERE / "index.html").read_text()
        for m in re.findall(r'(?:src|href)="([^"]+)"', page):
            self.assertFalse(m.startswith("http://") or m.startswith("https://")
                             or m.startswith("//"),
                             "external asset in the board page: %s" % m)

    def test_page_escapes_node_supplied_text(self):
        """Signer keys and payout strings come from the chain. They are hex and
        generated text today, but the page must not be one bad string away from
        injecting markup."""
        page = (HERE / "index.html").read_text()
        self.assertIn("const esc =", page)
        self.assertIn("esc(p.signer)", page)
        self.assertIn("esc(p.payout)", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
