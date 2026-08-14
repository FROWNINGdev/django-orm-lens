const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

// Shim the `vscode` module — rules only touch it via type-only imports at
// build time; at runtime the plain `{}` shim is sufficient because none of
// the rule-check code paths call into a vscode.* runtime member.
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { querysetRules } = require('../../out/rules/queryset');

test.after(() => {
  Module._load = originalLoad;
});

/** Build a fake `RuleContext` from a source string. */
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
  const r = querysetRules.find((r) => r.meta.code === code);
  assert.ok(r, `rule ${code} must exist`);
  return r;
}

test('DOL001 flags qs.count() > 0 and reports the qs prefix as fixHint', () => {
  const rule = ruleByCode('DOL001');
  const findings = rule.check(makeCtx('if User.objects.filter(a=1).count() > 0:'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, 'DOL001');
  assert.equal(findings[0].applicability, 'safe');
  assert.equal(findings[0].fixHint, 'User.objects.filter(a=1)');
});

test('DOL001 ignores commented lines', () => {
  const rule = ruleByCode('DOL001');
  const findings = rule.check(makeCtx('# if qs.count() > 0: legacy'));
  assert.equal(findings.length, 0);
});

test('DOL001 matches >= 1 form too', () => {
  const rule = ruleByCode('DOL001');
  const findings = rule.check(makeCtx('assert qs.count() >= 1'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'qs');
});

test('DOL002 flags qs.count() == 0', () => {
  const rule = ruleByCode('DOL002');
  const findings = rule.check(makeCtx('return Foo.objects.count() == 0'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'Foo.objects');
});

test('DOL003 flags qs.first() is None', () => {
  const rule = ruleByCode('DOL003');
  const findings = rule.check(
    makeCtx('if User.objects.filter(id=1).first() is None:'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'User.objects.filter(id=1)');
});

test('DOL004 flags qs.first() is not None', () => {
  const rule = ruleByCode('DOL004');
  const findings = rule.check(makeCtx('while Book.objects.first() is not None:'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'Book.objects');
});

test('DOL005 flags .filter().exclude() chain as a hint', () => {
  const rule = ruleByCode('DOL005');
  const findings = rule.check(
    makeCtx('users = User.objects.filter(active=True).exclude(banned=True)'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL006 flags list() around a QuerySet inside for', () => {
  const rule = ruleByCode('DOL006');
  const findings = rule.check(
    makeCtx('for u in list(User.objects.filter(active=True)):'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'safe');
  assert.equal(findings[0].fixHint, 'User.objects.filter(active=True)');
  assert.deepEqual(findings[0].args, { qs: 'User.objects.filter(active=True)' });
});

test('DOL007 flags FK attribute access inside a for-loop', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'for user in User.objects.all():',
    '    print(user.profile)',
    '    print(user.email)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  // Only one finding per loop head (dedup behaviour of the heuristic).
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'unsafe');
  assert.equal(findings[0].args.qs, 'User.objects.all()');
});

test('DOL007 does not flag .pk / .id / .save / dunder', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'for user in qs:',
    '    ids.append(user.pk)',
    '    user.save()',
    '    print(user._meta)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL007 does not flag UPPER_SNAKE class-constant access (issue #72)', () => {
  const rule = ruleByCode('DOL007');
  // Loop iterates over model *classes* (apps.get_models()), so
  // model.ANONYMISE_AFTER is an in-memory class-constant lookup, not a query.
  const src = [
    'for model in auditory_models():',
    '    if model.ANONYMISE_AFTER is None:',
    '        continue',
    '    sweep(model)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL007 still flags a real N+1 alongside a class-constant access', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'for user in User.objects.all():',
    '    print(user.DEFAULT_ROLE)',
    '    print(user.profile)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'profile');
});

test('DOL007 stops scanning at outdent', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'for user in qs:',
    '    pass',
    'other_var.profile',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});
