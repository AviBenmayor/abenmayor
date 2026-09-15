#!/usr/bin/env node
// Stand-in for `uv run loci report <address_id>` (D100, GTM-172), used only
// by tests/test_report_routes.js via LOCI_REPORT_CMD. Writes a small
// markdown file with the four report headings and prints its absolute path
// as the LAST stdout line -- report_routes.js's `findMarkdownPath` scans
// exactly for that ("the last token in the output that ends in .md").
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const addressId = process.argv[2] || 'unknown';
const delayMs = parseInt(process.env.LOCI_REPORT_STUB_DELAY_MS || '0', 10);

function writeAndPrint() {
  console.log('stub: assembling evidence pack');
  const outDir = process.env.LOCI_REPORT_STUB_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'loci-report-stub-'));
  fs.mkdirSync(outDir, {recursive: true});
  const outPath = path.join(outDir, `${addressId}.md`);
  fs.writeFileSync(outPath, [
    `# Allocator report -- ${addressId}`,
    '',
    '## 1. Category call',
    'stub category call.',
    '',
    '## 2. Supply',
    'stub supply table.',
    '',
    '## 3. Demand and catchment economics',
    'stub demand section.',
    '',
    '## 4. Legality, rents, risk and exit',
    'stub legality section.',
    '',
  ].join('\n'));
  console.log('stub: done');
  console.log(outPath);
}

console.log(`stub: generating report for ${addressId}`);
if (delayMs > 0) setTimeout(writeAndPrint, delayMs);
else writeAndPrint();
