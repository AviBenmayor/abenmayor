"""Export webmap/hexes.geojson + webmap/meta.json for the MapLibre app (Railway)."""
import json, pathlib, h3
from loci import db
from loci.categories import CATEGORIES

ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB = ROOT / "webmap"
COLORS = {"hardware":"#b5541f","convenience":"#2f7d5c","clinic":"#3d6fb4","fitness":"#c69a1e",
  "childcare":"#9350a6","laundry":"#1f9aa1","pharmacy":"#cc4b63","hair_barber":"#6d8b3a",
  "cafe_bakery":"#8a6d4b","grocery":"#417a2f","nails_beauty":"#b3689a","bar":"#7a5cc0",
  "bank":"#4a7a8c","tailor_repair":"#996a3a"}


def main():
    con = db.connect(read_only=True)
    names = json.loads((ROOT / "data/interim/nta_names.json").read_text())
    gapmap = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT h3_index, lead_missing, missing_expected FROM analysis.hex_gaps WHERE threshold_min=10").fetchall()}
    rows = con.execute("""SELECT h.h3_index,h.borough,h.nta_code,dm.population
        FROM analysis.hex h JOIN analysis.hex_demographics dm ON dm.h3_index=h.h3_index AND dm.acs_year=2023
        WHERE dm.population>800""").fetchall()
    feats = []
    for h, boro, nta, pop in rows:
        ring = [[round(lng, 5), round(lat, 5)] for lat, lng in h3.cell_to_boundary(h)]
        ring.append(ring[0])
        missing = gapmap[h][1].split(",") if h in gapmap else []
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"nta": names.get(nta, nta) or "—", "boro": boro or "—",
                           "pop": int(pop), "lead": gapmap[h][0] if h in gapmap else None,
                           "missing": missing, "gap": 1 if missing else 0}})
    WEB.mkdir(exist_ok=True)
    (WEB / "hexes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    counts = {}
    for _, (_, miss) in gapmap.items():
        for c in miss.split(","): counts[c] = counts.get(c, 0) + 1
    meta = {"cats": list(CATEGORIES), "catLabels": [CATEGORIES[c].label for c in CATEGORIES],
            "boros": ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"],
            "ntas": sorted({(names.get(n, n) or "—") for _, _, n, _ in rows}),
            "colors": COLORS, "gapCounts": {k: v for k, v in counts.items() if v}, "nGap": len(gapmap)}
    (WEB / "meta.json").write_text(json.dumps(meta))
    print(f"wrote {len(feats)} features, {len(gapmap)} gaps")


if __name__ == "__main__":
    main()
