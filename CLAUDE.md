# Working on the Sequentia staking pool board

Two files and two tests. Keep it that way.

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
has committed to nothing keeps every fee. Of the three committed modes, a `split` policy
pays exact proportional shares from an on-chain pot (anyone can trigger the distribution,
but leaving forfeits what is accrued and unclaimed), a `lottery` share is exact over time
but lumpy, and `direct` stops a silent redirect but does not make a payout fair. Do not let
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
node test_page_render.mjs
```

The second one runs the page's own JavaScript over a feed in a minimal DOM, because
grepping the page for field names catches a rename but not a page that throws halfway
through building the table. Add a case to its fixture whenever you add a state the page
renders differently. No network and no node required. Run them before every push; there is no CI here and the
page is public.

## Deploy

The box pulls from GitHub, always. Never edit these files on the server and never copy them
there from a workstation. See [README.md](README.md) for the Caddy route; the service runs
under systemd on the box, but no unit is committed here.

<!-- BEGIN SHARED AGENT CONVENTIONS: identical in every Sequentia repo. Change it in all of them together. -->
## Working with git and GitHub here

These rules are the same in every Sequentia repository. They are repeated in each
one because this file is the only thing an agent is guaranteed to read, whatever
machine it is working from.

**Nothing pushed to GitHub credits Claude, Anthropic, or any AI tool.** No
`Co-Authored-By: Claude` trailer, no `Claude-Session:` trailer or `claude.ai`
link, no "Generated with Claude Code" in a commit message or a pull request body,
no `claude/*` branch names or session ids, and no mention in source, comments,
docs or issue text. Agent tooling offers several of these by default; compose the
message without them rather than stripping them afterwards.

**Author every commit as**
`GracedEternalKingCabbageMan <151803062+GracedEternalKingCabbageMan@users.noreply.github.com>`.
Never a personal address.

**Every change lands through a pull request that you merge yourself, at once.**
There is no reviewer on this project; the pull request exists so the reasoning is
recorded beside the diff. Branch, push, open it, merge it, delete the branch, all
in one sitting. Pushing straight to the default branch is the rule most often
broken here, and it is the one that costs the record. A pull request stays open
only when the repository owner asks for that specific one, and that never carries
over to the next.

**Name branches `area/short-description`**: `fix/`, `doc/`, `feature/`, `test/`,
`build/`, or the component being changed. Never a tool name, a session id, or
`worktree-*`.

**Write the subject as `area: what changed`**, one line, 72 characters at the
outside and 50 where you can manage it. Put the reasoning in the body, and
explain why rather than what.

**These repositories are public and world-readable.** Never commit private keys,
seeds, `wallet.dat`, RPC credentials, `.env` files or API tokens. Read the diff
before every commit. Secrets belong on the server and in offline backups.

**A file belongs to the repository whose code it describes.** Decide which repo
owns it before writing it; if it landed in the wrong one, move it rather than
deleting it.

**Push the same day you commit.** The testnet server pulls only from GitHub, so a
branch left on one laptop is invisible to every other machine and to the box.
<!-- END SHARED AGENT CONVENTIONS -->

## Style

No em dashes in public copy. The network is "Sequentia"; the token is the "Sequence token
(SEQ)". Never write "the SEQ chain".
