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

test('DOL007 does not flag a loop over model classes (issue #72)', () => {
  const rule = ruleByCode('DOL007');
  // `auditory_models()` returns model *classes*, so every attribute read on
  // the loop variable is an in-memory __mro__ lookup, not a query.
  const src = [
    'for model in auditory_models():',
    '    if model.ANONYMISE_AFTER is None:',
    '        continue',
    '    sweep(model)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL007 does not flag class-level access in a model-class loop', () => {
  const rule = ruleByCode('DOL007');
  // Every one of these is idiomatic on a model *class* and involves no
  // per-iteration query, so none of them is an N+1 (issue #72).
  const sources = [
    // The reporter's sweep, with the body its `...` elides.
    [
      'for model in auditory_models():',
      '    if model.ANONYMISE_AFTER is None:',
      '        continue',
      '    model.objects.filter(created__lt=cutoff).update(anonymised=True)',
    ],
    ['for model in apps.get_models():', '    print(model.Meta)'],
    [
      'for model in apps.get_models():',
      '    try:',
      '        handle(model)',
      '    except model.DoesNotExist:',
      '        pass',
    ],
  ];
  for (const lines of sources) {
    const findings = rule.check(makeCtx(lines.join('\n')));
    assert.equal(findings.length, 0, `expected no finding for: ${lines[0]}`);
  }
});

test('DOL007 flags an UPPER_CASE relation on a real queryset loop', () => {
  const rule = ruleByCode('DOL007');
  // Django permits uppercase field names, so the attribute's casing says
  // nothing about whether the access hits the database.
  const src = [
    'for order in Order.objects.all():',
    '    print(order.CUSTOMER.name)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'CUSTOMER');
});

test('DOL007 flags a single-uppercase-letter attribute on a queryset loop', () => {
  const rule = ruleByCode('DOL007');
  const src = ['for p in Point.objects.all():', '    print(p.X)'].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'X');
});

test('DOL007 does not flag loops over non-queryset call sources', () => {
  const rule = ruleByCode('DOL007');
  const sources = [
    ['for i in range(10):', '    print(i.bit_length())'],
    ['for name in os.listdir(path):', '    print(name.upper())'],
    ['for model in apps.get_models():', '    print(model.objects.count())'],
  ];
  for (const lines of sources) {
    const findings = rule.check(makeCtx(lines.join('\n')));
    assert.equal(findings.length, 0, `expected no finding for: ${lines[0]}`);
  }
});

test('DOL007 does not flag a helper-call loop source (issue #72 boundary)', () => {
  const rule = ruleByCode('DOL007');
  // A call name alone says nothing about what comes back, and a
  // line-oriented rule cannot follow a callee's return, so helper-call
  // sources stay out of scope. Pin the boundary so it cannot silently widen.
  const sources = [
    ['for p in recent():', '    print(p.author)'],
    ['for o in self.get_queryset():', '    print(o.author)'],
  ];
  for (const lines of sources) {
    const findings = rule.check(makeCtx(lines.join('\n')));
    assert.equal(findings.length, 0, `expected no finding for: ${lines[0]}`);
  }
});

test('DOL007 flags a queryset-producing chain off a variable', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'for user in qs.filter(active=True):',
    '    print(user.profile)',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'profile');
});

test('DOL007 recognises every queryset-producing method off a variable', () => {
  const rule = ruleByCode('DOL007');
  // Pin the whole set rather than one member of it: a chain rooted on a
  // variable is a queryset source for the same reason as one rooted on a
  // manager, so every method that returns a new QuerySet has to be listed
  // here or the loop over it is skipped silently.
  const methods = [
    'all',
    'filter',
    'exclude',
    'annotate',
    'alias',
    'order_by',
    'reverse',
    'distinct',
    'values',
    'values_list',
    'dates',
    'datetimes',
    'none',
    'union',
    'intersection',
    'difference',
    'select_related',
    'prefetch_related',
    'extra',
    'defer',
    'only',
    'using',
    'select_for_update',
    'raw',
  ];
  for (const method of methods) {
    const src = [
      `for post in qs.${method}("author"):`,
      '    print(post.author)',
    ].join('\n');
    const findings = rule.check(makeCtx(src));
    assert.equal(findings.length, 1, `expected a finding for: qs.${method}()`);
    assert.equal(findings[0].fixHint, 'author');
  }
});

test('DOL007 still flags a bare-name loop source', () => {
  const rule = ruleByCode('DOL007');
  // A bare name carries no evidence either way — `users = User.objects.all()`
  // is the common idiom — so the unrecognisable case keeps the old behaviour.
  const src = ['for user in users:', '    print(user.profile)'].join('\n');
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
