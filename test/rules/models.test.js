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

test('DOL013 accepts a positional on_delete, as Django contrib writes it', () => {
  // ForeignKey(to, on_delete, ...). Flagging it was an error-severity false
  // positive, and the fixer then added a duplicate on_delete= that raises.
  const rule = ruleByCode('DOL013');
  for (const src of [
    'order = models.ForeignKey(Order, models.CASCADE)',
    'user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, verbose_name="user")',
    'ct = models.ForeignKey(ContentType, my_policy, related_name="x")',
  ]) {
    assert.equal(rule.check(makeCtx(src)).length, 0, src);
  }
});

test('DOL013 still flags one positional plus keywords', () => {
  const rule = ruleByCode('DOL013');
  for (const src of [
    "author = models.ForeignKey(Author, related_name='books')",
    'author = models.ForeignKey("a, b", null=True)',
    'author = models.ForeignKey(to=Author)',
  ]) {
    assert.equal(rule.check(makeCtx(src)).length, 1, src);
  }
});

test('DOL013 reads past nested calls in the arguments (#182)', () => {
  const rule = ruleByCode('DOL013');
  for (const src of [
    'author = models.ForeignKey(Author, verbose_name=_("author"))',
    'author = models.ForeignKey(Author, default=get_default_author())',
    // The comma sits inside a nested call, so it is not a second positional.
    'author = models.ForeignKey(Author, help_text=_("a, b"))',
    // A `)` inside a string doesn't close the call early.
    'author = models.ForeignKey(Author, help_text=_("a) b"))',
  ]) {
    assert.equal(rule.check(makeCtx(src)).length, 1, src);
  }
  for (const src of [
    'author = models.ForeignKey(Author, models.CASCADE, verbose_name=_("author"))',
    'author = models.ForeignKey(Author, on_delete=models.CASCADE, verbose_name=_("author"))',
  ]) {
    assert.equal(rule.check(makeCtx(src)).length, 0, src);
  }
});

test('DOL013 range ends at the matching paren, so the fixer edits the right spot', () => {
  const rule = ruleByCode('DOL013');
  const src = 'author = models.ForeignKey(Author, verbose_name=_("author"))  # note';
  const [finding] = rule.check(makeCtx(src));
  assert.equal(
    src.slice(finding.range.startCol, finding.range.endCol),
    'models.ForeignKey(Author, verbose_name=_("author"))',
  );
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
