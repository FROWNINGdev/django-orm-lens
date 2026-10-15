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

function makeCtx(source, dbEngine) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    dbEngine,
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

test('DOL016 flags index_together and unique_together inside Meta', () => {
  const rule = ruleByCode('DOL016');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        index_together = [',
    '            ("company_id", "is_campus_event", "status"),',
    '            ("company_id", "end_dt"),',
    '        ]',
    '        unique_together = [("company_id", "status")]',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.deepEqual(
    findings.map((f) => f.args.option),
    ['index_together', 'unique_together'],
  );
  assert.equal(findings[0].applicability, 'unsafe');
  assert.equal(rule.meta.defaultSeverity, 'warning');
});

test('DOL016 flags Index and UniqueConstraint without name=', () => {
  const rule = ruleByCode('DOL016');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        indexes = [',
    '            models.Index(fields=["company_id", "status"]),',
    '            models.Index(',
    '                fields=["company_id", "end_dt"],',
    '            ),',
    '        ]',
    '        constraints = [',
    '            models.UniqueConstraint(fields=["company_id", "status"]),',
    '            models.CheckConstraint(check=models.Q(status__gte=0)),',
    '        ]',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.deepEqual(
    findings.map((f) => f.args.kind),
    ['Index', 'Index', 'UniqueConstraint', 'CheckConstraint'],
  );
});

test('DOL016 allows explicitly named indexes and constraints', () => {
  const rule = ruleByCode('DOL016');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        indexes = [',
    '            models.Index(',
    '                fields=["company_id", "is_campus_event", "status"],',
    '                name="idx_company_campus_status",',
    '            ),',
    '        ]',
    '        constraints = [',
    '            models.UniqueConstraint(',
    '                fields=["company_id", "status"],',
    '                condition=models.Q(name="active"),',
    '                name="uniq_company_status",',
    '            ),',
    '        ]',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src)).length, 0);
});

test('DOL017 renames an index and a unique constraint to the MySQL convention', () => {
  const rule = ruleByCode('DOL017');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        db_table = "ai_events"',
    '        indexes = [',
    '            models.Index(fields=["company_id", "status"], name="idx_event_status"),',
    '        ]',
    '        constraints = [',
    "            models.UniqueConstraint(fields=['company_id', 'status'], name='unique_event_status'),",
    '        ]',
  ].join('\n');
  const findings = rule.check(makeCtx(src));
  assert.deepEqual(
    findings.map((f) => [f.args.kind, f.args.name, f.args.recommended, f.fixHint]),
    [
      ['Index', 'idx_event_status', 'idx_events_company_status', '"idx_events_company_status"'],
      ['UniqueConstraint', 'unique_event_status', 'uniq_events_company_status', "'uniq_events_company_status'"],
    ],
  );
  assert.equal(findings[0].applicability, 'suggestion');
  assert.equal(rule.meta.defaultSeverity, 'warning');
});

test('DOL017 only runs for MySQL or an unknown engine', () => {
  const rule = ruleByCode('DOL017');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        db_table = "ai_events"',
    '        indexes = [',
    '            models.Index(fields=["company_id", "status"], name="idx_event_status"),',
    '        ]',
  ].join('\n');
  for (const engine of [undefined, 'auto', 'mysql']) {
    assert.equal(rule.check(makeCtx(src, engine)).length, 1, `engine ${engine}`);
  }
  for (const engine of ['postgres', 'sqlite']) {
    assert.deepEqual(rule.check(makeCtx(src, engine)), [], `engine ${engine}`);
  }
});

test('DOL017 accepts the conventional name and a uuid unique constraint', () => {
  const rule = ruleByCode('DOL017');
  const src = [
    'class Event(models.Model):',
    '    class Meta:',
    '        db_table = "ai_events"',
    '        indexes = [',
    '            models.Index(fields=["company_id", "status"], name="idx_events_company_status"),',
    '        ]',
    '        constraints = [',
    '            models.UniqueConstraint(fields=["uuid"], name="idx_uniq_ai_events"),',
    '        ]',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src)).length, 0);
});

test('DOL017 uses the app and model name when Meta has no db_table', () => {
  const rule = ruleByCode('DOL017');
  const ctx = makeCtx([
    'class Order(models.Model):',
    '    class Meta:',
    '        indexes = [',
    '            models.Index(fields=["user_id"], name="idx_user"),',
    '        ]',
  ].join('\n'));
  ctx.document = { uri: { fsPath: '/proj/shop/models.py' } };
  ctx.index = {
    apps: [{
      name: 'shop',
      path: '/proj/shop',
      models: [{ name: 'Order', filePath: '/proj/shop/models.py' }],
    }],
  };
  const findings = rule.check(ctx);
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.recommended, 'idx_shop_order_user');
});

test('DOL017 stays quiet without a table name and outside Meta', () => {
  const rule = ruleByCode('DOL017');
  assert.equal(
    rule.check(makeCtx(
      'class Event(models.Model):\n    class Meta:\n        indexes = [models.Index(fields=["company_id"], name="idx_x")]',
    )).length,
    0,
  );
  assert.equal(
    rule.check(makeCtx('models.Index(fields=["company_id"], name="idx_x")')).length,
    0,
  );
});

test('DOL016 ignores indexes declared outside class Meta', () => {
  const rule = ruleByCode('DOL016');
  const src = [
    'index_together = [("company_id", "status")]',
    'models.Index(fields=["company_id"])',
    'class NotMeta:',
    '    unique_together = [("company_id", "status")]',
  ].join('\n');
  assert.equal(rule.check(makeCtx(src)).length, 0);
});
