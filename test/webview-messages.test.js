const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { acceptsMessage, EXTENSION_MESSAGE_TYPES } = require('../out/webviewMessages');

test.after(() => {
  Module._load = originalLoad;
});

const SELF = 'vscode-webview://0e6f1a2b';

const push = (over = {}) => ({
  origin: SELF,
  data: { type: 'index', payload: { apps: [], scannedAt: 0, theme: 'dark' } },
  ...over,
});

test('an index push from the panel own origin is accepted', () => {
  assert.equal(acceptsMessage(push(), SELF), true);
});

test('a theme push from the panel own origin is accepted', () => {
  assert.equal(acceptsMessage(push({ data: { type: 'theme', payload: 'light' } }), SELF), true);
});

// The regression this file exists for. The guard reported in #55 compared
// `source` against `window`, and a real push carries a `source` matching
// neither `window` nor `window.parent` — so every host message was dropped and
// an open ER panel silently stopped updating. A message whose `source` is
// foreign but whose `origin` is our own must still be accepted.
test('#55: a push is accepted no matter what its source is', () => {
  for (const source of [null, undefined, {}, { name: 'not-window' }]) {
    assert.equal(acceptsMessage(push({ source }), SELF), true, `source=${JSON.stringify(source)}`);
  }
});

test('a push from a foreign origin is rejected', () => {
  assert.equal(acceptsMessage(push({ origin: 'https://evil.example' }), SELF), false);
});

test('an origin that merely looks like ours is rejected', () => {
  assert.equal(acceptsMessage(push({ origin: SELF + '.evil.example' }), SELF), false);
});

test('a message with no origin at all is rejected', () => {
  assert.equal(acceptsMessage({ data: { type: 'index' } }, SELF), false);
});

test('unknown message types are rejected even from our own origin', () => {
  assert.equal(acceptsMessage(push({ data: { type: 'eval' } }), SELF), false);
  assert.equal(acceptsMessage(push({ data: { type: '' } }), SELF), false);
});

test('non-object payloads are rejected rather than thrown on', () => {
  for (const data of [null, undefined, 'index', 42, true]) {
    assert.equal(acceptsMessage(push({ data }), SELF), false, `data=${String(data)}`);
  }
});

test('a null or missing event is rejected rather than thrown on', () => {
  assert.equal(acceptsMessage(null, SELF), false);
  assert.equal(acceptsMessage(undefined, SELF), false);
});

test('the accepted set is exactly what the host sends', () => {
  assert.deepEqual([...EXTENSION_MESSAGE_TYPES].sort(), ['index', 'theme']);
});
