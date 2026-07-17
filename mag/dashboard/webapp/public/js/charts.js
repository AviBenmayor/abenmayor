// Hand-built SVG chart primitives (no charting library) so mark specs —
// rounded data-end bar caps square at the baseline, 2px surface gaps, thin
// recessive gridlines, hover tooltips — are exact rather than fought out of
// a library's defaults.

const NS = 'http://www.w3.org/2000/svg';
const MAX_BAR = 24;
const CAP_R = 4;

function el(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

export function fmtMoney(v, { compact = false } = {}) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v < 0 ? '-' : '';
  const abs = Math.abs(v);
  if (compact && abs >= 1000) {
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
    return `${sign}$${(abs / 1000).toFixed(1)}K`;
  }
  return `${sign}$${abs.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export function fmtNum(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

export function fmtBps(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${Math.round(v).toLocaleString('en-US')} bps`;
}

function niceStep(rough) {
  const mag = 10 ** Math.floor(Math.log10(Math.abs(rough) || 1));
  const norm = Math.abs(rough) / mag;
  let step;
  if (norm <= 1) step = 1;
  else if (norm <= 2) step = 2;
  else if (norm <= 5) step = 5;
  else step = 10;
  return step * mag;
}

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const step = niceStep((max - min) / count);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

function roundedBarPath(x, w, yTop, yBottom, roundTop) {
  const h = yBottom - yTop;
  const r = Math.min(CAP_R, w / 2, Math.max(h, 0) / 2);
  if (h <= 0.5) return `M${x},${yBottom} L${x + w},${yBottom}`;
  if (roundTop) {
    return [
      `M${x},${yBottom}`,
      `L${x},${yTop + r}`,
      `Q${x},${yTop} ${x + r},${yTop}`,
      `L${x + w - r},${yTop}`,
      `Q${x + w},${yTop} ${x + w},${yTop + r}`,
      `L${x + w},${yBottom}`,
      'Z',
    ].join(' ');
  }
  return [
    `M${x},${yTop}`,
    `L${x + w},${yTop}`,
    `L${x + w},${yBottom - r}`,
    `Q${x + w},${yBottom} ${x + w - r},${yBottom}`,
    `L${x + r},${yBottom}`,
    `Q${x},${yBottom} ${x},${yBottom - r}`,
    `L${x},${yTop}`,
    'Z',
  ].join(' ');
}

let tooltipEl = null;
function tooltip() {
  if (!tooltipEl) {
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'chart-tooltip';
    document.body.appendChild(tooltipEl);
  }
  return tooltipEl;
}

function showTooltip(evt, html) {
  const tt = tooltip();
  tt.innerHTML = html;
  tt.classList.add('visible');
  const pad = 14;
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  const rect = tt.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
  tt.style.left = `${x + window.scrollX}px`;
  tt.style.top = `${y + window.scrollY}px`;
}
function hideTooltip() {
  if (tooltipEl) tooltipEl.classList.remove('visible');
}

function legend(container, items) {
  if (items.length < 2) return;
  const bar = document.createElement('div');
  bar.className = 'chart-legend';
  for (const it of items) {
    const item = document.createElement('span');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-swatch" style="background:${it.color}"></span>${it.label}`;
    bar.appendChild(item);
  }
  container.insertBefore(bar, container.firstChild);
}

const MARGIN = { top: 10, right: 16, bottom: 28, left: 56 };

function frame(container, height) {
  container.innerHTML = '';
  const width = container.clientWidth || 600;
  const svg = el('svg', {
    class: 'chart-svg',
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: 'none',
  });
  container.appendChild(svg);
  return { svg, width, height, iw: width - MARGIN.left - MARGIN.right, ih: height - MARGIN.top - MARGIN.bottom };
}

/** Grouped or stacked bar chart, 1-2 series, categorical x-axis. Bars can
 * cross a zero baseline (grouped mode only). */
export function groupedBarChart(container, { data, xKey, series, height = 320, mode = 'grouped', formatValue = fmtMoney }) {
  if (!data.length) { container.innerHTML = '<div class="empty-state">No data in the current filter.</div>'; return; }
  const { svg, ih, iw } = frame(container, height);
  legend(container, series);
  const g = el('g', { transform: `translate(${MARGIN.left},${MARGIN.top})` });
  svg.appendChild(g);

  let yMin = 0, yMax = 0;
  if (mode === 'stacked') {
    for (const d of data) {
      const total = series.reduce((s, ser) => s + (d[ser.key] || 0), 0);
      yMax = Math.max(yMax, total);
    }
  } else {
    for (const d of data) for (const ser of series) {
      yMin = Math.min(yMin, d[ser.key] || 0);
      yMax = Math.max(yMax, d[ser.key] || 0);
    }
  }
  const ticks = niceTicks(yMin, yMax, 5);
  yMin = Math.min(yMin, ticks[0]);
  yMax = Math.max(yMax, ticks[ticks.length - 1]);
  const y = (v) => ih - ((v - yMin) / (yMax - yMin)) * ih;
  const yZero = y(0);

  for (const t of ticks) {
    g.appendChild(el('line', { class: 'gridline', x1: 0, x2: iw, y1: y(t), y2: y(t) }));
    const label = el('text', { class: 'axis', x: -10, y: y(t) + 4, 'text-anchor': 'end' });
    label.textContent = formatValue === fmtMoney ? fmtMoney(t, { compact: true }) : formatValue(t);
    label.setAttribute('fill', 'var(--text-muted)');
    label.setAttribute('font-size', '11');
    g.appendChild(label);
  }
  g.appendChild(el('line', { class: 'baseline', x1: 0, x2: iw, y1: yZero, y2: yZero }));

  const bandW = iw / data.length;
  const gap = 2;
  const barW = mode === 'stacked'
    ? Math.min(MAX_BAR, bandW * 0.55)
    : Math.min(MAX_BAR, (bandW * 0.7 - gap * (series.length - 1)) / series.length);

  data.forEach((d, i) => {
    const cx = bandW * i + bandW / 2;
    if (mode === 'stacked') {
      let acc = 0;
      const x = cx - barW / 2;
      series.forEach((ser, si) => {
        const v = d[ser.key] || 0;
        const yTop = y(acc + v);
        const yBottom = y(acc);
        const path = el('path', {
          class: 'mark-bar',
          d: roundedBarPath(x, barW, yTop, yBottom - (si < series.length - 1 ? gap : 0), si === series.length - 1),
          fill: ser.color,
        });
        g.appendChild(path);
        attachHover(path, d, [ser], svg, xKey, formatValue);
        acc += v;
      });
    } else {
      const totalW = barW * series.length + gap * (series.length - 1);
      let x = cx - totalW / 2;
      for (const ser of series) {
        const v = d[ser.key] || 0;
        const yTop = y(Math.max(v, 0));
        const yBottom = y(Math.min(v, 0));
        const path = el('path', {
          class: 'mark-bar',
          d: roundedBarPath(x, barW, yTop, yBottom, v >= 0),
          fill: ser.color,
        });
        g.appendChild(path);
        attachHover(path, d, [ser], svg, xKey, formatValue);
        x += barW + gap;
      }
    }
    const label = el('text', { class: 'axis', x: cx, y: ih + 20, 'text-anchor': 'middle' });
    label.textContent = d[xKey];
    label.setAttribute('fill', 'var(--text-secondary)');
    label.setAttribute('font-size', '11.5');
    label.setAttribute('font-weight', '500');
    g.appendChild(label);
  });
}

function attachHover(node, d, seriesSubset, svg, xKey, formatValue) {
  node.addEventListener('mousemove', (evt) => {
    node.classList.add('hover');
    const rows = seriesSubset.map((ser) => `<div class="tt-row"><span class="tt-dot" style="background:${ser.color}"></span>${ser.label}: <b style="margin-left:auto;padding-left:.6rem">${formatValue(d[ser.key] ?? 0)}</b></div>`).join('');
    showTooltip(evt, `<div class="tt-title">${d[xKey]}</div>${rows}`);
  });
  node.addEventListener('mouseleave', () => { node.classList.remove('hover'); hideTooltip(); });
}

/** Line chart, 1+ series over an ordinal/time x-axis. Optional `band`
 * ({loKey, hiKey, color, label}) draws a translucent area (e.g. a CI funnel)
 * behind the lines. */
export function lineChart(container, { data, xKey, series, band, height = 300, formatValue = fmtMoney, formatX = (v) => v }) {
  if (!data.length) { container.innerHTML = '<div class="empty-state">No data in the current filter.</div>'; return; }
  const { svg, ih, iw } = frame(container, height);
  legend(container, series);
  const g = el('g', { transform: `translate(${MARGIN.left},${MARGIN.top})` });
  svg.appendChild(g);

  let yMin = 0, yMax = 0;
  for (const d of data) for (const ser of series) {
    yMin = Math.min(yMin, d[ser.key] ?? 0);
    yMax = Math.max(yMax, d[ser.key] ?? 0);
  }
  if (band) for (const d of data) {
    if (d[band.loKey] != null) yMin = Math.min(yMin, d[band.loKey]);
    if (d[band.hiKey] != null) yMax = Math.max(yMax, d[band.hiKey]);
  }
  const ticks = niceTicks(yMin, yMax, 5);
  yMin = Math.min(yMin, ticks[0]);
  yMax = Math.max(yMax, ticks[ticks.length - 1]);
  const y = (v) => ih - ((v - yMin) / (yMax - yMin)) * ih;
  const x = (i) => (data.length === 1 ? iw / 2 : (i / (data.length - 1)) * iw);

  for (const t of ticks) {
    g.appendChild(el('line', { class: 'gridline', x1: 0, x2: iw, y1: y(t), y2: y(t) }));
    const label = el('text', { x: -10, y: y(t) + 4, 'text-anchor': 'end', fill: 'var(--text-muted)', 'font-size': 11 });
    label.textContent = formatValue === fmtMoney ? fmtMoney(t, { compact: true }) : formatValue(t);
    g.appendChild(label);
  }
  if (yMin < 0 && yMax > 0) g.appendChild(el('line', { class: 'baseline', x1: 0, x2: iw, y1: y(0), y2: y(0) }));

  const step = Math.max(1, Math.ceil(data.length / 8));
  data.forEach((d, i) => {
    if (i % step !== 0 && i !== data.length - 1) return;
    const label = el('text', { x: x(i), y: ih + 20, 'text-anchor': 'middle', fill: 'var(--text-secondary)', 'font-size': 11 });
    label.textContent = formatX(d[xKey]);
    g.appendChild(label);
  });

  if (band) {
    const fwd = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(d[band.hiKey])}`).join(' ');
    const back = [...data].reverse().map((d, i) => `L${x(data.length - 1 - i)},${y(d[band.loKey])}`).join(' ');
    g.appendChild(el('path', { d: `${fwd} ${back} Z`, fill: band.color, opacity: 0.12, stroke: 'none' }));
  }

  for (const ser of series) {
    const pts = data.map((d, i) => [x(i), y(d[ser.key] ?? 0)]);
    const path = el('path', {
      d: pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' '),
      fill: 'none', stroke: ser.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    });
    g.appendChild(path);
    pts.forEach((p, i) => {
      const dot = el('circle', { cx: p[0], cy: p[1], r: 4, fill: ser.color, stroke: 'var(--surface)', 'stroke-width': 2, class: 'mark-hitbox-dot' });
      dot.style.cursor = 'pointer';
      g.appendChild(dot);
      dot.addEventListener('mousemove', (evt) => {
        showTooltip(evt, `<div class="tt-title">${formatX(data[i][xKey])}</div><div class="tt-row"><span class="tt-dot" style="background:${ser.color}"></span>${ser.label}: <b style="margin-left:auto;padding-left:.6rem">${formatValue(data[i][ser.key])}</b></div>`);
      });
      dot.addEventListener('mouseleave', hideTooltip);
    });
  }
}

/** Bar + bootstrap CI whiskers + theoretical marker, for the hold view. */
export function ciBarChart(container, { data, xKey, height = 420, formatValue = fmtBps }) {
  if (!data.length) { container.innerHTML = '<div class="empty-state">No data in the current filter.</div>'; return; }
  const { svg, ih, iw } = frame(container, height);
  const g = el('g', { transform: `translate(${MARGIN.left},${MARGIN.top})` });
  svg.appendChild(g);

  let yMin = 0, yMax = 0;
  for (const d of data) {
    yMin = Math.min(yMin, d.realBps, d.ciLo, d.theoBps);
    yMax = Math.max(yMax, d.realBps, d.ciHi, d.theoBps);
  }
  const ticks = niceTicks(yMin, yMax, 6);
  yMin = Math.min(yMin, ticks[0]);
  yMax = Math.max(yMax, ticks[ticks.length - 1]);
  const y = (v) => ih - ((v - yMin) / (yMax - yMin)) * ih;
  const yZero = y(0);

  for (const t of ticks) {
    g.appendChild(el('line', { class: 'gridline', x1: 0, x2: iw, y1: y(t), y2: y(t) }));
    const label = el('text', { x: -10, y: y(t) + 4, 'text-anchor': 'end', fill: 'var(--text-muted)', 'font-size': 11 });
    label.textContent = fmtNum(t);
    g.appendChild(label);
  }
  g.appendChild(el('line', { class: 'baseline', x1: 0, x2: iw, y1: yZero, y2: yZero }));

  const bandW = iw / data.length;
  const barW = Math.min(MAX_BAR + 20, bandW * 0.5);

  data.forEach((d, i) => {
    const cx = bandW * i + bandW / 2;
    // "outside CI" is an alert state, not a win — amber, never green, and it
    // stays correct when a league someday flags negative
    const color = d.signal ? 'var(--status-warning)' : 'var(--mark-muted)';
    const yTop = y(Math.max(d.realBps, 0));
    const yBottom = y(Math.min(d.realBps, 0));
    const bar = el('path', { class: 'mark-bar', d: roundedBarPath(cx - barW / 2, barW, yTop, yBottom, d.realBps >= 0), fill: color });
    g.appendChild(bar);

    g.appendChild(el('line', { x1: cx, x2: cx, y1: y(d.ciLo), y2: y(d.ciHi), stroke: 'var(--text-muted)', 'stroke-width': 1.5 }));
    g.appendChild(el('line', { x1: cx - 5, x2: cx + 5, y1: y(d.ciLo), y2: y(d.ciLo), stroke: 'var(--text-muted)', 'stroke-width': 1.5 }));
    g.appendChild(el('line', { x1: cx - 5, x2: cx + 5, y1: y(d.ciHi), y2: y(d.ciHi), stroke: 'var(--text-muted)', 'stroke-width': 1.5 }));

    g.appendChild(el('line', {
      x1: cx - barW / 2 - 4, x2: cx + barW / 2 + 4, y1: y(d.theoBps), y2: y(d.theoBps),
      stroke: 'var(--mark-1)', 'stroke-width': 3, 'stroke-linecap': 'round',
    }));

    const hit = el('rect', { class: 'mark-hitbox', x: cx - bandW / 2, y: 0, width: bandW, height: ih });
    g.appendChild(hit);
    hit.addEventListener('mousemove', (evt) => {
      showTooltip(evt, `<div class="tt-title">${d.dim}</div>`
        + `<div class="tt-row"><span class="tt-dot" style="background:var(--mark-1)"></span>Theoretical: <b style="margin-left:auto;padding-left:.6rem">${fmtBps(d.theoBps)}</b></div>`
        + `<div class="tt-row"><span class="tt-dot" style="background:${color}"></span>Realized: <b style="margin-left:auto;padding-left:.6rem">${fmtBps(d.realBps)}</b></div>`
        + `<div class="tt-row">95% CI: <b style="margin-left:auto;padding-left:.6rem">[${fmtNum(d.ciLo)}, ${fmtNum(d.ciHi)}]</b></div>`
        + `<div class="tt-row">Settled fills: <b style="margin-left:auto;padding-left:.6rem">${d.fills}</b></div>`);
    });
    hit.addEventListener('mouseleave', hideTooltip);

    const label = el('text', { x: cx, y: ih + 20, 'text-anchor': 'middle', fill: 'var(--text-secondary)', 'font-size': 11.5, 'font-weight': 500 });
    label.textContent = d.dim;
    g.appendChild(label);
    if (d.neff != null) {
      const sub = el('text', { x: cx, y: ih + 34, 'text-anchor': 'middle', fill: 'var(--text-muted)', 'font-size': 10 });
      sub.textContent = `n ${d.fills} · n_eff ≈ ${Math.round(d.neff)}`;
      g.appendChild(sub);
    }
  });

  const legendBar = document.createElement('div');
  legendBar.className = 'chart-legend';
  legendBar.innerHTML = `
    <span class="legend-item"><span class="legend-swatch" style="background:var(--mark-1)"></span>Theoretical hold (quoted edge)</span>
    <span class="legend-item"><span class="legend-swatch" style="background:var(--status-warning)"></span>Realized hold (outside 95% CI — investigate)</span>
    <span class="legend-item"><span class="legend-swatch" style="background:var(--mark-muted)"></span>Realized hold (inside 95% CI — noise)</span>`;
  container.insertBefore(legendBar, container.firstChild);
}

/** Every trade as one thin bar (blue gain / red loss), grouped into lanes by a
 * dimension. Hover shows the trade; click selects it (onSelect callback). */
export function tradeImpactChart(container, { groups, height = 300, onSelect }) {
  const total = groups.reduce((s, g) => s + g.trades.length, 0);
  if (!total) { container.innerHTML = '<div class="empty-state">No trades in the current filter.</div>'; return; }
  const { svg, ih, iw } = frame(container, height);
  const g = el('g', { transform: `translate(${MARGIN.left},${MARGIN.top})` });
  svg.appendChild(g);

  let yMin = 0, yMax = 0;
  for (const grp of groups) for (const t of grp.trades) {
    yMin = Math.min(yMin, t.impact);
    yMax = Math.max(yMax, t.impact);
  }
  const ticks = niceTicks(yMin, yMax, 5);
  yMin = Math.min(yMin, ticks[0]);
  yMax = Math.max(yMax, ticks[ticks.length - 1]);
  const y = (v) => ih - ((v - yMin) / (yMax - yMin)) * ih;
  const yZero = y(0);

  for (const t of ticks) {
    g.appendChild(el('line', { class: 'gridline', x1: 0, x2: iw, y1: y(t), y2: y(t) }));
    const label = el('text', { x: -10, y: y(t) + 4, 'text-anchor': 'end', fill: 'var(--text-muted)', 'font-size': 11 });
    label.textContent = fmtMoney(t, { compact: true });
    g.appendChild(label);
  }
  g.appendChild(el('line', { class: 'baseline', x1: 0, x2: iw, y1: yZero, y2: yZero }));

  const laneGap = 18;
  const usable = iw - laneGap * (groups.length - 1);
  let laneX = 0;
  let selectedBar = null;

  for (const [gi, grp] of groups.entries()) {
    const laneW = (grp.trades.length / total) * usable;
    const sorted = [...grp.trades].sort((a, b) => b.impact - a.impact);
    const slot = laneW / sorted.length;
    const barW = Math.max(1, Math.min(8, slot - 1));

    sorted.forEach((t, i) => {
      const x = laneX + i * slot + (slot - barW) / 2;
      const yTop = y(Math.max(t.impact, 0));
      const yBottom = y(Math.min(t.impact, 0));
      const color = t.impact >= 0 ? 'var(--pnl-pos)' : 'var(--pnl-neg)';
      const bar = el('rect', {
        class: 'mark-bar', x, y: yTop, width: barW,
        height: Math.max(1, yBottom - yTop), fill: color,
      });
      g.appendChild(bar);
      // widened invisible hitbox so 1-2px bars are hoverable
      const hit = el('rect', { class: 'mark-hitbox', x: laneX + i * slot, y: 0, width: slot, height: ih });
      g.appendChild(hit);
      const show = (evt) => {
        showTooltip(evt, `<div class="tt-title">${t.fill_id} · ${t.outcome}</div>`
          + `<div class="tt-row">${t.venue} · ${t.league} · ${t.status}</div>`
          + `<div class="tt-row"><span class="tt-dot" style="background:${color}"></span>P&amp;L impact: <b style="margin-left:auto;padding-left:.6rem">${fmtMoney(t.impact)}</b></div>`
          + `<div class="tt-row">Stake: <b style="margin-left:auto;padding-left:.6rem">${fmtMoney(t.mag_stake)}</b></div>`);
      };
      hit.addEventListener('mousemove', show);
      hit.addEventListener('mouseleave', hideTooltip);
      if (onSelect) {
        hit.addEventListener('click', () => {
          if (selectedBar) selectedBar.removeAttribute('stroke');
          bar.setAttribute('stroke', 'var(--text-primary)');
          bar.setAttribute('stroke-width', '1');
          selectedBar = bar;
          onSelect(t);
        });
      }
    });

    const label = el('text', {
      x: laneX + laneW / 2, y: ih + 20, 'text-anchor': 'middle',
      fill: 'var(--text-secondary)', 'font-size': 11.5, 'font-weight': 500,
    });
    label.textContent = `${grp.label} (${grp.trades.length})`;
    g.appendChild(label);

    if (gi < groups.length - 1) {
      g.appendChild(el('line', {
        x1: laneX + laneW + laneGap / 2, x2: laneX + laneW + laneGap / 2,
        y1: 0, y2: ih, stroke: 'var(--grid)', 'stroke-width': 1,
      }));
    }
    laneX += laneW + laneGap;
  }

  const legendBar = document.createElement('div');
  legendBar.className = 'chart-legend';
  legendBar.innerHTML = `
    <span class="legend-item"><span class="legend-swatch" style="background:var(--pnl-pos)"></span>Gain</span>
    <span class="legend-item"><span class="legend-swatch" style="background:var(--pnl-neg)"></span>Loss</span>
    <span class="legend-item" style="color:var(--text-muted)">One bar per trade — click a bar for details</span>`;
  container.insertBefore(legendBar, container.firstChild);
}

/** Horizontal stacked capital bars per venue: posted collateral + free cash
 * segments with a revolver marker overlaid, so deployment and funding read in
 * one glance. */
export function capitalBarChart(container, { rows, height = 90 * 2 + 40 }) {
  if (!rows.length) { container.innerHTML = '<div class="empty-state">No data for this date.</div>'; return; }
  const { svg, iw } = frame(container, height);
  const LEFT = 70;
  const width = iw + MARGIN.left + MARGIN.right;
  const innerW = width - LEFT - 24;
  const g = el('g', { transform: `translate(${LEFT},${MARGIN.top})` });
  svg.appendChild(g);

  const maxTotal = Math.max(...rows.map((r) => r.posted_collateral + r.free_cash), ...rows.map((r) => r.revolver_drawn));
  const x = (v) => (v / maxTotal) * innerW;
  const laneH = 74;
  const barH = 22;

  rows.forEach((r, i) => {
    const yTop = i * laneH + 14;
    const yBar = yTop + 16;

    const vlabel = el('text', { x: -10, y: yBar + barH / 2 + 4, 'text-anchor': 'end', fill: 'var(--text-secondary)', 'font-size': 12, 'font-weight': 600 });
    vlabel.textContent = r.venue;
    g.appendChild(vlabel);

    const wPosted = x(r.posted_collateral);
    const wFree = x(r.free_cash);
    g.appendChild(el('rect', { x: 0, y: yBar, width: Math.max(wPosted - 1, 0), height: barH, rx: 4, fill: 'var(--mark-1)' }));
    g.appendChild(el('rect', { x: wPosted + 1, y: yBar, width: Math.max(wFree - 1, 0), height: barH, rx: 4, fill: 'var(--mark-1-light)' }));

    // revolver marker: how much of this deployment is borrowed
    const xr = x(r.revolver_drawn);
    g.appendChild(el('line', { x1: xr, x2: xr, y1: yBar - 7, y2: yBar + barH + 7, stroke: 'var(--status-warning)', 'stroke-width': 2.5, 'stroke-linecap': 'round' }));

    const totLabel = el('text', { x: wPosted + wFree + 8, y: yBar + barH / 2 + 4, fill: 'var(--text-primary)', 'font-size': 12, 'font-family': 'Source Code Pro, monospace', 'font-weight': 600 });
    totLabel.textContent = fmtMoney(r.posted_collateral + r.free_cash, { compact: true });
    g.appendChild(totLabel);

    const sub = el('text', { x: 0, y: yBar + barH + 18, fill: 'var(--text-muted)', 'font-size': 10.5 });
    sub.textContent = `posted ${fmtMoney(r.posted_collateral, { compact: true })} · free ${fmtMoney(r.free_cash, { compact: true })} · revolver ${fmtMoney(r.revolver_drawn, { compact: true })} (${Math.round((r.revolver_drawn / (r.posted_collateral + r.free_cash)) * 100)}% of capital)`;
    g.appendChild(sub);
  });

  const legendBar = document.createElement('div');
  legendBar.className = 'chart-legend';
  legendBar.innerHTML = `
    <span class="legend-item"><span class="legend-swatch" style="background:var(--mark-1)"></span>Posted collateral</span>
    <span class="legend-item"><span class="legend-swatch" style="background:var(--mark-1-light)"></span>Free cash</span>
    <span class="legend-item"><span class="legend-swatch" style="background:var(--status-warning);width:3px;border-radius:1px"></span>Revolver drawn</span>`;
  container.insertBefore(legendBar, container.firstChild);
}

/** Histogram of a single numeric series with an optional marker line. */
export function histogramChart(container, { values, bins = 40, markerValue, markerLabel, height = 300, color = 'var(--mark-2)' }) {
  if (!values.length) { container.innerHTML = '<div class="empty-state">No data.</div>'; return; }
  const { svg, ih, iw } = frame(container, height);
  const g = el('g', { transform: `translate(${MARGIN.left},${MARGIN.top})` });
  svg.appendChild(g);

  const xMin = Math.min(...values, markerValue ?? Infinity);
  const xMax = Math.max(...values, markerValue ?? -Infinity);
  const binW = (xMax - xMin) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    let idx = Math.floor((v - xMin) / binW);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    counts[idx]++;
  }
  const yticks = niceTicks(0, Math.max(...counts), 4);
  const yMax = Math.max(...counts, yticks[yticks.length - 1]);
  const x = (v) => ((v - xMin) / (xMax - xMin)) * iw;
  const y = (v) => ih - (v / yMax) * ih;
  for (const t of yticks) {
    if (t < 0) continue;
    g.appendChild(el('line', { class: 'gridline', x1: 0, x2: iw, y1: y(t), y2: y(t) }));
    const label = el('text', { x: -10, y: y(t) + 4, 'text-anchor': 'end', fill: 'var(--text-muted)', 'font-size': 11 });
    label.textContent = fmtNum(t);
    g.appendChild(label);
  }
  g.appendChild(el('line', { class: 'baseline', x1: 0, x2: iw, y1: ih, y2: ih }));

  counts.forEach((c, i) => {
    if (!c) return;
    const bx = x(xMin + i * binW);
    const bw = Math.max(1, x(xMin + (i + 1) * binW) - bx - 1);
    const bar = el('rect', { x: bx, y: y(c), width: bw, height: ih - y(c), fill: color, opacity: 0.85 });
    g.appendChild(bar);
  });

  if (markerValue != null) {
    const mx = x(markerValue);
    g.appendChild(el('line', { x1: mx, x2: mx, y1: 0, y2: ih, stroke: 'var(--mark-1)', 'stroke-width': 2, 'stroke-dasharray': '4,3' }));
    const label = el('text', { x: mx, y: -2, 'text-anchor': 'middle', fill: 'var(--mark-1)', 'font-size': 11, 'font-weight': 600 });
    label.textContent = markerLabel ?? '';
    g.appendChild(label);
  }

  const xticks = niceTicks(xMin, xMax, 5);
  for (const t of xticks) {
    const label = el('text', { x: x(t), y: ih + 20, 'text-anchor': 'middle', fill: 'var(--text-secondary)', 'font-size': 11 });
    label.textContent = fmtNum(t);
    g.appendChild(label);
  }
}
