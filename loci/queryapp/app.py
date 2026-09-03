"""Loci Query — a read-only, guarded query service over the Loci dataset.

Three ways in, all hitting the same read-only DuckDB:
  1. structured filters   (safe, no SQL)
  2. raw SQL              (SELECT-only, single statement, forced LIMIT)
  3. natural language     (LLM -> SQL, then run through the same SQL guard)

Guardrails, in layers: the DuckDB connection is opened read_only (writes are
impossible at the engine level), and every SQL string is validated to be a single
SELECT/WITH against the three whitelisted tables with a bounded LIMIT before it
runs. Optional shared password via LOCI_QUERY_PASSWORD.
"""
from __future__ import annotations

import os
import re
import threading

import duckdb
from flask import Flask, jsonify, request

DB = os.path.join(os.path.dirname(__file__), "loci_query.duckdb")
PASSWORD = os.environ.get("LOCI_QUERY_PASSWORD", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
TABLES = {"buildings", "neighborhoods", "pois"}
MAX_LIMIT = 5000
QUERY_TIMEOUT_S = 20

app = Flask(__name__)

# one shared read-only connection; DuckDB read connections are thread-safe via cursors
_con = duckdb.connect(DB, read_only=True)
_lock = threading.Lock()

BANNED = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|"
                    r"install|load|pragma|export|import|call|set|reset|vacuum|"
                    r"replace|truncate|grant)\b", re.I)


def guard_sql(sql: str) -> str:
    """Return a safe, bounded SELECT or raise ValueError."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("empty query")
    if ";" in s:
        raise ValueError("only a single statement is allowed")
    if not re.match(r"^(with|select)\b", s, re.I):
        raise ValueError("only SELECT / WITH queries are allowed")
    if BANNED.search(s):
        raise ValueError("only read-only SELECT queries are allowed")
    # every identifier that looks like a FROM/JOIN target must be whitelisted
    for tbl in re.findall(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", s, re.I):
        if tbl.lower() not in TABLES:
            raise ValueError(f"unknown table '{tbl}'. Allowed: {', '.join(sorted(TABLES))}")
    if not re.search(r"\blimit\s+\d+", s, re.I):
        s += f" LIMIT 1000"
    else:  # clamp an over-large limit
        s = re.sub(r"\blimit\s+(\d+)", lambda m: f"LIMIT {min(int(m.group(1)), MAX_LIMIT)}", s, flags=re.I)
    return s


def run_sql(sql: str):
    result = {}
    def _work():
        with _lock:
            cur = _con.cursor()
            rel = cur.execute(sql)
            result["cols"] = [d[0] for d in rel.description]
            result["rows"] = rel.fetchall()
    t = threading.Thread(target=_work, daemon=True)
    t.start(); t.join(QUERY_TIMEOUT_S)
    if t.is_alive():
        raise ValueError("query timed out")
    if "cols" not in result:
        raise ValueError("query failed")
    return result["cols"], [list(r) for r in result["rows"]]


SCHEMA_DOC = """Tables (DuckDB, read-only):

buildings  — one row per residential building that has at least one conspicuous daily-needs gap
             (Manhattan/Brooklyn/Queens; 203,792 rows). Columns:
  building_id, borough, neighborhood, lon, lat, units (residential units),
  median_income (of the building's area, USD),
  and boolean gap flags: missing_grocery, missing_convenience, missing_pharmacy,
  missing_laundry, missing_hair_barber, missing_nails_beauty, missing_restaurant,
  missing_cafe_bakery, missing_bar, missing_childcare, missing_clinic, missing_fitness.
  A flag is TRUE when no such business is within an ~800m walk though ≥80% of NYC buildings reach one.

neighborhoods — one row per NYC neighborhood (NTA), 145 rows. Columns:
  neighborhood, borough, population, median_income_2023,
  real_income_change_13_23_pct (inflation-adjusted % change 2013→2023),
  college_share_2023_pct, college_change_13_23_pp, median_age, avg_tenure_years
  (avg years residents have lived there), gym_age_share_pct (share aged 18-54),
  renter_share_pct, gap_buildings (total), and per-category <cat>_gap_buildings counts
  (grocery_gap_buildings, fitness_gap_buildings, pharmacy_gap_buildings, ...),
  investability_score, rising_score, buy_quadrant, top_missing_business
  (the last four are only populated for the validated buy-list neighborhoods).

pois — one row per real business (deduped), 158,374 rows. Columns:
  category (grocery, convenience, pharmacy, laundry, hair_barber, nails_beauty,
  restaurant, cafe_bakery, bar, childcare, clinic, fitness, bank, hardware, tailor_repair),
  name, borough, neighborhood, lon, lat."""


def nl_to_sql(question: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)
    sys = ("You translate questions into a single read-only DuckDB SQL query over this schema. "
           "Return ONLY the SQL, no prose, no markdown fences. Always add a sensible LIMIT (<=200). "
           "Use ILIKE for text matching on neighborhood/name.\n\n" + SCHEMA_DOC)
    r = client.chat.completions.create(model=OPENAI_MODEL, temperature=0,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": question}])
    sql = r.choices[0].message.content.strip()
    sql = re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.I | re.M).strip()
    return sql


def check_auth() -> bool:
    if not PASSWORD:
        return True
    return request.headers.get("X-Access", "") == PASSWORD or request.form.get("pw", "") == PASSWORD


@app.route("/")
def index():
    return PAGE


@app.route("/api/schema")
def schema():
    return jsonify({"schema": SCHEMA_DOC, "nl_enabled": bool(OPENAI_KEY), "needs_pw": bool(PASSWORD)})


@app.route("/api/query", methods=["POST"])
def query():
    if not check_auth():
        return jsonify({"error": "unauthorized — wrong or missing password"}), 401
    data = request.get_json(force=True)
    try:
        if data.get("mode") == "nl":
            if not OPENAI_KEY:
                return jsonify({"error": "natural-language mode is off (no OPENAI_API_KEY set on the server)"}), 400
            sql = nl_to_sql(data["q"])
        else:
            sql = data["q"]
        safe = guard_sql(sql)
        cols, rows = run_sql(safe)
        return jsonify({"sql": safe, "cols": cols, "rows": rows, "n": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e), "sql": locals().get("sql", "")}), 400


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Loci Query</title>
<link rel=preconnect href=https://fonts.googleapis.com><link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel=stylesheet>
<style>
:root{--paper:#F1F2F4;--surface:#fff;--ink:#171A1F;--ink2:#3C434D;--muted:#697079;--hair:#E1E4E8;--accent:#D9531F;--accent2:#1C6B5E}
@media(prefers-color-scheme:dark){:root{--paper:#0F1216;--surface:#191D24;--ink:#E9ECEF;--ink2:#C2C8CF;--muted:#8B939D;--hair:#2A303A;--accent:#EF6C3E;--accent2:#4FBBA6}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-family:Fraunces,serif;font-weight:600;font-size:30px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin:0 0 22px}
.tabs{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.tab{font-family:"IBM Plex Mono",monospace;font-size:12px;padding:8px 14px;border:1px solid var(--hair);border-radius:999px;background:var(--surface);cursor:pointer;color:var(--ink2)}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.panel{background:var(--surface);border:1px solid var(--hair);border-radius:14px;padding:18px 20px;margin-bottom:16px}
textarea,input,select{font-family:"IBM Plex Mono",monospace;font-size:13px;width:100%;padding:10px 12px;border:1px solid var(--hair);border-radius:9px;background:var(--paper);color:var(--ink)}
textarea{min-height:70px;resize:vertical}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:10px}
.row>div{flex:1;min-width:150px}label{font-size:11px;font-family:"IBM Plex Mono",monospace;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);display:block;margin-bottom:4px}
button.go{font-family:"IBM Plex Sans";font-weight:600;font-size:14px;background:var(--accent);color:#fff;border:0;border-radius:9px;padding:11px 22px;cursor:pointer;margin-top:10px}
.hint{font-size:12.5px;color:var(--muted);margin-top:8px}
.ex{color:var(--accent);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.sqlbox{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--muted);background:var(--paper);border:1px dashed var(--hair);border-radius:8px;padding:8px 12px;margin:12px 0;white-space:pre-wrap;word-break:break-word}
.err{color:#c0392b;font-size:13px;margin-top:10px}
@media(prefers-color-scheme:dark){.err{color:#ff8a70}}
.tblwrap{overflow:auto;max-height:60vh;border:1px solid var(--hair);border-radius:10px;margin-top:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:var(--surface);text-align:left;padding:9px 12px;border-bottom:2px solid var(--hair);font-family:"IBM Plex Mono",monospace;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--hair);font-variant-numeric:tabular-nums;white-space:nowrap}
tr:hover td{background:var(--paper)}
details{margin-top:14px}summary{cursor:pointer;font-size:12px;color:var(--accent);font-family:"IBM Plex Mono",monospace}
pre.schema{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--ink2);white-space:pre-wrap;background:var(--paper);padding:14px;border-radius:9px;border:1px solid var(--hair)}
.pwbar{margin-bottom:14px}
</style></head><body><div class=wrap>
<h1>Loci Query</h1>
<p class=sub>Ask the NYC retail-gap dataset directly — 203k gap buildings, 145 neighborhoods, 158k businesses. Read-only.</p>
<div class=pwbar id=pwbar hidden><label>Access password</label><input id=pw type=password placeholder="password" style=max-width:280px></div>
<div class=tabs>
  <div class="tab on" data-m=nl id=tabnl>Ask in English</div>
  <div class="tab" data-m=filter>Filters</div>
  <div class="tab" data-m=sql>SQL</div>
</div>

<div class=panel id=p_nl>
  <label>Your question</label>
  <textarea id=nlq placeholder="e.g. Which Queens neighborhoods have the most pharmacy gaps and income over $100k?"></textarea>
  <div class=hint>Try:
    <span class=ex onclick="setnl('Rising, investable neighborhoods on the buy list, best first')">the buy list</span> ·
    <span class=ex onclick="setnl('Neighborhoods where incomes rose most from 2013 to 2023')">biggest income gains</span> ·
    <span class=ex onclick="setnl('How many gyms are in East New York vs Williamsburg?')">gyms by area</span> ·
    <span class=ex onclick="setnl('Brooklyn buildings missing a grocery with income over 80000, top 50')">grocery gaps</span>
  </div>
  <button class=go onclick=ask()>Ask</button>
  <div class=hint id=nloff hidden>Natural-language mode is off until an OpenAI key is set on the server. Use Filters or SQL meanwhile.</div>
</div>

<div class=panel id=p_filter hidden>
  <div class=row>
    <div><label>Table</label><select id=f_table onchange=ftable()><option>neighborhoods</option><option>buildings</option><option>pois</option></select></div>
    <div><label>Borough</label><select id=f_boro><option value="">any</option><option>Manhattan</option><option>Brooklyn</option><option>Queens</option></select></div>
    <div id=f_catwrap><label>Missing business</label><select id=f_cat></select></div>
    <div><label>Min income</label><input id=f_inc type=number placeholder=e.g. 80000></div>
    <div><label>Rows</label><input id=f_lim type=number value=100></div>
  </div>
  <button class=go onclick=filt()>Run</button>
</div>

<div class=panel id=p_sql hidden>
  <label>SQL (SELECT only, tables: buildings · neighborhoods · pois)</label>
  <textarea id=sqlq>SELECT neighborhood, median_income_2023, real_income_change_13_23_pct, fitness_gap_buildings
FROM neighborhoods WHERE borough='Brooklyn' ORDER BY fitness_gap_buildings DESC LIMIT 20</textarea>
  <button class=go onclick=runsql()>Run</button>
  <details><summary>show schema</summary><pre class=schema id=schematext>loading…</pre></details>
</div>

<div id=out></div>
</div>
<script>
let MODE="nl", NEEDPW=false, NLON=true;
const cats=["grocery","convenience","pharmacy","laundry","hair_barber","nails_beauty","restaurant","cafe_bakery","bar","childcare","clinic","fitness"];
fetch('/api/schema').then(r=>r.json()).then(d=>{
  document.getElementById('schematext').textContent=d.schema;
  NEEDPW=d.needs_pw; NLON=d.nl_enabled;
  if(NEEDPW) document.getElementById('pwbar').hidden=false;
  if(!NLON){document.getElementById('nloff').hidden=false;}
});
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  MODE=t.dataset.m; document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on')); t.classList.add('on');
  for(const m of ['nl','filter','sql']) document.getElementById('p_'+m).hidden=(m!==MODE);
});
const cs=document.getElementById('f_cat'); cs.innerHTML='<option value="">any gap</option>'+cats.map(c=>`<option value=${c}>${c}</option>`).join('');
function ftable(){document.getElementById('f_catwrap').style.display=document.getElementById('f_table').value=='pois'?'none':'block';}
function setnl(q){document.getElementById('nlq').value=q;document.getElementById('tabnl').click();}
function hdrs(){const h={'Content-Type':'application/json'};if(NEEDPW)h['X-Access']=document.getElementById('pw').value;return h;}
function post(body){return fetch('/api/query',{method:'POST',headers:hdrs(),body:JSON.stringify(body)}).then(r=>r.json());}
function ask(){const q=document.getElementById('nlq').value.trim();if(q)go({mode:'nl',q});}
function runsql(){go({mode:'sql',q:document.getElementById('sqlq').value});}
function filt(){
  const t=document.getElementById('f_table').value,b=document.getElementById('f_boro').value,
    c=document.getElementById('f_cat').value,inc=document.getElementById('f_inc').value,lim=document.getElementById('f_lim').value||100;
  let w=[]; if(b)w.push(`borough='${b}'`);
  const inccol=t=='neighborhoods'?'median_income_2023':'median_income';
  if(inc&&t!='pois')w.push(`${inccol}>=${+inc}`);
  if(c&&t!='pois')w.push(`missing_${c}=true`);
  if(c&&t=='pois')w.push(`category='${c}'`);
  let sel='*', ord='';
  if(t=='neighborhoods'){sel='neighborhood,borough,population,median_income_2023,real_income_change_13_23_pct,'+(c?`${c}_gap_buildings`:'gap_buildings')+',investability_score,rising_score,buy_quadrant';ord='ORDER BY '+(c?`${c}_gap_buildings`:'gap_buildings')+' DESC';}
  if(t=='buildings'){sel='borough,neighborhood,units,median_income'+(c?`,missing_${c}`:'');ord='ORDER BY median_income DESC';}
  if(t=='pois'){sel='category,name,borough,neighborhood';}
  const sql=`SELECT ${sel} FROM ${t} ${w.length?'WHERE '+w.join(' AND '):''} ${ord} LIMIT ${lim}`;
  go({mode:'sql',q:sql});
}
function go(body){
  document.getElementById('out').innerHTML='<p class=hint>running…</p>';
  post(body).then(render);
}
function render(d){
  const o=document.getElementById('out');
  if(d.error){o.innerHTML=`<div class=panel>${d.sql?`<div class=sqlbox>${d.sql}</div>`:''}<div class=err>⚠ ${d.error}</div></div>`;return;}
  let h=`<div class=panel><div class=sqlbox>${d.sql}</div><div class=hint>${d.n} row${d.n==1?'':'s'}</div><div class=tblwrap><table><thead><tr>${d.cols.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>`;
  for(const r of d.rows) h+='<tr>'+r.map(v=>`<td>${v===null?'—':(typeof v=='number'?v.toLocaleString():v)}</td>`).join('')+'</tr>';
  h+='</tbody></table></div></div>'; o.innerHTML=h;
}
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
