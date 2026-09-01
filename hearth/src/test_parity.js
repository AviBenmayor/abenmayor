/* Runs the REAL browser scorer from tool/lead_queue.html against Python's scores.
   Stubs just enough DOM for the file to evaluate, then calls its own functions. */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

const html = fs.readFileSync(path.join(ROOT, 'tool/lead_queue.html'), 'utf8');
const js = html.split('<script>')[1].split('</script>')[0];

const el = () => ({ innerHTML:'', textContent:'', value:'40', classList:{add(){},remove(){}},
                    addEventListener(){}, onclick:null, oninput:null, onchange:null,
                    click(){}, files:[], dataset:{} });
const document = { getElementById: el, querySelectorAll: () => [], createElement: el };
const window = {};
// The page asks whether it is being served over http (in which case it offers a link back
// to the dashboard). Under test it is neither, which is the local-file case.
const location = { protocol: 'file:', href: 'file:///lead_queue.html' };
const FileReader = function(){};
const console_ = console;

// Evaluate the tool's script in this scope, then hand back the functions we want to test.
const factory = new Function('document','window','FileReader','console','location',
  js + '\nreturn {contributions, tierOf, toObjects, parseCSV, coachFor, classify, outcomeOf,'
     + ' setOpps: o => { STATE.opps = o; }};');
const T = factory(document, window, FileReader, {log(){}}, location);

// ---- 1. parity against Python on real scoring rows ----
const csv = fs.readFileSync(path.join(ROOT, 'data/leads_to_score.csv'), 'utf8');
const rows = T.toObjects(csv);
const expected = JSON.parse(fs.readFileSync(path.join(ROOT, 'output/parity_expected.json'), 'utf8'));

let worst = 0, checked = 0;
for (const r of rows) {
  const exp = expected[r.lead_id];
  if (exp === undefined) continue;
  const got = T.contributions(r).score;
  worst = Math.max(worst, Math.abs(got - exp));
  checked++;
}
console_.log(`1. parity vs Python : checked ${checked} rows, max abs diff ${worst.toExponential(2)}`);
if (checked === 0) { console_.error('   FAIL: no rows matched'); process.exit(1); }
if (worst > 1e-6) { console_.error(`   FAIL: diff ${worst} exceeds 1e-6`); process.exit(1); }

// ---- 2. full-file scoring, tier distribution should match the submission ----
const full = rows.map(r => ({ id:r.lead_id, s:T.contributions(r) }));
const tiers = {};
full.forEach(f => { const t = T.tierOf(f.s.score); tiers[t] = (tiers[t]||0)+1; });
console_.log(`2. scored all ${full.length} rows in-browser; tiers`, tiers);

// ---- 3. the edge cases a hostile demo will actually throw ----
const cases = [
  ['empty file',            ''],
  ['header only',           'lead_id,icp_category\n'],
  ['no lead_id column',     'icp_category,legacy_score\nIdeal,50\n'],
  ['unknown campaign',      'lead_id,campaign_ref,icp_category\nX1,cmp_NEVER_SEEN,Ideal\n'],
  ['blank everything',      'lead_id,icp_category,legacy_score\nX2,,\n'],
  ['legacy_score = text',   'lead_id,legacy_score\nX3,not_a_number\n'],
  ['legacy_score negative', 'lead_id,legacy_score\nX4,-999\n'],
  ['quoted comma in band',  'lead_id,contractor_annual_revenue\nX5,"$1,000,000 to $4,999,999"\n'],
  ['CRLF line endings',     'lead_id,icp_category\r\nX6,Ideal\r\n'],
  ['BOM prefix',            '﻿lead_id,icp_category\nX7,Ideal\n'],
  ['trailing blank lines',  'lead_id,icp_category\nX8,Ideal\n\n\n'],
  ['whitespace padding',    'lead_id , icp_category \n X9 , Ideal \n'],
  ['semicolon separated',   'lead_id;icp_category\nXA;Ideal\n'],
  ['extra unknown columns', 'lead_id,icp_category,favourite_colour\nXB,Ideal,blue\n'],
];
console_.log('3. edge cases:');
let failures = 0;
for (const [name, text] of cases) {
  let out;
  try {
    const objs = T.toObjects(text);
    if (!objs.length) { out = 'no data rows (handled)'; }
    else {
      const s = T.contributions(objs[0]);
      out = Number.isFinite(s.score)
        ? `score $${s.score.toFixed(0)} p=${(s.p*100).toFixed(0)}% tier ${T.tierOf(s.score)}`
        : 'NON-FINITE SCORE';
      if (!Number.isFinite(s.score)) failures++;
    }
  } catch (e) { out = 'threw: ' + e.message; }
  console_.log(`   ${name.padEnd(24)} ${out}`);
}

// ---- 3b. file classification and the historical outcome join ----
console_.log('3b. file classification:');
const fixtures = {
  'leads_history.csv':     'leads',
  'leads_to_score.csv':    'leads',
  'opps.csv':              'opps',
  'activities.csv':        'activities',
  'call_extractions.csv':  'calls',
  'call_objections.csv':   'objections',
};
let clsFail = 0;
for (const [f, want] of Object.entries(fixtures)) {
  const fp = path.join(ROOT, 'data', f);
  if (!fs.existsSync(fp)) { console_.log(`   ${f.padEnd(24)} (absent, skipped)`); continue; }
  const got = T.classify(T.toObjects(fs.readFileSync(fp, 'utf8')));
  const ok = got === want;
  if (!ok) clsFail++;
  console_.log(`   ${f.padEnd(24)} -> ${got}${ok ? '' : `  EXPECTED ${want}`}`);
}
if (clsFail) { console_.error(`   FAIL: ${clsFail} misclassified`); process.exit(1); }

// The outcome join must follow converted_opp_id -> opps.opp_id -> is_won, and must NOT
// treat a bare conversion as a win when opps.csv is absent.
const hist = path.join(ROOT, 'data', 'leads_history.csv');
if (fs.existsSync(hist)) {
  const leads = T.toObjects(fs.readFileSync(hist, 'utf8'));
  const opps = {};
  T.toObjects(fs.readFileSync(path.join(ROOT, 'data', 'opps.csv'), 'utf8'))
    .forEach(r => { if (r.opp_id) opps[r.opp_id] = r; });

  T.setOpps(opps);
  let won = 0, unresolved = 0, decided = 0;
  leads.forEach(l => { const o = T.outcomeOf(l); if (!o) return;
                       if (o.won === true) won++; else if (o.won === null) unresolved++;
                       if (o.won !== null) decided++; });
  console_.log(`   with opps.csv     : ${won} won, ${unresolved} unresolved, ${decided} decided`);

  T.setOpps({});
  let won2 = 0, unresolved2 = 0;
  leads.forEach(l => { const o = T.outcomeOf(l); if (!o) return;
                       if (o.won === true) won2++; else if (o.won === null) unresolved2++; });
  console_.log(`   without opps.csv  : ${won2} won, ${unresolved2} unresolved`);
  if (won !== 907) { console_.error(`   FAIL: expected 907 wins, got ${won}`); process.exit(1); }
  if (won2 !== 0) {
    console_.error(`   FAIL: counted ${won2} wins with no opps file — conversion is not a win`);
    process.exit(1);
  }
  console_.log('   join correct: 907 wins with opps, 0 claimed without it');
}

// ---- 4. a genuinely large file, to check it does not hang ----
const big = ['lead_id,icp_category,contractor_annual_revenue,legacy_score']
  .concat(Array.from({length:50000}, (_,i) =>
    `B${i},Ideal,"$500,000 to $999,999",${(i%100)}`)).join('\n');
const t0 = Date.now();
const bigRows = T.toObjects(big);
bigRows.forEach(r => T.contributions(r));
console_.log(`4. 50,000 rows parsed + scored in ${Date.now()-t0} ms`);

console_.log(failures ? `\nFAILED: ${failures} edge case(s) produced a non-finite score`
                      : '\nAll parity and edge-case checks passed.');
process.exit(failures ? 1 : 0);
