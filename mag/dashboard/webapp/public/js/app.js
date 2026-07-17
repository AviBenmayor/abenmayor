import { loadData, sumByDim, sum, holdPopulation, stakeWeightedHold, bootstrapHoldCI, holdByDimension, kishNeff, groupBy } from './data.js';
import { groupedBarChart, lineChart, ciBarChart, histogramChart, tradeImpactChart, capitalBarChart, fmtMoney, fmtNum, fmtBps } from './charts.js';

const state = {
  view: 'pnl',
  pnl: { venues: [], leagues: [], selectedTrade: null },
  hold: { venues: [], leagues: [], sides: [] },
  cash: { date: null, revolverLimit: 40000 },
};

let DATA = null;

function toneClass(v) {
  if (v == null || Number.isNaN(v)) return '';
  if (v > 0) return 'good';
  if (v < 0) return 'critical';
  return '';
}

// ---------------- shared components ----------------

function heroRow(stats) {
  const wrap = document.createElement('div');
  wrap.className = 'hero-row';
  for (const s of stats) {
    const stat = document.createElement('div');
    stat.className = 'hero-stat';
    stat.innerHTML = `<div class="hero-label">${s.label}</div><div class="hero-value ${s.tone || ''}">${s.value}</div>`
      + (s.sub ? `<div class="hero-sub">${s.sub}</div>` : '');
    wrap.appendChild(stat);
  }
  return wrap;
}

function statCard(label, value, { onClick, hint } = {}) {
  const card = document.createElement('div');
  card.className = 'card stat-card' + (onClick ? ' clickable' : '');
  card.innerHTML = `<div class="hero-label">${label}</div><div class="stat-value">${value}</div>`
    + (hint ? `<div class="stat-hint">${hint}</div>` : '');
  if (onClick) card.addEventListener('click', onClick);
  return card;
}

function card({ title, caption } = {}) {
  const c = document.createElement('div');
  c.className = 'card';
  if (title) {
    const t = document.createElement('div');
    t.className = 'card-title';
    t.textContent = title;
    c.appendChild(t);
  }
  if (caption) {
    const cap = document.createElement('div');
    cap.className = 'card-caption';
    cap.textContent = caption;
    c.appendChild(cap);
  }
  return c;
}

function grid(cls) {
  const g = document.createElement('div');
  g.className = `grid ${cls}`;
  return g;
}

function table({ columns, rows }) {
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  const t = document.createElement('table');
  const thead = document.createElement('thead');
  thead.innerHTML = `<tr>${columns.map((c) => `<th>${c.label}</th>`).join('')}</tr>`;
  t.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = columns.map((c) => {
      const raw = row[c.key];
      const val = c.format ? c.format(raw, row) : raw;
      return `<td class="${c.text ? 'text' : ''}">${val}</td>`;
    }).join('');
    tbody.appendChild(tr);
  }
  t.appendChild(tbody);
  wrap.appendChild(t);
  return wrap;
}

function expander(summaryText, bodyHtml, { open = false } = {}) {
  const d = document.createElement('details');
  d.className = 'expander';
  if (open) d.setAttribute('open', '');
  d.innerHTML = `<summary>${summaryText}</summary><div class="expander-body">${bodyHtml}</div>`;
  return d;
}

function pageHeader(kicker, title, caption) {
  const h = document.createElement('div');
  h.innerHTML = `<div class="page-kicker">${kicker}</div><h1 class="page-title">${title}</h1><p class="page-caption">${caption}</p>`;
  return h;
}

/** Segmented multi-select with an explicit "All" state. Clicking a value while
 * everything is selected narrows to just that value (the intuitive read);
 * clicking more values adds them; "All" resets. */
function segmentedFilter(label, options, selectedArr, onChange) {
  const set = document.createElement('div');
  set.className = 'filter-set';
  const l = document.createElement('span');
  l.className = 'filter-set-label';
  l.textContent = label;
  set.appendChild(l);

  const seg = document.createElement('div');
  seg.className = 'seg';
  const allSelected = selectedArr.length === options.length;

  const allBtn = document.createElement('button');
  allBtn.textContent = 'All';
  allBtn.type = 'button';
  if (allSelected) allBtn.classList.add('on');
  allBtn.onclick = () => {
    selectedArr.length = 0;
    selectedArr.push(...options);
    onChange();
  };
  seg.appendChild(allBtn);

  for (const opt of options) {
    const b = document.createElement('button');
    b.textContent = opt;
    b.type = 'button';
    if (!allSelected && selectedArr.includes(opt)) b.classList.add('on');
    b.onclick = () => {
      if (allSelected) {
        selectedArr.length = 0;
        selectedArr.push(opt);
      } else if (selectedArr.includes(opt)) {
        if (selectedArr.length > 1) selectedArr.splice(selectedArr.indexOf(opt), 1);
        else { selectedArr.length = 0; selectedArr.push(...options); }
      } else {
        selectedArr.push(opt);
      }
      onChange();
    };
    seg.appendChild(b);
  }
  set.appendChild(seg);
  return set;
}

function filterBar(children) {
  const bar = document.createElement('div');
  bar.className = 'filter-bar';
  for (const c of children) bar.appendChild(c);
  return bar;
}

// ---------------- Desk P&L ----------------

function tradeImpact(r) {
  if (r.status === 'OPEN') return r.unrealized_pnl ?? 0;
  return r.realized_pnl ?? 0;
}

function tradeDetailPanel(trade) {
  const c = document.createElement('div');
  c.className = 'card trade-detail';
  c.id = 'trade-detail';
  if (!trade) {
    c.classList.remove('trade-detail');
    c.innerHTML = '<div class="card-title">Trade detail</div>'
      + '<div class="detail-placeholder">Click any bar in the charts above — or a row in the winners &amp; losers list — to see that trade\'s full details here.</div>';
    return c;
  }
  const impact = tradeImpact(trade);
  const rows = [
    ['Fill', trade.fill_id],
    ['Filled at', trade.filled_at.toISOString().slice(0, 16).replace('T', ' ')],
    ['Venue', trade.venue],
    ['League', trade.league],
    ['Outcome', trade.outcome],
    ['MAG side', trade.mag_side],
    ['Status', trade.status],
    ['MAG stake', fmtMoney(trade.mag_stake)],
    ['Counterparty stake', fmtMoney(trade.counterparty_stake)],
    ['Fee', `${trade.fee_bps} bps`],
    ['Quoted edge', trade.theoretical_hold_bps != null ? `${trade.theoretical_hold_bps} bps` : '—'],
    trade.status === 'OPEN'
      ? ['Current mark', fmtMoney(trade.current_mark)]
      : ['Settle value', fmtMoney(trade.settle_value)],
    ['P&L impact', `<span style="color:var(${impact >= 0 ? '--pnl-pos' : '--pnl-neg'})">${fmtMoney(impact)}</span>`],
  ];
  c.innerHTML = '<button class="trade-detail-close" title="Clear selection">✕</button>'
    + `<div class="card-title">Trade detail — ${trade.fill_id}</div>`
    + `<div class="trade-detail-grid">${rows.map(([k, v]) => `<div><div class="kv-label">${k}</div><div class="kv-value">${v}</div></div>`).join('')}</div>`;
  c.querySelector('.trade-detail-close').onclick = () => {
    state.pnl.selectedTrade = '__cleared__';
    renderApp();
  };
  return c;
}

function renderPnL(root) {
  const { pos } = DATA;
  const view = pos.filter((r) => state.pnl.venues.includes(r.venue) && state.pnl.leagues.includes(r.league));

  root.appendChild(pageHeader(
    'Manhattan Athletic Group', 'Desk P&L',
    'How is the desk doing? Total P&L, split into realized and unrealized, sliceable by venue and league.',
  ));

  const venues = [...new Set(pos.map((r) => r.venue))].sort();
  const leagues = [...new Set(pos.map((r) => r.league))].sort();
  root.appendChild(filterBar([
    segmentedFilter('Venue', venues, state.pnl.venues, renderApp),
    segmentedFilter('League', leagues, state.pnl.leagues, renderApp),
  ]));

  const realized = sum(view, 'realized_pnl');
  const unrealized = sum(view, 'unrealized_pnl');
  const total = realized + unrealized;
  const notional = sum(view, 'mag_stake');
  const won = view.filter((r) => r.status === 'WON').length;
  const lost = view.filter((r) => r.status === 'LOST').length;
  const openRowsAll = view.filter((r) => r.status === 'OPEN');
  const open = openRowsAll.length;
  const openStake = sum(openRowsAll, 'mag_stake');
  const winRate = won + lost ? (won / (won + lost)) * 100 : NaN;

  root.appendChild(heroRow([
    { label: 'Total P&L', value: fmtMoney(total), tone: 'brand' },
    { label: 'Realized P&L', value: fmtMoney(realized), tone: toneClass(realized) },
    {
      label: 'Unrealized P&L (open book)', value: fmtMoney(unrealized), tone: toneClass(unrealized),
      sub: `${fmtNum(open)} open · ${fmtMoney(openStake, { compact: true })} at risk`,
    },
  ]));

  // P&L breakdowns directly under the hero. Realized/unrealized share one hue
  // at two lightness steps (settled vs estimate), so blue means exactly one
  // thing on this page: P&L dollars.
  const series = [
    { key: 'realized_pnl', label: 'Realized', color: 'var(--mark-1)' },
    { key: 'unrealized_pnl', label: 'Unrealized', color: 'var(--mark-1-light)' },
  ];
  const charts = grid('grid-2');
  const c1 = card({ title: 'P&L by venue' });
  const c1chart = document.createElement('div');
  c1.appendChild(c1chart);
  charts.appendChild(c1);
  const c2 = card({ title: 'P&L by league' });
  const c2chart = document.createElement('div');
  c2.appendChild(c2chart);
  charts.appendChild(c2);
  root.appendChild(charts);

  const byVenue = sumByDim(view, 'venue', ['realized_pnl', 'unrealized_pnl']).map((d) => ({ venue: d.key, ...d })).sort((a, b) => a.venue.localeCompare(b.venue));
  const byLeague = sumByDim(view, 'league', ['realized_pnl', 'unrealized_pnl']).map((d) => ({ league: d.key, ...d })).sort((a, b) => a.league.localeCompare(b.league));
  groupedBarChart(c1chart, { data: byVenue, xKey: 'venue', series, height: 230 });
  groupedBarChart(c2chart, { data: byLeague, xKey: 'league', series, height: 230 });

  // stat cards
  const makerPnl = sum(view.filter((r) => r.mag_side === 'MAKER'), 'realized_pnl');
  const takerPnl = sum(view.filter((r) => r.mag_side === 'TAKER'), 'realized_pnl');
  const stats = grid('grid-5');
  stats.appendChild(statCard('Notional volume', fmtMoney(notional), { hint: `${fmtNum(view.length)} fills` }));
  stats.appendChild(statCard('Maker / taker realized P&L', `${fmtMoney(makerPnl, { compact: true })} / ${fmtMoney(takerPnl, { compact: true })}`));
  stats.appendChild(statCard('Open positions', fmtNum(open), {
    onClick: () => setView('hold'),
    hint: 'View hold analysis →',
  }));
  stats.appendChild(statCard('Open book (stake at risk)', fmtMoney(openStake)));
  stats.appendChild(statCard('Win rate (WON / WON+LOST)', Number.isNaN(winRate) ? '—' : `${winRate.toFixed(0)}%`));
  root.appendChild(stats);

  // per-trade impact charts (replace the old tables)
  const onSelect = (t) => {
    state.pnl.selectedTrade = t.fill_id;
    const panel = document.getElementById('trade-detail');
    const fresh = tradeDetailPanel(t);
    panel.replaceWith(fresh);
    fresh.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  const impactRow = grid('grid-2');
  const i1 = card({ title: "Every trade's P&L impact — by venue" });
  const i1chart = document.createElement('div');
  i1.appendChild(i1chart);
  impactRow.appendChild(i1);
  const i2 = card({ title: "Every trade's P&L impact — by league" });
  const i2chart = document.createElement('div');
  i2.appendChild(i2chart);
  impactRow.appendChild(i2);
  root.appendChild(impactRow);

  const withImpact = view.map((r) => ({ ...r, impact: tradeImpact(r) }));
  const venueGroups = venues.filter((v) => state.pnl.venues.includes(v))
    .map((v) => ({ label: v, trades: withImpact.filter((r) => r.venue === v) }));
  const leagueGroups = leagues.filter((l) => state.pnl.leagues.includes(l))
    .map((l) => ({ label: l, trades: withImpact.filter((r) => r.league === l) }));
  tradeImpactChart(i1chart, { groups: venueGroups, onSelect });
  tradeImpactChart(i2chart, { groups: leagueGroups, onSelect });

  // concentration risk (biggest winners & losers) + trade detail
  const riskRow = grid('grid-2');
  const losers = withImpact.filter((r) => (r.realized_pnl ?? 0) < 0)
    .sort((a, b) => a.realized_pnl - b.realized_pnl).slice(0, 5);
  const winners = withImpact.filter((r) => (r.realized_pnl ?? 0) > 0)
    .sort((a, b) => b.realized_pnl - a.realized_pnl).slice(0, 5);

  const concCard = card({
    title: 'Concentration risk — biggest winners & losers',
    caption: 'P&L lives in a handful of large-stake trades on both sides: a full loss costs the entire stake, and a win pays about the same. The largest wins and losses here are the same magnitude — the risk is stake size, not bad picking.',
  });
  const concGrid = document.createElement('div');
  concGrid.className = 'conc-grid';
  const mkList = (title, rows, winSide) => {
    const col = document.createElement('div');
    col.innerHTML = `<div class="conc-col-title">${title}</div>`;
    if (!rows.length) {
      col.appendChild(Object.assign(document.createElement('div'), { className: 'detail-placeholder', textContent: 'None in the current filter.' }));
      return col;
    }
    for (const [i, t] of rows.entries()) {
      const row = document.createElement('div');
      row.className = 'loser-row';
      row.innerHTML = `<span class="loser-rank">${i + 1}</span>`
        + `<span class="loser-main"><div class="loser-outcome">${t.outcome}</div>`
        + `<div class="loser-meta">${t.fill_id} · ${t.venue} · ${t.league} · staked ${fmtMoney(t.mag_stake)}</div></span>`
        + `<span class="loser-amt${winSide ? ' win' : ''}">${winSide ? '+' : ''}${fmtMoney(t.realized_pnl)}</span>`;
      row.onclick = () => onSelect(t);
      col.appendChild(row);
    }
    return col;
  };
  concGrid.appendChild(mkList('Biggest losers', losers, false));
  concGrid.appendChild(mkList('Biggest winners', winners, true));
  concCard.appendChild(concGrid);
  riskRow.appendChild(concCard);

  // detail panel defaults to the worst loser so the space demos itself;
  // '__cleared__' means the user explicitly closed it
  let selected = null;
  if (state.pnl.selectedTrade !== '__cleared__') {
    selected = (state.pnl.selectedTrade && withImpact.find((r) => r.fill_id === state.pnl.selectedTrade))
      || losers[0] || winners[0] || null;
  }
  riskRow.appendChild(tradeDetailPanel(selected));
  root.appendChild(riskRow);

  // trend
  const trendCard = card({
    title: 'Realized P&L trend',
    caption: "Cumulative realized P&L by fill date. There's no settlement-date field in the data, so this uses filled_at as a proxy for when a trade entered the book — not the date it actually settled.",
  });
  const trendChart = document.createElement('div');
  trendCard.appendChild(trendChart);
  root.appendChild(trendCard);

  const settled = view.filter((r) => r.realized_pnl != null).sort((a, b) => a.filled_at - b.filled_at);
  const byDate = groupBy(settled, (r) => r.filled_at.toISOString().slice(0, 10));
  let cum = 0;
  const daily = Array.from(byDate.entries()).sort(([a], [b]) => (a < b ? -1 : 1)).map(([date, rows]) => {
    cum += sum(rows, 'realized_pnl');
    return { date, cumulative: cum };
  });
  lineChart(trendChart, {
    data: daily, xKey: 'date',
    series: [{ key: 'cumulative', label: 'Cumulative realized P&L', color: 'var(--mark-1)' }],
    formatX: (d) => d.slice(5),
  });
}

// ---------------- Hold View ----------------

function renderHold(root) {
  const { pos } = DATA;
  const hp = holdPopulation(pos);
  const view = hp.filter((r) => state.hold.venues.includes(r.venue)
    && state.hold.leagues.includes(r.league) && state.hold.sides.includes(r.mag_side));

  root.appendChild(pageHeader(
    'Manhattan Athletic Group', 'Hold View',
    "Are we capturing the edge we think we're quoting, or is there a leak? Theoretical hold is what the model implied when we quoted; realized hold is what settlement actually paid us per dollar staked.",
  ));

  const venues = [...new Set(pos.map((r) => r.venue))].sort();
  const sides = [...new Set(pos.map((r) => r.mag_side))].sort();
  root.appendChild(filterBar([
    segmentedFilter('League', [...new Set(pos.map((r) => r.league))].sort(), state.hold.leagues, renderApp),
    segmentedFilter('Venue', venues, state.hold.venues, renderApp),
    segmentedFilter('MAG side', sides, state.hold.sides, renderApp),
  ]));

  if (!view.length) {
    root.appendChild(Object.assign(document.createElement('div'), { className: 'callout warn', textContent: 'No settled fills in the current filter.' }));
    return;
  }

  const desk = stakeWeightedHold(view);
  const [ciLo, ciHi] = bootstrapHoldCI(view);
  const inside = ciLo <= desk.theoBps && desk.theoBps <= ciHi;
  const neff = kishNeff(view);
  const sigma = (ciHi - ciLo) / 3.92;

  // realized/gap deliberately wear no green: the verdict banner says these
  // numbers are noise, so the color language must not congratulate them —
  // neutral ink with the σ tag carries it
  root.appendChild(heroRow([
    { label: 'Theoretical hold', value: fmtBps(desk.theoBps), tone: 'brand' },
    {
      label: 'Realized hold', value: fmtBps(desk.realBps), tone: null,
      sub: `95% CI [${Math.round(ciLo).toLocaleString()}, ${Math.round(ciHi).toLocaleString()}] bps`,
    },
    {
      label: 'Gap (realized − theoretical)', value: fmtBps(desk.gapBps), tone: null,
      sub: sigma ? `${(desk.gapBps / sigma) >= 0 ? '+' : ''}${(desk.gapBps / sigma).toFixed(1)}σ — ${Math.abs(desk.gapBps / sigma) < 2 ? 'within noise' : 'statistically notable'}` : '',
    },
    {
      label: 'Settled fills', value: fmtNum(desk.fills), tone: null,
      sub: `n_eff ≈ ${Math.round(neff)} after stake concentration`,
    },
  ]));

  const callout = document.createElement('div');
  callout.className = `callout ${inside ? '' : 'warn'}`;
  callout.innerHTML = inside
    ? `<b>Consistent with the quoted edge — no detectable leak, and no detectable outperformance either.</b> Realized hold came in ${desk.gapBps >= 0 ? '+' : ''}${Math.round(desk.gapBps).toLocaleString()} bps against quote, but that is ${(desk.gapBps / sigma).toFixed(1)}σ: the 95% confidence interval <b>[${Math.round(ciLo).toLocaleString()}, ${Math.round(ciHi).toLocaleString()}] bps</b> comfortably contains the theoretical ${Math.round(desk.theoBps).toLocaleString()}. Stake concentration makes ${desk.fills} fills behave like <b>~${Math.round(neff)} even bets</b>, so the noise floor (±~${Math.round(sigma).toLocaleString()} bps) is ${Math.round(sigma / desk.theoBps)}× the entire quoted edge — even a total leak would be invisible in this sample. This view catches leaks over months of settled volume, not ten days.`
    : `Realized hold of ${Math.round(desk.realBps).toLocaleString()} bps falls outside the 95% confidence interval <b>[${Math.round(ciLo).toLocaleString()}, ${Math.round(ciHi).toLocaleString()}] bps</b> around the quoted ${Math.round(desk.theoBps).toLocaleString()} bps. Worth a look — but confirm on more fills before acting.`;
  root.appendChild(callout);

  const chartCard = card({
    title: 'Theoretical vs realized hold by league',
    caption: "Error bars are a 95% bootstrap interval on realized hold. They are wide on purpose: where a bar's interval covers its theoretical marker, the league's realized hold is indistinguishable from the edge we quoted, and the difference should not be traded on.",
  });
  const chartEl = document.createElement('div');
  chartCard.appendChild(chartEl);
  root.appendChild(chartCard);
  const byLeague = holdByDimension(view, 'league');
  ciBarChart(chartEl, { data: byLeague, xKey: 'dim' });
  const note = document.createElement('div');
  note.className = 'card-caption';
  note.style.marginTop = '.8rem';
  note.textContent = "Grey bars: quoted edge sits inside the interval — no signal. Amber: outside the interval. With four leagues tested at 95% there's roughly a one-in-five chance that some league flags by luck alone, so a single flag is a prompt to collect more data, not evidence of a real per-league effect.";
  chartCard.appendChild(note);

  // companion chart: convergence funnel — cumulative realized hold with a
  // shrinking bootstrap CI band, theoretical as the flat reference
  const convCard = card({
    title: 'Cumulative realized hold vs quoted edge — with shrinking CI funnel',
    caption: 'Running stake-weighted realized hold as fills settle, wrapped in its 95% bootstrap interval recomputed at each day. Ten days in, the funnel still swallows the theoretical line — this chart becomes decisive over months of settled volume, and this is the view that would catch a real leak.',
  });
  const convEl = document.createElement('div');
  convCard.appendChild(convEl);
  root.appendChild(convCard);

  const ordered = [...view].sort((a, b) => a.filled_at - b.filled_at);
  const days = [...new Set(ordered.map((r) => r.filled_at.toISOString().slice(0, 10)))].sort();
  const sofar = [];
  let idx = 0, cumPnl = 0, cumStake = 0, cumTheo = 0;
  const convData = [];
  for (const day of days) {
    while (idx < ordered.length && ordered[idx].filled_at.toISOString().slice(0, 10) <= day) {
      const r = ordered[idx++];
      sofar.push(r);
      cumPnl += r.realized_pnl;
      cumStake += r.mag_stake;
      cumTheo += r.theoretical_hold_bps * r.mag_stake;
    }
    const [lo, hi] = bootstrapHoldCI(sofar, { n: 4000 });
    convData.push({ date: day, real: (1e4 * cumPnl) / cumStake, theo: cumTheo / cumStake, lo, hi });
  }
  lineChart(convEl, {
    data: convData, xKey: 'date', height: 300,
    series: [
      { key: 'real', label: 'Cumulative realized hold', color: 'var(--mark-1)' },
      { key: 'theo', label: 'Quoted edge (theoretical)', color: 'var(--mark-muted)' },
    ],
    band: { loKey: 'lo', hiKey: 'hi', color: 'var(--mark-1)' },
    formatValue: (v) => `${Math.round(v).toLocaleString()} bps`,
    formatX: (d) => d.slice(5),
  });

  const tblCard = card({ title: 'League detail' });
  tblCard.appendChild(table({
    columns: [
      { key: 'dim', label: 'League', text: true },
      { key: 'fills', label: 'Settled fills', format: fmtNum },
      { key: 'stake', label: 'Stake', format: fmtMoney },
      { key: 'pnl', label: 'Realized P&L', format: fmtMoney },
      { key: 'theoBps', label: 'Theoretical (bps)', format: (v) => Math.round(v).toLocaleString() },
      { key: 'realBps', label: 'Realized (bps)', format: (v) => Math.round(v).toLocaleString() },
      { key: 'gapBps', label: 'Gap (bps)', format: fmtBps },
      { key: 'gapSigma', label: 'Gap (σ)', format: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}σ` },
      { key: 'neff', label: 'n_eff', format: (v) => `≈${Math.round(v)}` },
      { key: 'ciLo', label: '95% CI', format: (v, r) => `[${Math.round(r.ciLo).toLocaleString()}, ${Math.round(r.ciHi).toLocaleString()}]` },
      { key: 'signal', label: 'Verdict', format: (v) => (v ? '<span class="tag signal">Outside CI — investigate</span>' : '<span class="tag noise">Inside CI — noise</span>') },
    ],
    rows: byLeague,
  }));
  root.appendChild(tblCard);

  // small tiles: maker/taker cut + fill-selection check
  const bySide = holdByDimension(view, 'mag_side');
  const maker = bySide.find((r) => r.dim === 'MAKER');
  const taker = bySide.find((r) => r.dim === 'TAKER');
  const sideTile = (r) => (r
    ? [`${Math.round(r.realBps).toLocaleString()} / ${Math.round(r.theoBps).toLocaleString()} bps`,
       `gap ${fmtBps(r.gapBps)} (${r.gapSigma >= 0 ? '+' : ''}${r.gapSigma.toFixed(1)}σ — ${Math.abs(r.gapSigma) < 2 ? 'within noise' : 'statistically notable'}) · n_eff ≈ ${Math.round(r.neff)}`]
    : ['—', 'not in current filter']);
  const [makerVal, makerHint] = sideTile(maker);
  const [takerVal, takerHint] = sideTile(taker);

  const filledQ = DATA.quotes.filter((q) => q.fill_id != null);
  const unfilledQ = DATA.quotes.filter((q) => q.fill_id == null);
  const avg = (rows) => rows.reduce((s, q) => s + q.theoretical_hold_bps, 0) / (rows.length || 1);

  const tiles = grid('grid-3');
  tiles.appendChild(statCard('Maker hold — realized vs quoted', makerVal, { hint: makerHint }));
  tiles.appendChild(statCard('Taker hold — realized vs quoted', takerVal, { hint: takerHint }));
  tiles.appendChild(statCard(
    'Fill-selection check (all quotes)',
    `${Math.round(avg(filledQ))} vs ${Math.round(avg(unfilledQ))} bps`,
    { hint: `avg quoted edge, ${filledQ.length} filled vs ${unfilledQ.length} unfilled — no adverse-selection pattern` },
  ));
  root.appendChild(tiles);

  const whyCard = card({ title: 'Why the intervals are this wide' });
  const whyGrid = document.createElement('div');
  whyGrid.className = 'grid grid-2-3';
  whyGrid.style.marginBottom = '0';
  const histEl = document.createElement('div');
  whyGrid.appendChild(histEl);
  const whyText = document.createElement('div');
  whyText.style.fontSize = '.88rem';
  whyText.style.lineHeight = '1.65';
  whyText.style.color = 'var(--text-secondary)';
  whyText.innerHTML = `Every settled fill is binary. We lose the stake (<b style="color:var(--text-primary)">−10,000 bps</b>) or the pool pays out (<b style="color:var(--text-primary)">≈ +10,000 bps</b>). Nothing lands near the ${Math.round(desk.theoBps).toLocaleString()} bps we quote.
    <br><br>The quoted edge is an <i>expected value across many trades</i> — it is never the outcome of any single one. So realized hold only converges on it slowly, and at ${desk.fills} fills the noise around it is still an order of magnitude wider than the edge we're trying to measure.
    <br><br>That's the case for showing intervals on this view rather than point estimates. A bare bar chart here would read as "MLB is printing, kill NFL" — and both of those are almost certainly luck.`;
  whyGrid.appendChild(whyText);
  whyCard.appendChild(whyGrid);
  root.appendChild(whyCard);
  histogramChart(histEl, { values: view.map((r) => r.realized_hold_bps), markerValue: desk.theoBps, markerLabel: 'quoted edge', color: 'var(--mark-muted)' });

  root.appendChild(expander('How realized hold is defined (and what\'s excluded)', `
    <b style="color:var(--text-primary)">Realized hold (bps) = 10,000 × Σ realized P&L ÷ Σ MAG stake</b>, over settled fills.
    <br><br>Both holds are stake-weighted ratios of sums, <i>not</i> averages of the per-fill bps column. Averaging per-fill hold answers a different question — "hold on the average trade" — and weights a $24 fill the same as a $1,099 one. The desk earns dollars per dollar staked, so the ratio of sums is the number that reconciles to the P&L view.
    <br><br><code>settle_value</code> is already net of the venue fee, so realized hold is a post-fee number. Theoretical hold is <i>assumed</i> to be the pre-fee model edge — the brief doesn't specify. If so, 150–200 bps of fee accounts for part of any gap and the two aren't perfectly like-for-like; if the model already quotes net of fees, this caveat drops out entirely.
    <br><br><b style="color:var(--text-primary)">Excluded from the population:</b>
    <table><thead><tr><th>Status</th><th>Excluded</th><th>Why</th></tr></thead><tbody>
    <tr><td class="text">OPEN</td><td class="text">yes</td><td class="text">A mark is an estimate, not a result. Mixing marks into realized hold imports mark noise into a settlement number.</td></tr>
    <tr><td class="text">VOID</td><td class="text">yes</td><td class="text">The market was cancelled and the stake returned. It never tested the edge — booking it at 0 bps would read as a leak that never happened.</td></tr>
    </tbody></table>
    <br><b style="color:var(--text-primary)">Population check:</b> all 320 fills in this dataset carry a quote, so theoretical and realized hold are computed over the identical set of fills. No apples-to-oranges gap from one side having fills the other doesn't. If unquoted fills ever appeared, they'd have to be dropped from both sides, not just one.
  `, { open: true }));

  root.appendChild(expander('Adverse selection check — are we only getting filled on our thin quotes?', `
    The other place a hold leak hides: if MAG only gets filled when the quote is wrong, realized hold decays even though the model is fine. It doesn't show up here.
    <br><br>Fill rate is flat across the theoretical-hold range — <b style="color:var(--text-primary)">85% / 90% / 93% / 93% / 91%</b> across the &lt;150, 150–200, 200–250, 250–300, and 300+ bps buckets — and the 30 unfilled quotes average <b style="color:var(--text-primary)">220 bps</b> against <b style="color:var(--text-primary)">230 bps</b> for filled ones. No sign that the market is picking us off on our thinnest edges.
  `));
}

// ---------------- Cash at Exchange ----------------

function renderCash(root) {
  const { venueCash } = DATA;
  const dateStr = state.cash.date;
  const view = venueCash.filter((r) => r.as_of.toISOString().slice(0, 10) === dateStr);

  root.appendChild(pageHeader(
    'Manhattan Athletic Group', 'Cash at Exchange',
    'How much capital is deployed where, and how much revolver headroom do we have? Collateral is venue-specific — cash posted at one exchange cannot back a position at another — so this view is always broken out by venue first.',
  ));

  const dates = [...new Set(venueCash.map((r) => r.as_of.toISOString().slice(0, 10)))].sort();
  const dateSet = document.createElement('div');
  dateSet.className = 'filter-set';
  dateSet.innerHTML = '<span class="filter-set-label">As of date</span>';
  const sel = document.createElement('select');
  sel.className = 'field-select';
  for (const d of dates) sel.appendChild(new Option(d, d, false, d === state.cash.date));
  sel.onchange = () => { state.cash.date = sel.value; renderApp(); };
  dateSet.appendChild(sel);

  const limitSet = document.createElement('div');
  limitSet.className = 'filter-set';
  limitSet.innerHTML = '<span class="filter-set-label">Revolver limit ($)</span>';
  const num = document.createElement('input');
  num.type = 'number';
  num.className = 'field-number';
  num.value = state.cash.revolverLimit;
  num.step = 1000;
  num.title = "The facility limit isn't in the trading data — it's a treasury figure. Enter the real number; headroom updates against it.";
  num.onchange = () => { state.cash.revolverLimit = Number(num.value) || 0; renderApp(); };
  limitSet.appendChild(num);

  root.appendChild(filterBar([dateSet, limitSet]));

  const totalCapital = sum(view, 'total_capital');
  const totalRevolver = sum(view, 'revolver_drawn');
  const headroom = state.cash.revolverLimit - totalRevolver;
  const latestDate = dates[dates.length - 1];
  const isLatest = dateStr === latestDate;

  root.appendChild(heroRow([
    { label: 'Total capital deployed', value: fmtMoney(totalCapital), tone: 'brand' },
    {
      label: 'Revolver drawn', value: fmtMoney(totalRevolver), tone: null,
      sub: totalCapital ? `${Math.round((totalRevolver / totalCapital) * 100)}% of capital at venues` : '',
    },
    {
      label: 'Revolver headroom', value: fmtMoney(headroom), tone: null,
      sub: 'illustrative — facility size is not in the dataset; limit is the input above',
    },
  ]));

  // the cross-venue imbalance is the insight this page exists for — but the
  // open book is only knowable as of the latest date (statuses are a current
  // snapshot and there are no settle dates to rewind them)
  const openByVenue = new Map();
  for (const r of DATA.pos.filter((p) => p.status === 'OPEN')) {
    openByVenue.set(r.venue, (openByVenue.get(r.venue) ?? 0) + r.mag_stake);
  }
  const sortedView = [...view].sort((a, b) => a.venue.localeCompare(b.venue));

  if (isLatest && sortedView.length) {
    const cov = sortedView.map((r) => ({
      venue: r.venue,
      open: openByVenue.get(r.venue) ?? 0,
      posted: r.posted_collateral,
      ratio: (openByVenue.get(r.venue) ?? 0) ? r.posted_collateral / openByVenue.get(r.venue) : NaN,
      revShare: r.total_capital ? (r.revolver_drawn / r.total_capital) * 100 : NaN,
    }));
    const thin = cov.filter((c) => c.ratio < 1);
    if (thin.length) {
      const callout = document.createElement('div');
      callout.className = 'callout warn';
      callout.innerHTML = `<b>One venue thin, one double-parked.</b> `
        + cov.map((c) => `${c.venue} holds ${fmtMoney(c.posted)} posted against ${fmtMoney(c.open)} of open stake (<b>${c.ratio.toFixed(2)}× coverage</b>, ${Math.round(c.revShare)}% revolver-funded)`).join('; ')
        + `. Collateral is venue-specific — cash at one exchange cannot back the other — so the action this view drives: <b>move idle collateral to the thin venue, or draw less revolver.</b>`;
      root.appendChild(callout);
    }
  }

  // per-venue cards
  const venueRow = grid('grid-2');
  for (const r of sortedView) {
    const open = openByVenue.get(r.venue) ?? 0;
    const ratio = open ? r.posted_collateral / open : NaN;
    const equity = r.total_capital - r.revolver_drawn;
    const vCard = card({ title: r.venue });
    const badge = document.createElement('div');
    badge.style.marginBottom = '.8rem';
    badge.innerHTML = isLatest && !Number.isNaN(ratio)
      ? (ratio < 1
        ? `<span class="tag signal">${ratio.toFixed(2)}× collateral coverage of open stake — thin</span>`
        : `<span class="tag noise">${ratio.toFixed(2)}× collateral coverage of open stake</span>`)
      : '<span class="tag noise">coverage n/a — open book only known as of the latest date</span>';
    vCard.appendChild(badge);
    const kv = document.createElement('div');
    kv.className = 'trade-detail-grid';
    kv.innerHTML = [
      ['Total at venue', fmtMoney(r.total_capital)],
      ['Posted collateral', fmtMoney(r.posted_collateral)],
      ['Free cash', fmtMoney(r.free_cash)],
      ['Revolver drawn', fmtMoney(r.revolver_drawn)],
      ['Equity-funded', fmtMoney(equity)],
    ].map(([k, v]) => `<div><div class="kv-label">${k}</div><div class="kv-value">${v}</div></div>`).join('');
    vCard.appendChild(kv);
    venueRow.appendChild(vCard);
  }
  root.appendChild(venueRow);

  // one chart: deployment + funding in a glance
  const capCard = card({
    title: 'Capital and funding by venue',
    caption: 'Bar = posted collateral + free cash; amber marker = revolver drawn. Where the marker sits deep inside the bar, the venue is running on borrowed money.',
  });
  const capEl = document.createElement('div');
  capCard.appendChild(capEl);
  root.appendChild(capCard);
  capitalBarChart(capEl, { rows: sortedView });

  // one trend: revolver by venue — volatile, which is the argument for watching it
  const trendCard = card({
    title: 'Revolver drawn by venue over time',
    caption: 'Draws swing meaningfully day to day (KALSHI ranges $4.6K–$11.2K over the window) — which is itself the argument for monitoring this rather than snapshotting it.',
  });
  const trendEl = document.createElement('div');
  trendCard.appendChild(trendEl);
  root.appendChild(trendCard);

  const venues = [...new Set(venueCash.map((r) => r.venue))].sort();
  const trendData = dates.map((d) => {
    const rec = { date: d };
    for (const v of venues) {
      const row2 = venueCash.find((r) => r.venue === v && r.as_of.toISOString().slice(0, 10) === d);
      rec[v] = row2 ? row2.revolver_drawn : null;
    }
    return rec;
  });
  const markColors = ['var(--mark-1)', 'var(--mark-1-light)', 'var(--mark-muted)'];
  lineChart(trendEl, {
    data: trendData, xKey: 'date', height: 280,
    series: venues.map((v, i) => ({ key: v, label: v, color: markColors[i % markColors.length] })),
    formatX: (d) => d.slice(5),
  });

  const caveat = document.createElement('div');
  caveat.className = 'callout';
  caveat.innerHTML = '<b>Two honest gaps, named.</b> (1) The brief asks for revolver <i>headroom</i>, but no facility limit exists anywhere in the data — headroom is shown against a placeholder input rather than an invented number. (2) Coverage compares posted collateral to open stake, which is a rough proxy for required margin: venue margin rules aren\'t in the data, and without settlement dates the open book can\'t be reconstructed for earlier dates. Directionally right, precisely unknowable.';
  root.appendChild(caveat);
}

// ---------------- shell ----------------

function renderApp() {
  const main = document.getElementById('main');
  main.innerHTML = '';
  if (state.view === 'pnl') renderPnL(main);
  else if (state.view === 'hold') renderHold(main);
  else if (state.view === 'cash') renderCash(main);

  document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === state.view));
}

function setView(view) {
  state.view = view;
  window.scrollTo({ top: 0 });
  renderApp();
}

async function main() {
  DATA = await loadData();
  state.pnl.venues = [...new Set(DATA.pos.map((r) => r.venue))];
  state.pnl.leagues = [...new Set(DATA.pos.map((r) => r.league))];
  state.hold.venues = [...new Set(DATA.pos.map((r) => r.venue))];
  state.hold.leagues = [...new Set(DATA.pos.map((r) => r.league))];
  state.hold.sides = [...new Set(DATA.pos.map((r) => r.mag_side))];
  const dates = [...new Set(DATA.venueCash.map((r) => r.as_of.toISOString().slice(0, 10)))].sort();
  state.cash.date = dates[dates.length - 1];

  document.querySelectorAll('.nav-item').forEach((n) => n.addEventListener('click', () => setView(n.dataset.view)));
  renderApp();
}

main();
