const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { datetimeRules } = require('../../out/rules/datetime');

test.after(() => {
  Module._load = originalLoad;
});

function makeCtx(source) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    lineCount: lines.length,
    lineAt(i) {
      return lines[i] ?? '';
    },
    windowBefore(i, n) {
      return lines.slice(Math.max(0, i - n), i);
    },
    windowAfter(i, n) {
      return lines.slice(i + 1, Math.min(lines.length, i + 1 + n));
    },
  };
}

function ruleByCode(code) {
  const r = datetimeRules.find((r) => r.meta.code === code);
  assert.ok(r, `rule ${code} must exist`);
  return r;
}

test('DOL021 flags datetime.now()', () => {
  const rule = ruleByCode('DOL021');
  const findings = rule.check(makeCtx('now = datetime.now()'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL021 leaves datetime.datetime.now() alone (attribute access)', () => {
  const rule = ruleByCode('DOL021');
  const findings = rule.check(makeCtx('now = datetime.datetime.now()'));
  assert.equal(findings.length, 0);
});

test('DOL021 leaves timezone.now() alone', () => {
  const rule = ruleByCode('DOL021');
  const findings = rule.check(makeCtx('now = timezone.now()'));
  assert.equal(findings.length, 0);
});

test('DOL022 flags datetime.utcnow()', () => {
  const rule = ruleByCode('DOL022');
  const findings = rule.check(makeCtx('ts = datetime.utcnow()'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL022 ignores commented lines', () => {
  const rule = ruleByCode('DOL022');
  const findings = rule.check(makeCtx('# ts = datetime.utcnow() legacy'));
  assert.equal(findings.length, 0);
});
