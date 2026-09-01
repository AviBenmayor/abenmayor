"""Hearth lead routing dashboard.

Two audiences in one app, deliberately:
  /            the rep view -- a ranked queue and a per-lead card that says what to do
  /speed /cutoff /model   the manager view -- the evidence behind the ranking and the
               cutoff, so the person who has to defend the policy can see the workings

Auth is HTTP Basic and fails closed. The data pack is confidential per the brief, so an
unset password is treated as a misconfiguration, not as "open to the world".
"""
import io
import os
import secrets
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import charts, data
from .scoring import score_frame

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
app = FastAPI(title="Hearth lead routing", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals.update(charts=charts, TIER=data.TIER_META)

security = HTTPBasic(auto_error=False)
USER = os.getenv("DASH_USER", "hearth")
PASSWORD = os.getenv("DASH_PASSWORD")
ALLOW_OPEN = os.getenv("DASH_ALLOW_OPEN") == "1"


def auth(creds: HTTPBasicCredentials = Depends(security)):
    if ALLOW_OPEN:
        return "local"
    if not PASSWORD:
        raise HTTPException(503, "DASH_PASSWORD is not set. Refusing to serve lead data "
                                 "without a credential.")
    ok = creds and secrets.compare_digest(creds.username, USER) and \
        secrets.compare_digest(creds.password, PASSWORD)
    if not ok:
        raise HTTPException(401, "Unauthorized", {"WWW-Authenticate": "Basic"})
    return creds.username


def page(req, name, **ctx):
    a = data.analytics()
    return tpl.TemplateResponse(req, name, {"a": a, "cap": a["capacity"], "open": ALLOW_OPEN, **ctx})


@app.get("/healthz")
def healthz():
    return {"ok": True, "leads": len(data.leads())}


@app.get("/", response_class=HTMLResponse)
def queue(request: Request, _=Depends(auth),
          day: str = Query(""), tier: str = Query(""), q: str = Query(""),
          page_n: int = Query(1, alias="p")):
    df = data.leads()
    days = data.day_index()
    if day == "all":
        view = df
    else:
        if not day:
            day = days[len(days) // 2]["date"]      # a typical mid-window day
        view = df[df.created_date.eq(day)]
    if tier:
        view = view[view.tier.eq(tier)]
    if q:
        s = q.strip().lower()
        mask = False
        for c in ["lead_id", "state", "icp_category", "channel", "utm_medium",
                  "contractor_annual_revenue", "campaign_ref"]:
            mask = mask | view[c].astype(str).str.lower().str.contains(s, na=False)
        view = view[mask]

    per = 60
    total = len(view)
    pages = max(1, -(-total // per))
    page_n = max(1, min(page_n, pages))
    rows = view.iloc[(page_n - 1) * per: page_n * per]
    counts = view.tier.value_counts().to_dict()
    return page(request, "queue.html", rows=rows.to_dict("records"), day=day, days=days,
                tier=tier, q=q, total=total, page_n=page_n, pages=pages, counts=counts,
                touch_load=int((view.planned_touches).sum()))


@app.get("/lead/{lead_id}", response_class=HTMLResponse)
def lead(request: Request, lead_id: str, _=Depends(auth)):
    df = data.leads()
    hit = df[df.lead_id.eq(lead_id)]
    if hit.empty:
        raise HTTPException(404, f"{lead_id} is not in the Mar-May scoring window.")
    r = hit.iloc[0].to_dict()
    a = data.analytics()
    obj = a["objections"].get(r["icp_category"]) or a["objections"]["__overall__"]
    return page(request, "lead.html", r=r, play=data.play_for(r["tier"]), obj=obj,
                rank=int(hit.index[0]) + 1, n=len(df))


@app.get("/score", response_class=HTMLResponse)
def score_form(request: Request, _=Depends(auth)):
    return page(request, "score.html", result=None, warn=[], pasted="")


@app.post("/score", response_class=HTMLResponse)
async def score_post(request: Request, _=Depends(auth),
                     pasted: str = Form(""), upload: UploadFile = File(None)):
    raw, err = None, None
    try:
        if upload is not None and upload.filename:
            raw = pd.read_csv(io.BytesIO(await upload.read()), dtype=str)
        elif pasted.strip():
            raw = pd.read_csv(io.StringIO(pasted.strip()), dtype=str)
        else:
            err = "Paste a CSV block or choose a file."
    except Exception as e:
        err = f"Could not parse that as CSV: {e}"
    if raw is not None and raw.empty:
        err = "That parsed to zero rows."
    if err:
        return page(request, "score.html", result=None, warn=[err], pasted=pasted)
    try:
        out, warn = score_frame(raw)
    except Exception as e:                      # never 500 in front of the room
        return page(request, "score.html", result=None,
                    warn=[f"Scoring failed: {type(e).__name__}: {e}"], pasted=pasted)
    merged = raw.reset_index(drop=True).join(out.drop(columns=["lead_id"]))
    return page(request, "score.html", result=out.to_dict("records"),
                merged=merged.to_dict("records"), warn=warn, pasted=pasted)


@app.post("/api/score")
async def api_score(request: Request, _=Depends(auth)):
    """Live scoring endpoint. Accepts a single object or a list of them.

    curl -u hearth:$PW -H 'content-type: application/json' -d '{"channel":"google",...}' \\
         https://<host>/api/score
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body is not valid JSON. Send an object or a list "
                                      "of objects with the intake columns."}, status_code=400)
    rows = body if isinstance(body, list) else [body]
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return JSONResponse({"error": "Expected a JSON object or a list of objects."},
                            status_code=400)
    if not rows:
        return JSONResponse({"error": "No rows supplied."}, status_code=400)
    try:
        out, warn = score_frame(pd.DataFrame(rows).astype(str))
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)
    a = data.analytics()["model"]
    return {"scored": out.to_dict("records"), "warnings": warn,
            "model": {"target": "expected dollars = P(win) x E[amount | win]",
                      "features": data.model_json()["features"],
                      "trained_on": "Oct 2025 - Feb 2026",
                      "out_of_time_auc": a["temporal"]["logit"]["auc"],
                      "baseline_auc": a["temporal"]["legacy_score (baseline)"]["auc"]}}


@app.get("/speed", response_class=HTMLResponse)
def speed(request: Request, _=Depends(auth)):
    return page(request, "speed.html", s=data.analytics()["speed"])


@app.get("/cutoff", response_class=HTMLResponse)
def cutoff(request: Request, _=Depends(auth),
           a_pct: int = Query(10), b_pct: int = Query(20), c_pct: int = Query(30),
           reps: int = Query(0), tpd: int = Query(0)):
    cap = data.analytics()["capacity"]
    reps = reps or cap["core_reps"]
    tpd = tpd or cap["touches_per_rep_day"]
    df = data.leads().sort_values("score", ascending=False).reset_index(drop=True)
    n = len(df)
    a_pct = max(0, min(100, a_pct))
    b_pct = max(0, min(100 - a_pct, b_pct))
    c_pct = max(0, min(100 - a_pct - b_pct, c_pct))
    bounds = [("A", 0, a_pct), ("B", a_pct, a_pct + b_pct),
              ("C", a_pct + b_pct, a_pct + b_pct + c_pct),
              ("D", a_pct + b_pct + c_pct, 100)]
    spend = {d["code"]: d["touches"] for d in cap["tier_defs"]}
    pct = (pd.Series(range(n)) + 0.5) / n * 100
    tot_p = df.p_win.sum()
    rows = []
    for code, lo, hi in bounds:
        sel = df[(pct >= lo) & (pct < hi)]
        rows.append({"tier": code, "name": data.TIER_META[code]["name"], "n": len(sel),
                     "share": len(sel) / n * 100,
                     "mean_p": float(sel.p_win.mean() * 100) if len(sel) else 0.0,
                     "wins": float(sel.p_win.sum()),
                     "pct_wins": float(sel.p_win.sum() / tot_p * 100),
                     "touches": spend[code], "budget": len(sel) * spend[code]})
    used = sum(r["budget"] for r in rows)
    supply = reps * tpd * cap["business_days"]
    return page(request, "cutoff.html", rows=rows, used=used, supply=supply,
                a_pct=a_pct, b_pct=b_pct, c_pct=c_pct, reps=reps, tpd=tpd,
                worked_wins=sum(r["pct_wins"] for r in rows if r["tier"] != "D"),
                dropped=[r for r in rows if r["tier"] == "D"][0])


@app.get("/model", response_class=HTMLResponse)
def model(request: Request, _=Depends(auth)):
    return page(request, "model.html")


@app.get("/submission.csv")
def submission(_=Depends(auth)):
    """Byte-identical to output/submission.csv -- same scorer, same thresholds, same
    rounding. If this file and the one we submitted ever differ, one of them is wrong."""
    df = data.leads()[["lead_id", "score", "tier"]].copy()
    df["score"] = df.score.round(2)
    return Response(df.to_csv(index=False), media_type="text/csv",
                    headers={"content-disposition": "attachment; filename=submission.csv"})


@app.get("/tool", response_class=HTMLResponse)
def tool(_=Depends(auth)):
    """The offline rep tool, served from the same box so it has a link.

    This is the SAME 57 KB file as tool/lead_queue.html -- not a server-rendered copy. It
    still scores entirely in the browser and still works with the network off; serving it
    here just saves emailing an attachment.

    Behind auth like everything else: the file embeds a 500-row parity vector of real
    lead_ids and their scores, and the brief says not to post the pack anywhere.
    """
    f = ROOT / "tool" / "lead_queue.html"
    if not f.exists():
        raise HTTPException(503, "tool/lead_queue.html is not in the image. Run "
                                 "src/build_tool.py and redeploy.")
    return HTMLResponse(f.read_text())


@app.get("/api/historical")
def historical(_=Depends(auth)):
    """The Oct-Feb window, for the Historical tab, behind the same credential.

    A deliberate exception to "the container never sees the pack" (app/data.py), taken so
    the tab is demonstrable without local files. Narrowed on purpose: activities.csv is
    excluded entirely, and the five lead columns the tool cannot use never leave the
    machine. See src/build_demo_bundle.py. Delete the service when the process concludes.
    """
    f = ROOT / "output" / "app_data" / "historical.json.gz"
    if not f.exists():
        raise HTTPException(404, "No historical bundle in this image. Run "
                                 "src/build_demo_bundle.py and redeploy.")
    return Response(f.read_bytes(), media_type="application/json",
                    headers={"content-encoding": "gzip", "cache-control": "private, max-age=3600"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"
