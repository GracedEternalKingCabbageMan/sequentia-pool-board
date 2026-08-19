# Sequentia staking pool board

The public board of Sequentia staking pools: every signer producing blocks on the network,
the stake weight it commands, how much of that was lent to it and by how many delegators,
how reliably it actually produces, and what it has committed on-chain to paying out.

Live at [sequentiatestnet.com/pools/](https://sequentiatestnet.com/pools/).

Two files, no build step:

- [`index.html`](index.html) — the whole page. Inline CSS and JS, no external assets,
  styled to match the rest of the site.
- [`pool-board-server.py`](pool-board-server.py) — the one thing a static page cannot do,
  which is read a node. Serves `listpools` as `GET /pools.json`, cached.

## What it is for

Delegating on Sequentia is non-custodial by construction. The pool's key never appears in
the staking output's spending condition, so a pool can never move a delegator's coins, and
reclaiming the delegation needs nobody's cooperation. What a delegator *is* trusting a pool
for is the reward, and that trust rests on two things being visible:

1. **What the pool has committed to.** A pool that has committed to nothing keeps every fee
   its blocks earn. That is the default rather than an abuse, and the board says so in
   plain words instead of leaving the column blank.
2. **Announced changes, while there is still time to act.** A payout policy cannot bind
   until it has been announced on-chain for the chain's notice period. That protection is
   worth nothing to a delegator who does not see the notice, so every announcement still
   inside its window is pulled to the top of the page with a countdown in blocks and an
   approximate date.

`blocks_produced` against `blocks_expected` is the number nobody advertises: a pool holding
a tenth of the network's stake should produce about a tenth of the blocks, and well under
that means it is offline or missing its slots while its delegators earn nothing.

## The feed

`pool-board-server.py` is deliberately **not** an RPC proxy. It exposes exactly one fixed
query, no caller-supplied method or parameter reaches the node, and there is no wallet in
the picture. It also caches behind a single lock, because a public board is polled by every
viewer at once while `listpools` walks the whole stake registry: a crowd arriving together
costs the node one call, not one each.

```
SEQ_RPC_COOKIE=/root/sequentia/pool-board-node/testnet3/.cookie \
SEQ_POOLS_PORT=8091 python3 pool-board-server.py
```

| Variable | Default | Meaning |
|---|---|---|
| `SEQ_RPC_URL` | `http://127.0.0.1:7041` | node RPC endpoint |
| `SEQ_RPC_COOKIE` | *(none)* | path to the node's `.cookie` (preferred). On `chain=test` the node writes it to `<datadir>/testnet3/.cookie`, not `<datadir>/test/`. |
| `SEQ_RPC_USER` / `SEQ_RPC_PASSWORD` | *(none)* | RPC credentials, when not using a cookie |
| `SEQ_POOLS_WINDOW` | `500` | blocks to measure production reliability over |
| `SEQ_POOLS_TTL` | `15` | seconds to cache the answer for |
| `SEQ_POOLS_PORT` | `8091` | local listen port |
| `SEQ_POOLS_BIND` | `127.0.0.1` | listen address; keep it loopback behind a front-end |
| `SEQ_POOLS_PAGE` | *(this directory)* | where `index.html` lives, so the server can serve it too |

The node it reads must be recent enough to have `listpools` (Sequentia Core 24.2.0 or
later). It does not need a wallet and must not be a block producer: a read-only follower is
exactly right.

## Deploy

The page fetches the absolute path `/pools/pools.json`, so serve the page at `/pools/` and
the feed beneath it. With Caddy, which is what the testnet box runs:

```caddyfile
redir /pools /pools/ permanent
handle_path /pools/* {
	reverse_proxy 127.0.0.1:8091
}
```

`handle_path` strips the prefix, so the service sees `/` for the page and `/pools.json` for
the feed; it answers both. Run it under systemd so it comes back after a reboot. It holds no
state and can be restarted freely.

## Tests

```
python3 test_pool_board_server.py   # the feed
node test_page_render.mjs           # the page, rendered against a fixture
node test_page_render.mjs --live    # ...and against the deployed feed
```

`test_page_render.mjs` runs the page's own JavaScript over a feed in a minimal DOM and
checks what came out: one row per pool, nothing rendering as `undefined` or `NaN`, a pool
with no committed policy still saying it keeps everything, a pool producing nothing showing
its zero, a pool owed nothing NOT being called unreliable, and an announced change reaching
the top of the page with a deadline. Grepping the page for field names catches a rename;
this catches a page that throws halfway through building the table, which a browser shows
as a half-drawn board and reports nowhere.

The Python tests cover the routes, the cache (including that a burst of concurrent viewers costs one
upstream call), error handling, that no caller input can reach the node, and that the feed
carries every field [`index.html`](index.html) renders. That last one is the point: a rename
on either side fails the test rather than silently emptying a column on a public page.

## Related

- Node, RPCs (`listpools`, `delegatestake`, `undelegatestake`, `listdelegations`,
  `announcepayout`) and the consensus design:
  [Sequentia](https://github.com/GracedEternalKingCabbageMan/Sequentia), and
  `doc/sequentia/04-proof-of-stake.md` §2 there for the delegation and payout-record design.
- Starting a pool is a node operation and is only offered in the desktop node wallet's
  Staking tab. Other wallets delegate and leave; they do not run pools.
