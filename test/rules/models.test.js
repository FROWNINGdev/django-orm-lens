const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { modelRules } = require('../../out/rules/models');

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
  const r = modelRules.find((r) => r.meta.code === code);
  assert.ok(r, `rule ${code} must exist`);
  return r;
}

test('DOL011 flags CharField(null=True)', () => {
  const rule = ruleByCode('DOL011');
  const findings = rule.check(
    makeCtx('name = models.CharField(max_length=100, null=True)'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.field, 'CharField');
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL011 flags TextField(null=True) too', () => {
  const rule = ruleByCode('DOL011');
  const findings = rule.check(makeCtx('bio = models.TextField(null=True)'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.field, 'TextField');
});

test('DOL011 leaves CharField without null=True alone', () => {
  const rule = ruleByCode('DOL011');
  const findings = rule.check(
    makeCtx('name = models.CharField(max_length=100, blank=True)'),
  );
  assert.equal(findings.length, 0);
});

test('DOL012 flags a Model class with no __str__', () => {
  const rule = ruleByCode('DOL012');
  const src = [
    'class Author(models.Model):',
    '    name = models.CharField(max_length=100)',
    '    email = models.EmailField()',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.name, 'Author');
});

test('DOL012 does not flag models with __str__', () => {
  const rule = ruleByCode('DOL012');
  const src = [
    'class Author(models.Model):',
    '    name = models.CharField(max_length=100)',
    '    def __str__(self):',
    '        return self.name',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL012 skips abstract models', () => {
  const rule = ruleByCode('DOL012');
  const src = [
    'class Base(models.Model):',
    '    class Meta:',
    '        abstract = True',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL012 does not flag non-model classes', () => {
  const rule = ruleByCode('DOL012');
  const src = [
    'class NotAModel:',
    '    pass',
    '',
    'class AlsoNot(object):',
    '    pass',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.equal(findings.length, 0);
});

test('DOL013 flags ForeignKey without on_delete', () => {
  const rule = ruleByCode('DOL013');
  const findings = rule.check(
    makeCtx('author = models.ForeignKey(Author)'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL013 leaves ForeignKey with on_delete alone', () => {
  const rule = ruleByCode('DOL013');
  const findings = rule.check(
    makeCtx('author = models.ForeignKey(Author, on_delete=models.CASCADE)'),
  );
  assert.equal(findings.length, 0);
});

test('DOL014 flags CharField without max_length', () => {
  const rule = ruleByCode('DOL014');
  const findings = rule.check(makeCtx('nickname = models.CharField()'));
  assert.equal(findings.length, 1);
});

test('DOL014 leaves CharField with max_length alone', () => {
  const rule = ruleByCode('DOL014');
  const findings = rule.check(
    makeCtx('nickname = models.CharField(max_length=50)'),
  );
  assert.equal(findings.length, 0);
});

test('DOL015 flags TextField(max_length=X)', () => {
  const rule = ruleByCode('DOL015');
  const findings = rule.check(
    makeCtx('bio = models.TextField(max_length=1000)'),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].applicability, 'suggestion');
});

test('DOL015 leaves plain TextField alone', () => {
  const rule = ruleByCode('DOL015');
  const findings = rule.check(makeCtx('bio = models.TextField()'));
  assert.equal(findings.length, 0);
});
