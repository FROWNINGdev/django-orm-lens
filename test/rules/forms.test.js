const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { formsRules } = require('../../out/rules/forms');

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
  const r = formsRules.find((r) => r.meta.code === code);
  assert.ok(r, `rule ${code} must exist`);
  return r;
}

test('DOL031 flags render(request, "tpl", locals())', () => {
  const rule = ruleByCode('DOL031');
  const findings = rule.check(
    makeCtx('return render(request, "index.html", locals())'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL031 leaves render() with explicit dict alone', () => {
  const rule = ruleByCode('DOL031');
  const findings = rule.check(
    makeCtx('return render(request, "index.html", {"user": user})'),
  );
  assert.equal(findings.length, 0);
});

test("DOL032 flags fields = '__all__' (single quotes)", () => {
  const rule = ruleByCode('DOL032');
  const findings = rule.check(makeCtx("        fields = '__all__'"));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'unsafe');
});

test('DOL032 flags fields = "__all__" (double quotes)', () => {
  const rule = ruleByCode('DOL032');
  const findings = rule.check(makeCtx('        fields = "__all__"'));
  assert.equal(findings.length, 1);
});

test('DOL032 leaves explicit field lists alone', () => {
  const rule = ruleByCode('DOL032');
  const findings = rule.check(
    makeCtx('        fields = ["name", "email", "created_at"]'),
  );
  assert.equal(findings.length, 0);
});
