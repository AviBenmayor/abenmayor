// Data loading + aggregation. Ported from dashboard/model.py so the numbers
// match the validated Part 1/3 logic exactly — only the runtime changed.

export async function loadData() {
  const [pos, venueCash, quotes] = await Promise.all([
    fetch('data/pos.json').then((r) => r.json()),
    fetch('data/venue_cash.json').then((r) => r.json()),
    fetch('data/quotes.json').then((r) => r.json()),
  ]);
  // timestamps in the source are UTC but carry no zone suffix — append 'Z' so
  // JS parses them as UTC instead of local time. Without this, late-evening
  // fills (e.g. 05-27 22:24 UTC) bin into the wrong calendar day anywhere
  // west of Greenwich.
  for (const r of pos) {
    r.filled_at = new Date(r.filled_at + 'Z');
    r.mark_as_of = r.mark_as_of ? new Date(r.mark_as_of + 'Z') : null;
  }
  for (const r of venueCash) r.as_of = new Date(r.as_of + 'Z');
  return { pos, venueCash, quotes };
}

export function groupBy(rows, keyFn) {
  const m = new Map();
  for (const r of rows) {
    const k = keyFn(r);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  return m;
}

export function sumByDim(rows, dimKey, valueKeys) {
  const groups = groupBy(rows, (r) => r[dimKey]);
  const out = [];
  for (const [key, g] of groups) {
    const rec = { key, count: g.length };
    for (const vk of valueKeys) rec[vk] = g.reduce((s, r) => s + (r[vk] ?? 0), 0);
    out.push(rec);
  }
  return out;
}

export function sum(rows, key) {
  return rows.reduce((s, r) => s + (r[key] ?? 0), 0);
}

// ---- Part 3: hold view ----

export function holdPopulation(pos) {
  return pos.filter((r) => (r.status === 'WON' || r.status === 'LOST') && r.theoretical_hold_bps != null);
}

export function stakeWeightedHold(rows) {
  const stake = sum(rows, 'mag_stake');
  if (!stake) return { fills: rows.length, stake: 0, pnl: 0, theoBps: NaN, realBps: NaN, gapBps: NaN };
  const theo = rows.reduce((s, r) => s + r.theoretical_hold_bps * r.mag_stake, 0) / stake;
  const pnl = sum(rows, 'realized_pnl');
  const real = (1e4 * pnl) / stake;
  return { fills: rows.length, stake, pnl, theoBps: theo, realBps: real, gapBps: real - theo };
}

function mulberry32(seed) {
  let s = seed >>> 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function percentile(sorted, p) {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

export function bootstrapHoldCI(rows, { n = 20000, seed = 7 } = {}) {
  const m = rows.length;
  const totalStake = sum(rows, 'mag_stake');
  if (m === 0 || !totalStake) return [NaN, NaN];
  const rng = mulberry32(seed);
  const pnl = rows.map((r) => r.realized_pnl);
  const stake = rows.map((r) => r.mag_stake);
  const draws = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let pSum = 0;
    let sSum = 0;
    for (let j = 0; j < m; j++) {
      const idx = Math.floor(rng() * m);
      pSum += pnl[idx];
      sSum += stake[idx];
    }
    draws[i] = (1e4 * pSum) / sSum;
  }
  const sorted = Array.from(draws).sort((a, b) => a - b);
  return [percentile(sorted, 2.5), percentile(sorted, 97.5)];
}

/** Kish effective sample size: (Σw)²/Σw² with stakes as weights. Stake
 * concentration makes 249 uneven bets behave like far fewer even ones. */
export function kishNeff(rows) {
  const sum = rows.reduce((s, r) => s + r.mag_stake, 0);
  const sq = rows.reduce((s, r) => s + r.mag_stake * r.mag_stake, 0);
  return sq ? (sum * sum) / sq : 0;
}

export function holdByDimension(rows, dimKey) {
  const groups = groupBy(rows, (r) => r[dimKey]);
  const out = [];
  for (const [key, g] of groups) {
    const s = stakeWeightedHold(g);
    const [ciLo, ciHi] = bootstrapHoldCI(g);
    const signal = !(ciLo <= s.theoBps && s.theoBps <= ciHi);
    const sigma = (ciHi - ciLo) / 3.92; // 95% CI width -> 1σ
    out.push({
      dim: key, ...s, ciLo, ciHi, signal, sigma,
      gapSigma: sigma ? s.gapBps / sigma : NaN,
      neff: kishNeff(g),
    });
  }
  out.sort((a, b) => b.stake - a.stake);
  return out;
}
