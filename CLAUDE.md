# Working on the Sequentia staking pool board

Two files and a test. Keep it that way.

## What this repo is

A static page (`index.html`) and the minimal read-only feed it needs
(`pool-board-server.py`). It has no build step, no dependencies outside the Python
standard library, and no state. If a change here starts to want a framework, a database or
a package manifest, the change is in the wrong repo.

It deliberately does **not** live in the node repo. Nothing that is not the node belongs
there.

## The two rules that matter

**The feed is not an RPC proxy.** It issues exactly one fixed query, `listpools`, with
parameters this repo chooses. No caller-supplied method or argument may ever reach the
node, and no node URL, credential or stack trace may ever reach a caller. Both directions
are covered by tests; keep them covered.

**The page must stay honest about what the chain does and does not enforce.** A pool that
has committed to nothing keeps every fee, `direct` mode stops a silent redirect but does
not make a payout fair, and a `lottery` share is exact over time but lumpy. Do not let
marketing language creep in: the whole reason the board exists is that a delegator can
check these things.

## The field contract

`index.html` renders a fixed set of fields from `listpools`. `test_pool_board_server.py`
asserts every one of them against a sample payload shaped like the node's answer. If the
node's RPC gains or renames a field, update the sample and the page together. A silently
empty column on a public page is the failure this prevents.

The node side of the same contract is asserted in
`test/functional/feature_pos_pools.py` in the
[Sequentia](https://github.com/GracedEternalKingCabbageMan/Sequentia) repo.

## Tests

```
python3 test_pool_board_server.py
```

No network and no node required. Run them before every push; there is no CI here and the
page is public.

## Deploy

The box pulls from GitHub, always. Never edit these files on the server and never copy them
there from a workstation. See [README.md](README.md) for the Caddy route and the systemd
unit.

## Style

No em dashes in public copy. The network is "Sequentia"; the token is the "Sequence token
(SEQ)". Never write "the SEQ chain".
