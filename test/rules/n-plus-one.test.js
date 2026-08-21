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

/**
 * DOL007 against a parsed workspace — the half `queryset.test.js` cannot
 * cover, because its `makeCtx` builds a context with no `index`.
 *
 * That split is the point rather than an accident. Issue #85 reported four
 * loops the rule flagged in the extension but the CLI left alone, and all
 * four turn on what the schema says: a declared column, a property the schema
 * has never heard of, and a foreign key the same statement already spans.
 * None of them can be judged from line shape, so none of them can be tested
 * without an index.
 */

/** Build a `RuleContext` from a source string, optionally with a schema. */
function makeCtx(source, index) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    index,
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

/** One entry shaped like `ParsedField`. */
function field(name, type, extra = {}) {
  return { name, type, args: '', isRelation: false, lineNumber: 1, ...extra };
}

function fk(name, relatedModel, extra = {}) {
  return field(name, 'ForeignKey', {
    isRelation: true,
    relationKind: 'ForeignKey',
    relatedModel,
    ...extra,
  });
}

function model(name, fields, inheritedFields = []) {
  return {
    name,
    appName: 'core',
    filePath: `core/models/${name.toLowerCase()}.py`,
    lineNumber: 1,
    fields,
    inheritedFields,
    meta: {},
    baseClasses: [],
  };
}

/**
 * The reporter's schema, minimised.
 *
 * `Consent.is_deleted` is deliberately absent: it is a Python property on an
 * abstract base, not a column, so the schema genuinely does not declare it.
 * That absence *is* the case-3 input — the rule has to read "not declared on
 * a model I know" as "not a query", which is the same call the CLI makes.
 */
const REPORTER_INDEX = {
  scannedAt: 0,
  apps: [
    {
      name: 'core',
      path: 'core',
      models: [
        model('OneTimeCode', [
          field('consumed_at', 'DateTimeField'),
          field('created_on', 'DateTimeField'),
          fk('issued_by', 'User'),
        ]),
        model('Membership', [field('roles', 'CharField'), fk('user', 'User')]),
        model('Consent', [fk('definition', 'ConsentDefinition')]),
        model('ConsentDefinition', [
          field('purpose', 'CharField'),
          field('published_at', 'DateTimeField'),
        ]),
        model('User', [field('email', 'EmailField')]),
      ],
    },
  ],
};

test('DOL007 case 1: a declared local column is not an N+1 (issue #85)', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'def case_1_local_field():',
    '    codes = list(OneTimeCode.objects.select_related("issued_by").order_by("-created_on"))',
    '    for code in codes:',
    '        print(code.consumed_at)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 case 2: an FK the chain already spans is not an N+1 (issue #85)', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'def case_2_covered_fk():',
    '    memberships = list(Membership.objects.select_related("user").order_by("roles"))',
    '    for m in memberships:',
    '        print(m.user)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 case 2 holds without a schema too (issue #85)', () => {
  // The coverage gate is pure string matching, so it survives a cold start.
  // This is the gate that stops the rule contradicting code that has already
  // taken its own advice, so it must not depend on a scan having finished.
  const rule = ruleByCode('DOL007');
  const src = [
    '    memberships = list(Membership.objects.select_related("user"))',
    '    for m in memberships:',
    '        print(m.user)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src)).length, 0);
});

test('DOL007 case 3: a property on an abstract base is not an N+1 (issue #85)', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'def case_3_property():',
    '    rows = list(Consent.objects.select_related("definition"))',
    '    for consent in rows:',
    '        print(consent.is_deleted)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 case 4: a column on an annotated queryset is not an N+1 (issue #85)', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    'def case_4_annotated():',
    '    definitions = list(',
    '        ConsentDefinition.objects.annotate(n=Count("consents")).order_by("purpose")',
    '    )',
    '    for definition in definitions:',
    '        print(definition.published_at)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 still flags an uncovered FK when the schema is present', () => {
  // The gates must not silence the rule wholesale — this is the true positive
  // that disabling DOL007 workspace-wide would have cost.
  const rule = ruleByCode('DOL007');
  const src = [
    '    memberships = Membership.objects.all()',
    '    for m in memberships:',
    '        print(m.user.email)',
  ].join('\n');
  const findings = rule.check(makeCtx(src, REPORTER_INDEX));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'user');
});

test('DOL007 flags an uncovered reverse manager', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    '    users = User.objects.all()',
    '    for u in users:',
    '        print(u.membership_set)',
  ].join('\n');
  const findings = rule.check(makeCtx(src, REPORTER_INDEX));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'membership_set');
});

test('DOL007 leaves a reverse manager alone once prefetched', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    '    users = User.objects.prefetch_related("membership_set")',
    '    for u in users:',
    '        print(u.membership_set)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 treats a bare .select_related() as spanning every FK', () => {
  const rule = ruleByCode('DOL007');
  const src = [
    '    memberships = Membership.objects.select_related()',
    '    for m in memberships:',
    '        print(m.user)',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 0);
});

test('DOL007 keeps its schema-free behaviour when the model is unknown', () => {
  // An index that does not contain the model must not be read as "the schema
  // says this is scalar" — a partial scan would otherwise silence real
  // findings, which is this change's own failure mode pointed the other way.
  const rule = ruleByCode('DOL007');
  const src = ['for row in Unknown.objects.all():', '    print(row.thing)'].join('\n');
  assert.equal(rule.check(makeCtx(src, REPORTER_INDEX)).length, 1);
});

test('DOL007 does not follow a binding across a scope boundary', () => {
  // A name bound inside another function is not the one this loop holds;
  // answering with a model the code no longer has would be confidently wrong.
  const rule = ruleByCode('DOL007');
  const src = [
    'def other():',
    '    rows = Membership.objects.select_related("user")',
    '',
    'def here(rows):',
    '    for m in rows:',
    '        print(m.user)',
  ].join('\n');
  const findings = rule.check(makeCtx(src, REPORTER_INDEX));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].fixHint, 'user');
});
