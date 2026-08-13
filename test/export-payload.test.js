const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { decodeExportPayload } = require('../out/graphWebview');

test.after(() => {
  Module._load = originalLoad;
});

// What html-to-image actually returns from toSvg(): percent-encoded markup,
// not base64. Reading it as base64 is silent corruption, never an exception.
const svgMarkup =
  '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">' +
  '<text x="10" y="20">Order &#8594; Product &#183; Ünïcode</text></svg>';
const svgDataUrl =
  'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgMarkup);

test('svg export round-trips the markup byte for byte', () => {
  assert.equal(decodeExportPayload(svgDataUrl).toString('utf-8'), svgMarkup);
});

test('svg export starts with an <svg tag, not binary noise', () => {
  const head = decodeExportPayload(svgDataUrl).subarray(0, 4).toString('utf-8');
  assert.equal(head, '<svg');
});

test('png export still decodes as base64', () => {
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const url = 'data:image/png;base64,' + png.toString('base64');
  assert.deepEqual(decodeExportPayload(url), png);
});

test('base64 wins when the header carries both charset and base64', () => {
  const url =
    'data:image/svg+xml;charset=utf-8;base64,' +
    Buffer.from(svgMarkup, 'utf-8').toString('base64');
  assert.equal(decodeExportPayload(url).toString('utf-8'), svgMarkup);
});

test('a bare payload with no data: prefix is written as text', () => {
  assert.equal(decodeExportPayload(svgMarkup).toString('utf-8'), svgMarkup);
});

test('a malformed escape keeps the export instead of throwing', () => {
  const url = 'data:image/svg+xml;charset=utf-8,%E0%A4%A';
  assert.equal(decodeExportPayload(url).toString('utf-8'), '%E0%A4%A');
});
