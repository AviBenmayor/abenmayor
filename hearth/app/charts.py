"""Inline SVG. No chart library and no CDN -- one less thing to fail in front of a room
on someone else's wifi, and the container stays small. Colours come from CSS variables
so the charts follow the page theme."""
from html import escape


def hbar(rows, value_key="v", label_key="k", note_key=None, band_key=None,
         suffix="%", width=560, row_h=30, vmax=None, accent="var(--accent)"):
    """rows: [{k, v, note?, band?(lo,hi), cls?}] -- one horizontal bar each."""
    rows = list(rows)
    if not rows:
        return "<p class='muted'>no data</p>"
    vmax = vmax or max(1e-9, max(r[value_key] or 0 for r in rows)) * 1.18
    lab_w, pad = 92, 8
    h = len(rows) * row_h + 10
    bar_w = width - lab_w - 70
    out = [f"<svg class='chart' viewBox='0 0 {width} {h}' role='img'>"]
    for i, r in enumerate(rows):
        y = i * row_h + 6
        v = r[value_key] or 0
        w = max(1.0, v / vmax * bar_w)
        fill = r.get("cls_color") or accent
        out.append(f"<text x='0' y='{y + 14}' class='cl'>{escape(str(r[label_key]))}</text>")
        out.append(f"<rect x='{lab_w}' y='{y + 3}' width='{w:.1f}' height='{row_h - 12}' "
                   f"rx='2' fill='{fill}'/>")
        if band_key and r.get(band_key):
            lo, hi = r[band_key]
            x1 = lab_w + lo / vmax * bar_w
            x2 = lab_w + hi / vmax * bar_w
            cy = y + 3 + (row_h - 12) / 2
            out.append(f"<line x1='{x1:.1f}' x2='{x2:.1f}' y1='{cy}' y2='{cy}' "
                       f"class='ci'/><line x1='{x1:.1f}' x2='{x1:.1f}' y1='{cy-4}' y2='{cy+4}' class='ci'/>"
                       f"<line x1='{x2:.1f}' x2='{x2:.1f}' y1='{cy-4}' y2='{cy+4}' class='ci'/>")
        out.append(f"<text x='{lab_w + w + pad:.1f}' y='{y + 14}' class='cv'>{v:.1f}{suffix}"
                   + (f"<tspan class='cn'>  {escape(str(r[note_key]))}</tspan>" if note_key and r.get(note_key) else "")
                   + "</text>")
    out.append("</svg>")
    return "".join(out)


def funnel(stages, width=560):
    """stages: [(label, n)] -- descending."""
    top = stages[0][1]
    h = len(stages) * 46 + 8
    out = [f"<svg class='chart' viewBox='0 0 {width} {h}' role='img'>"]
    for i, (label, n) in enumerate(stages):
        y = i * 46 + 4
        w = max(2, n / top * (width - 4))
        pct = n / top * 100
        out.append(f"<rect x='0' y='{y}' width='{w:.1f}' height='30' rx='3' class='fn'/>")
        out.append(f"<text x='10' y='{y + 20}' class='fl'>{escape(label)}</text>")
        out.append(f"<text x='{min(w + 10, width - 150):.1f}' y='{y + 20}' class='cv'>"
                   f"{n:,} <tspan class='cn'>{pct:.1f}% of leads</tspan></text>")
    out.append("</svg>")
    return "".join(out)
