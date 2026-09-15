// Node smoke test for webmap/report_routes.js (D100, GTM-172, seed AC-22).
// Run with: node --test tests/test_report_routes.js
//
// Uses Node's built-in test runner (node:test) rather than a new
// dependency -- this repo's webmap server is itself dependency-free
// (webmap/server.js requires only Node builtins). `LOCI_REPORT_CMD` points
// at tests/fixtures/report_stub.js (a fake `loci report <address_id>` that
// writes a small markdown file and prints its path) so this test spends no
// money and needs no warehouse -- exactly the injection point the seed's
// "command overridable by LOCI_REPORT_CMD for tests" line describes.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const STUB = path.join(__dirname, 'fixtures', 'report_stub.js');
const ROUTES_PATH = require.resolve('../webmap/report_routes.js');

function freshRoutes() {
  delete require.cache[ROUTES_PATH];
  return require(ROUTES_PATH);
}

function startServer(routes) {
  const server = http.createServer(async (req, res) => {
    const handled = await routes.handle(req, res);
    if (!handled) { res.writeHead(404); res.end('not found'); }
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

function closeServer(server) {
  return new Promise((resolve) => server.close(resolve));
}

async function pollJob(base, jobId, {tries = 100, everyMs = 25} = {}) {
  let job;
  for (let i = 0; i < tries; i++) {
    const r = await fetch(`${base}/api/report/${jobId}`);
    job = await r.json();
    if (job.status !== 'running') return job;
    await new Promise((resolve) => setTimeout(resolve, everyMs));
  }
  return job;
}

test('LOCI_REPORT_ENABLED unset: the job routes are OFF (handle falls through)', async () => {
  delete process.env.LOCI_REPORT_ENABLED;
  const routes = freshRoutes();
  const server = await startServer(routes);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const r = await fetch(`${base}/api/report`, {method: 'POST', body: '{}'});
    assert.equal(r.status, 404, 'unhandled -> falls to the test harness\'s own 404');
  } finally {
    await closeServer(server);
  }
});

test('GET /api/snap is never gated (bad query -> 400, not 404)', async () => {
  delete process.env.LOCI_REPORT_ENABLED;
  const routes = freshRoutes();
  const server = await startServer(routes);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const r = await fetch(`${base}/api/snap?lat=nope&lon=nope`);
    assert.equal(r.status, 400);
  } finally {
    await closeServer(server);
  }
});

test('enabled: POST /api/report -> GET job -> done markdown from the stub', async () => {
  const stubDir = fs.mkdtempSync(path.join(os.tmpdir(), 'loci-report-test-'));
  process.env.LOCI_REPORT_ENABLED = '1';
  process.env.LOCI_REPORT_CMD = `node ${STUB}`;
  process.env.LOCI_REPORT_STUB_DIR = stubDir;
  const routes = freshRoutes();
  const server = await startServer(routes);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const postRes = await fetch(`${base}/api/report`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address_id: 'addr1'}),
    });
    assert.equal(postRes.status, 202);
    const {job_id: jobId} = await postRes.json();
    assert.ok(jobId);

    const job = await pollJob(base, jobId);
    assert.equal(job.status, 'done');
    assert.match(job.markdown, /## 1\. Category call/);
    assert.match(job.markdown, /## 2\. Supply/);
    assert.match(job.markdown, /## 3\. Demand and catchment economics/);
    assert.match(job.markdown, /## 4\. Legality, rents, risk and exit/);
    assert.ok(job.path.endsWith('addr1.md'));

    const getUnknown = await fetch(`${base}/api/report/nope-not-a-job`);
    assert.equal(getUnknown.status, 404);
  } finally {
    await closeServer(server);
    delete process.env.LOCI_REPORT_ENABLED;
    delete process.env.LOCI_REPORT_CMD;
    delete process.env.LOCI_REPORT_STUB_DIR;
  }
});

test('one concurrent job: a second POST while one runs is refused with 429', async () => {
  const stubDir = fs.mkdtempSync(path.join(os.tmpdir(), 'loci-report-test-'));
  process.env.LOCI_REPORT_ENABLED = '1';
  process.env.LOCI_REPORT_CMD = `node ${STUB}`;
  process.env.LOCI_REPORT_STUB_DIR = stubDir;
  process.env.LOCI_REPORT_STUB_DELAY_MS = '400';
  const routes = freshRoutes();
  const server = await startServer(routes);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const first = await fetch(`${base}/api/report`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address_id: 'addr1'}),
    });
    assert.equal(first.status, 202);

    const second = await fetch(`${base}/api/report`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address_id: 'addr2'}),
    });
    assert.equal(second.status, 429);

    const {job_id: jobId} = await first.json();
    const job = await pollJob(base, jobId, {tries: 100, everyMs: 25});
    assert.equal(job.status, 'done');
  } finally {
    await closeServer(server);
    delete process.env.LOCI_REPORT_ENABLED;
    delete process.env.LOCI_REPORT_CMD;
    delete process.env.LOCI_REPORT_STUB_DIR;
    delete process.env.LOCI_REPORT_STUB_DELAY_MS;
  }
});

test('a failing command reports status "error"', async () => {
  process.env.LOCI_REPORT_ENABLED = '1';
  process.env.LOCI_REPORT_CMD = 'node -e process.exit(1)';
  const routes = freshRoutes();
  const server = await startServer(routes);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const postRes = await fetch(`${base}/api/report`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address_id: 'addr1'}),
    });
    assert.equal(postRes.status, 202);
    const {job_id: jobId} = await postRes.json();
    const job = await pollJob(base, jobId);
    assert.equal(job.status, 'error');
  } finally {
    await closeServer(server);
    delete process.env.LOCI_REPORT_ENABLED;
    delete process.env.LOCI_REPORT_CMD;
  }
});
