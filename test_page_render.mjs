// Copyright (c) 2026 The Sequentia developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.
//
// Render the board page's own JavaScript against a feed and check what came
// out.  node test_page_render.mjs        (fixture, no network)
//      node test_page_render.mjs --live  (against the deployed feed)
//
// test_pool_board_server.py greps the page for field names, which catches a
// rename but not a page that throws halfway through building the table: the
// browser shows a half-drawn board and reports nothing. This actually runs the
// render.

import fs from 'fs';
import { execFileSync } from 'child_process';

const HERE = new URL('.', import.meta.url).pathname;
const LIVE = process.argv.includes('--live');
const FEED_URL = 'https://sequentiatestnet.com/pools/pools.json';

/// A feed shaped exactly like the node's listpools answer, exercising the cases
/// that have caught bugs: a pool with an announced change, one that has
/// committed to nothing, one producing nothing at all, and one owed nothing.
const FIXTURE = {
  height: 96000,
  network_weight: 8000000000000,
  min_stake: 4000000000000,
  notice_blocks: 1440,
  block_seconds: 60,
  window: 500,
  generated_at: Math.floor(Date.now() / 1000),
  pools: [
    {
      signer: '02' + 'ab'.repeat(32),
      weight: 5000000000000, own_weight: 1000000000000, delegated_weight: 4000000000000,
      delegators: 3, network_share: 0.625, eligible: true, committee_ready: true,
      blocks_produced: 310, blocks_expected: 312.5, reliability: 0.992,
      payout: 'pays one delegator per block, drawn by stake weight ... commission 5.00%',
      policy_in_force: { activation: 90000, mode: 'lottery', commission_bp: 500 },
      policy_pending: [{ activation: 99000, mode: 'lottery', commission_bp: 1000, blocks_away: 3000 }],
    },
    {
      signer: '03' + 'cd'.repeat(32),
      weight: 2000000000000, own_weight: 2000000000000, delegated_weight: 0,
      delegators: 0, network_share: 0.25, eligible: true, committee_ready: false,
      blocks_produced: 0, blocks_expected: 125.0, reliability: 0,
      payout: 'no policy committed: this pool keeps everything the blocks it produces earn',
      policy_pending: [],
    },
    {
      signer: '02' + 'ef'.repeat(32),
      weight: 0, own_weight: 0, delegated_weight: 0,
      delegators: 0, network_share: 0, eligible: false, committee_ready: false,
      blocks_produced: 0, blocks_expected: 0,
      payout: 'no policy committed: this pool keeps everything the blocks it produces earn',
      policy_pending: [],
    },
  ],
};

const feed = LIVE
  ? JSON.parse(execFileSync('curl', ['-sf', FEED_URL], { encoding: 'utf8', maxBuffer: 32 << 20 }))
  : FIXTURE;

const page = fs.readFileSync(HERE + 'index.html', 'utf8');
const script = page.match(/<script>([\s\S]*?)<\/script>/)[1];

// A DOM just real enough for the page's own render path.
const nodes = {};
const mk = (id) => (nodes[id] = { id, innerHTML: '', textContent: '', className: '', querySelectorAll: () => [] });
['stats', 'pending', 'rows', 'status', 'tbl'].forEach(mk);
const doc = { getElementById: (id) => nodes[id] || mk(id), querySelectorAll: () => [] };

const api = new Function('document', 'fetch', 'setInterval', 'console',
  script + '\nreturn {render, load, whenBinds, seq, pct, policyLine};')(
  doc, async () => ({ ok: true, json: async () => feed }), () => 0, console);

await api.load();

const rows = nodes.rows.innerHTML;
const stats = nodes.stats.innerHTML;
const pending = nodes.pending.innerHTML;
const status = nodes.status.textContent;

let failures = 0;
const check = (cond, what) => {
  if (cond) console.log('ok   -', what);
  else { console.log('FAIL -', what); failures++; }
};

check(stats.includes('Network stake'), 'stat tiles render');
check(stats.includes('Notice period'), 'the notice period is shown');
check((rows.match(/<tr class="row"/g) || []).length === feed.pools.length,
  `one row per pool (${feed.pools.length})`);
check(!rows.includes('undefined') && !stats.includes('undefined'), 'nothing renders as "undefined"');
check(!rows.includes('NaN') && !stats.includes('NaN') && !pending.includes('NaN'), 'nothing renders as NaN');
check(status.includes('pool(s)'), 'the status line renders');

// The honest defaults have to survive rendering; they are the reason the board
// exists, and a blank column would read as "nothing to worry about".
if (feed.pools.some(p => !p.policy_in_force)) {
  check(rows.includes('keeps everything'), 'a pool with no policy says it keeps everything');
}
// A pool producing nothing must show its zero rather than be skipped or blank.
if (feed.pools.some(p => p.reliability === 0)) {
  check(/>0\.00</.test(rows) || rows.includes('0.00'), 'a pool at reliability 0 shows it');
}
// A pool owed nothing is not "unreliable"; it must not render as 0.00.
if (feed.pools.some(p => p.reliability === undefined && p.blocks_expected === 0)) {
  check(rows.includes('not owed any'), 'a pool owed no blocks is not called unreliable');
}
// The audit surface: an announced change belongs above the table with a deadline.
if (feed.pools.some(p => (p.policy_pending || []).length)) {
  check(pending.includes('Announced changes'), 'a pending change is pulled to the top');
  check(/blocks \(about /.test(pending), 'the pending change carries a deadline');
}

check(/blocks \(about /.test(api.whenBinds(1440, feed.block_seconds)), 'whenBinds renders a deadline');
check(api.seq(100000000) === '1', 'seq() renders 1e8 atoms as 1');

console.log(failures ? `\n${failures} FAILED` : '\nPAGE RENDER OK');
process.exit(failures ? 1 : 0);
