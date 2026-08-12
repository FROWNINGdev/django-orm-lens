const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const {
  shouldPrompt,
  FIRST_PROMPT_AT,
  REPEAT_AFTER,
} = require('../out/starPrompt');

test.after(() => {
  Module._load = originalLoad;
});

const fresh = (over = {}) => ({
  opens: 0,
  dismissedAt: null,
  silenced: false,
  ...over,
});

test('stays quiet before the tool has proved useful', () => {
  for (let opens = 0; opens < FIRST_PROMPT_AT; opens++) {
    assert.equal(shouldPrompt(fresh({ opens })), false, `opens=${opens}`);
  }
});

test('asks on the third diagram, not on install', () => {
  assert.equal(shouldPrompt(fresh({ opens: FIRST_PROMPT_AT })), true);
});

test('silenced state is never prompted, however many opens', () => {
  assert.equal(shouldPrompt(fresh({ opens: 999, silenced: true })), false);
});

test('"Later" defers rather than declines, and re-arms exactly once', () => {
  const deferred = fresh({ opens: 3, dismissedAt: 3 });

  // Silent through the whole gap — the failure mode being guarded against is
  // re-asking on the very next open.
  for (let n = 4; n < 3 + REPEAT_AFTER; n++) {
    assert.equal(shouldPrompt({ ...deferred, opens: n }), false, `opens=${n}`);
  }
  assert.equal(shouldPrompt({ ...deferred, opens: 3 + REPEAT_AFTER }), true);
});

test('a deferral late in life still gets its full gap', () => {
  // Regression guard: an implementation comparing against FIRST_PROMPT_AT
  // instead of dismissedAt would re-ask immediately here.
  const deferred = fresh({ opens: 40, dismissedAt: 40 });
  assert.equal(shouldPrompt({ ...deferred, opens: 41 }), false);
  assert.equal(shouldPrompt({ ...deferred, opens: 40 + REPEAT_AFTER }), true);
});

test('thresholds are injectable, so the policy is testable without rebuilding', () => {
  assert.equal(shouldPrompt(fresh({ opens: 1 }), 1), true);
  assert.equal(shouldPrompt(fresh({ opens: 5, dismissedAt: 5 }), 1, 2), false);
  assert.equal(shouldPrompt(fresh({ opens: 7, dismissedAt: 5 }), 1, 2), true);
});
