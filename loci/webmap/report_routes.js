'use strict';
// The allocator-report job routes (D100, GTM-172, seed AC-22) plus the
// address-search fallback (D99, GTM-171, AC-14) -- kept in its own file so
// `server.js`'s existing request handler needs only the ONE line the design
// calls for: `if(await require('./report_routes').handle(req,res))return;`.
//
// GATING (seed "Report rule"): `loci report` can spend real money (Google
// Places, Tavily, Anthropic), so the job routes -- POST /api/report and
// GET /api/report/:job_id -- are OFF unless LOCI_REPORT_ENABLED=1 is set in
// the server's environment; `handle()` returns false for them (falls through
// to the normal 404) rather than answering with an error, so an unconfigured
// server behaves exactly as it did before this file existed. GET /api/snap
// is NOT gated -- it only reads the warehouse (no paid call, matching
// geo/geosearch.py's own "FREE AND KEYLESS" contract) and it is the search
// box's only way to resolve a GeoSearch hit that address_index.json misses.
//
// ONE CONCURRENT JOB (module-level `running`), per the design -- a second
// POST while one is in flight gets 429, not a second `uv run loci report`
// racing the first for the same spend ledger.
//
// COMMAND IS OVERRIDABLE. `LOCI_REPORT_CMD` (default `uv run loci report`)
// is a shell-style command line; the address_id is appended as its final
// argument. Tests point it at a stub script so no test ever spends money or
// needs a real warehouse -- see tests/test_report_routes.js.
const {spawn, spawnSync} = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.join(__dirname, '..');
const REPORT_CMD = process.env.LOCI_REPORT_CMD || 'uv run loci report';
const REPORT_ENABLED = process.env.LOCI_REPORT_ENABLED === '1';

const jobs = new Map();
let running = false;

function newJobId() {
  return 'job-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; if (data.length > 1e6) req.destroy(); });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function sendJSON(res, status, obj) {
  res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  res.end(JSON.stringify(obj));
}

// Scans the job's collected output for the markdown path `loci report`
// prints on success ("ok <path> $usd run_id=..."), or that a test stub
// prints as its own last line -- either way, "the last token in the output
// that ends in .md" is the one contract both sides need to agree on.
function findMarkdownPath(lines) {
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = lines[i].match(/(\S+\.md)\b/);
    if (m) return m[1];
  }
  return null;
}

function startJob(addressId) {
  const jobId = newJobId();
  const job = {status: 'running', progress_lines: [`starting report for ${addressId}…`],
              path: null, markdown: null};
  jobs.set(jobId, job);
  running = true;

  const parts = REPORT_CMD.split(' ').filter(Boolean);
  const cmd = parts[0];
  const args = parts.slice(1).concat([addressId]);
  let child;
  try {
    child = spawn(cmd, args, {cwd: REPO_ROOT});
  } catch (err) {
    job.status = 'error';
    job.progress_lines.push(String((err && err.message) || err));
    running = false;
    return jobId;
  }

  const onData = (buf) => {
    String(buf).split(/\r?\n/).filter(Boolean).forEach((line) => job.progress_lines.push(line));
  };
  child.stdout.on('data', onData);
  child.stderr.on('data', onData);
  child.on('error', (err) => {
    job.status = 'error';
    job.progress_lines.push(String((err && err.message) || err));
    running = false;
  });
  child.on('close', (code) => {
    running = false;
    if (job.status === 'error') return;   // already reported via 'error' above
    if (code !== 0) {
      job.status = 'error';
      job.progress_lines.push(`exited with code ${code}`);
      return;
    }
    let mdPath = findMarkdownPath(job.progress_lines);
    if (mdPath && !path.isAbsolute(mdPath)) mdPath = path.join(REPO_ROOT, mdPath);
    if (mdPath && fs.existsSync(mdPath)) {
      job.path = path.relative(REPO_ROOT, mdPath);
      job.markdown = fs.readFileSync(mdPath, 'utf8');
      job.status = 'done';
    } else {
      job.status = 'error';
      job.progress_lines.push('report finished but no markdown file was found');
    }
  });
  return jobId;
}

async function handleReportPost(req, res) {
  if (running) return sendJSON(res, 429, {error: 'a report is already running'});
  let body;
  try {
    body = JSON.parse((await readBody(req)) || '{}');
  } catch (err) {
    return sendJSON(res, 400, {error: 'bad json'});
  }
  const addressId = body && body.address_id;
  if (!addressId || typeof addressId !== 'string') {
    return sendJSON(res, 400, {error: 'address_id required'});
  }
  const jobId = startJob(addressId);
  sendJSON(res, 202, {job_id: jobId});
}

function handleReportGet(res, jobId) {
  const job = jobs.get(jobId);
  if (!job) return sendJSON(res, 404, {error: 'unknown job'});
  sendJSON(res, 200, {status: job.status, progress_lines: job.progress_lines,
                      path: job.path, markdown: job.markdown});
}

// GET /api/snap?lat=&lon= -- the search box's fallback when address_index.json
// (a bbl -> address_id map, lot-frame rows only) has no entry for the
// GeoSearch hit's BBL, or the hit carried none. Shells out to a one-line
// Python program rather than adding a Node DuckDB dependency to the webmap
// server -- "through `uv run loci` or a tiny python -c; keep it simple"
// (design S4). NotInCoverage is the expected miss, not a server error.
function handleSnap(res, u) {
  const lat = parseFloat(u.searchParams.get('lat'));
  const lon = parseFloat(u.searchParams.get('lon'));
  if (!isFinite(lat) || !isFinite(lon)) return sendJSON(res, 400, {error: 'bad'});
  const py = [
    'import json',
    'from loci import db as locidb',
    'from loci.geo.geosearch import GeoHit, NotInCoverage, snap',
    'con = locidb.connect(read_only=True)',
    'try:',
    `    aid = snap(con, GeoHit(label="", lat=${lat}, lon=${lon}))`,
    '    print(json.dumps({"address_id": aid}))',
    'except NotInCoverage as exc:',
    '    print(json.dumps({"error": str(exc)}))',
  ].join('\n');
  const r = spawnSync('uv', ['run', 'python', '-c', py], {cwd: REPO_ROOT, encoding: 'utf8'});
  if (r.error || r.status !== 0) {
    return sendJSON(res, 503, {error: 'snap unavailable'});
  }
  let out;
  try {
    const lastLine = r.stdout.trim().split(/\r?\n/).pop();
    out = JSON.parse(lastLine);
  } catch (err) {
    return sendJSON(res, 503, {error: 'snap unavailable'});
  }
  if (out.error) return sendJSON(res, 404, out);
  return sendJSON(res, 200, out);
}

// Returns true iff this module answered the request (server.js must not fall
// through to the static file handler); false otherwise.
async function handle(req, res) {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;

  if (p === '/api/snap') {
    handleSnap(res, u);
    return true;
  }
  if (!REPORT_ENABLED) return false;
  if (p === '/api/report' && req.method === 'POST') {
    await handleReportPost(req, res);
    return true;
  }
  const m = p.match(/^\/api\/report\/([^/]+)$/);
  if (m && req.method === 'GET') {
    handleReportGet(res, decodeURIComponent(m[1]));
    return true;
  }
  return false;
}

module.exports = {handle, _jobs: jobs};
