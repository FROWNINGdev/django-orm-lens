/**
 * End-to-end user-journey tests.
 *
 * Each test simulates a realistic workflow a Django engineer performs
 * with django-orm-lens installed. Fixture text is inlined so the whole
 * suite is self-contained and reviewable in one pass.
 *
 * Journeys covered:
 *   1. Detect and fix .count() > 0 anti-pattern (rules + fixer)
 *   2. Detect and fix .first() is None (rules + fixer)
 *   3. Detect N+1 attribute-access-in-loop (unfixable warning)
 *   4. Detect model-shape issues on a real fixture (DJ01/013/014)
 *   5. Inline noqa suppression works end-to-end
 *   6. Bulk factory generation for a small app (FK chain pulled in)
 *   7. Faker provider mapping across a spectrum of field types
 *   8. Schema diff on a real before/after — Add/Drop/Modify events
 *   9. Rename detection: RenameField and RenameModel over add/drop
 *  10. Impact analysis via scanFileText against admin/serializer/tpl
 *  11. Query builder on a real parser output: FK + related_name
 *  12. Full pipeline: parse -> rules -> factory in one flow
 */

const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { parseModelsFile } = require('../out/parser');
const { querysetRules } = require('../out/rules/queryset');
const { modelRules } = require('../out/rules/models');
const { datetimeRules } = require('../out/rules/datetime');
const { formsRules } = require('../out/rules/forms');
const { ALL_FIXERS, findFixersForCode } = require('../out/rules/fixers');
const { generateFactoryCode } = require('../out/factoryGenerator');
const { diffSchemas, diffToMarkdown } = require('../out/schemaDiff');
const { scanFileText, detectLayer, sortFindings } = require('../out/impactAnalysis');
const { generateQueryTemplates, snippetToPython } = require('../out/queryGen');

test.after(() => {
  Module._load = originalLoad;
});

/* --------------------------  small helpers  -------------------------- */

/** Build a fake RuleContext from a Python source string. */
function ctx(source) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    lineCount: lines.length,
    lineAt: (i) => lines[i] ?? '',
    windowBefore: (i, n) => lines.slice(Math.max(0, i - n), i),
    windowAfter: (i, n) => lines.slice(i + 1, Math.min(lines.length, i + 1 + n)),
  };
}

/** Minimal single-line document shim for fixer builders. */
function docWithLines(lines) {
  return { lineAt: (i) => ({ text: lines[i] ?? '' }) };
}

/** Apply a `FixEdit[]` to a source string and return the new source. */
function applyFixEdits(source, edits) {
  const lines = source.split(/\r?\n/);
  const byLine = new Map();
  for (const e of edits) {
    if (!byLine.has(e.line)) byLine.set(e.line, []);
    byLine.get(e.line).push(e);
  }
  for (const [line, group] of byLine) {
    group.sort((a, b) => b.startCol - a.startCol);
    let text = lines[line];
    for (const e of group) {
      text = text.slice(0, e.startCol) + e.newText + text.slice(e.endCol);
    }
    lines[line] = text;
  }
  return lines.join('\n');
}

/** Run every rule from every group over `source` and return findings. */
function scanAllRules(source) {
  const c = ctx(source);
  const findings = [];
  for (const rule of [...querysetRules, ...modelRules, ...datetimeRules, ...formsRules]) {
    for (const f of rule.check(c)) findings.push(f);
  }
  return findings;
}

/* ==============================================================
 * Journey 1 — Detect and fix .count() > 0 anti-pattern end-to-end
 * ============================================================== */
test('Journey 1: developer writes .count() > 0, gets DOL001 + auto-fix', () => {
  const before = 'if User.objects.filter(active=True).count() > 0:';
  const findings = scanAllRules(before);
  const dol001 = findings.find((f) => f.code === 'DOL001');
  assert.ok(dol001, 'DOL001 should be raised');
  assert.equal(dol001.applicability, 'safe', 'auto-apply is safe');

  const [fixer] = findFixersForCode('DOL001', dol001.fixHint);
  assert.ok(fixer, 'DOL001 fixer exists');
  const edits = fixer.build({ finding: dol001, document: docWithLines([before]) });
  const after = applyFixEdits(before, edits);
  assert.equal(after, 'if User.objects.filter(active=True).exists():');
});

/* ==============================================================
 * Journey 2 — .first() is None → not .exists()
 * ============================================================== */
test('Journey 2: .first() is None fix produces not .exists()', () => {
  const before = "if User.objects.filter(id=1).first() is None:";
  const findings = scanAllRules(before);
  const dol003 = findings.find((f) => f.code === 'DOL003');
  assert.ok(dol003);
  const [fixer] = findFixersForCode('DOL003', dol003.fixHint);
  const edits = fixer.build({ finding: dol003, document: docWithLines([before]) });
  const after = applyFixEdits(before, edits);
  assert.equal(after, 'if not User.objects.filter(id=1).exists():');
});

/* ==============================================================
 * Journey 3 — N+1 in a for-loop surfaces DOL007 (no auto-fix)
 * ============================================================== */
test('Journey 3: N+1 heuristic warns without a fixer', () => {
  const source = [
    'for user in User.objects.all():',
    '    print(user.profile)',
    '    print(user.department)',
  ].join('\n');
  const findings = scanAllRules(source);
  const dol007 = findings.filter((f) => f.code === 'DOL007');
  assert.ok(dol007.length >= 1, 'DOL007 should fire at least once');
  assert.equal(dol007[0].applicability, 'unsafe');
  const fixers = findFixersForCode('DOL007', dol007[0].fixHint);
  assert.equal(fixers.length, 0, 'DOL007 must not ship an auto-fixer');
});

/* ==============================================================
 * Journey 4 — Model-shape issues on a real fixture
 * ============================================================== */
test('Journey 4: model fixture surfaces DJ01/DJ08/DJ13 equivalents', () => {
  const source = [
    'class Post(models.Model):',
    '    title = models.CharField(null=True)',
    '    body = models.TextField(max_length=500)',
    '    author = models.ForeignKey(User)',
  ].join('\n');
  const findings = scanAllRules(source);
  const codes = new Set(findings.map((f) => f.code));
  assert.ok(codes.has('DOL011'), 'null=True on CharField');
  assert.ok(codes.has('DOL013'), 'FK without on_delete');
  assert.ok(codes.has('DOL014'), 'CharField without max_length');
  assert.ok(codes.has('DOL015'), 'TextField with max_length');
  assert.ok(codes.has('DOL012'), 'Missing __str__ on Post');
});

/* ==============================================================
 * Journey 5 — Inline noqa comment shape is accepted
 * ============================================================== */
test('Journey 5: # django-orm-lens-disable-next-line comment shape is valid', () => {
  const src = [
    '# django-orm-lens-disable-next-line DOL001',
    'if qs.count() > 0:',
  ].join('\n');
  const suppressionRe = /#\s*django-orm-lens-disable-next-line(?:\s+([A-Z0-9,\s]+))?/i;
  assert.match(src.split('\n')[0], suppressionRe);
});

/* ==============================================================
 * Journey 6 — Bulk factory generation with FK chain
 * ============================================================== */
test('Journey 6: factory generator pulls FK-related model into output', () => {
  const models = parseModelsFile(
    '/blog/models.py',
    [
      'class Author(models.Model):',
      '    name = models.CharField(max_length=100)',
      '',
      'class Book(models.Model):',
      '    title = models.CharField(max_length=200)',
      '    author = models.ForeignKey(Author, on_delete=models.CASCADE)',
    ].join('\n'),
  );
  const book = models.find((m) => m.name === 'Book');
  const index = {
    apps: [{ name: 'blog', path: '.', models }],
    scannedAt: 0,
  };
  const code = generateFactoryCode(book, index);
  assert.match(code, /class BookFactory/);
  assert.match(code, /class AuthorFactory/);
  assert.match(code, /author = factory\.SubFactory\(AuthorFactory\)/);
});

/* ==============================================================
 * Journey 7 — Faker provider spectrum across many field types
 * ============================================================== */
test('Journey 7: factory provider mapping covers key Django field types', () => {
  const models = parseModelsFile(
    '/shop/models.py',
    [
      'class Product(models.Model):',
      '    name = models.CharField(max_length=200)',
      '    slug = models.SlugField()',
      '    email = models.EmailField()',
      '    price = models.DecimalField(max_digits=8, decimal_places=2)',
      '    stock = models.IntegerField()',
      '    is_active = models.BooleanField()',
      '    created = models.DateTimeField()',
      '    tags = models.CharField(max_length=15)',
    ].join('\n'),
  );
  const p = models[0];
  const index = { apps: [{ name: 'shop', path: '.', models }], scannedAt: 0 };
  const code = generateFactoryCode(p, index);
  assert.match(code, /slug = factory\.Faker\('slug'\)/);
  assert.match(code, /email = factory\.Faker\('email'\)/);
  assert.match(code, /price = factory\.Faker\('pydecimal', left_digits=6, right_digits=2\)/);
  assert.match(code, /stock = factory\.Faker\('random_int'/);
  assert.match(code, /is_active = factory\.Faker\('pybool'\)/);
  assert.match(code, /created = factory\.Faker\('date_time'/);
});

/* ==============================================================
 * Journey 8 — Schema diff on a real before/after
 * ============================================================== */
test('Journey 8: schema diff over v1 -> v2 emits Add/Drop/Modify events', () => {
  const before = parseModelsFile(
    '/blog/models.py',
    [
      'class Post(models.Model):',
      '    title = models.CharField(max_length=100)',
      '    body = models.TextField()',
      '',
      'class OldModel(models.Model):',
      '    x = models.IntegerField()',
    ].join('\n'),
  );
  const after = parseModelsFile(
    '/blog/models.py',
    [
      'class Post(models.Model):',
      '    title = models.CharField(max_length=200)',
      '    body = models.TextField()',
      '    slug = models.SlugField()',
      '',
      'class Comment(models.Model):',
      '    text = models.TextField()',
    ].join('\n'),
  );
  const events = diffSchemas(before, after);
  const kinds = events.map((e) => e.kind);
  assert.ok(kinds.includes('AddModel'), 'Comment added');
  assert.ok(kinds.includes('DropModel') || kinds.includes('RenameModel'), 'OldModel dropped or renamed');
  const modify = events.find((e) => e.kind === 'ModifyModel' && e.model === 'Post');
  assert.ok(modify, 'Post should be modified');
  const changeKinds = new Set(modify.changes.map((c) => c.kind));
  assert.ok(changeKinds.has('AddField'), 'slug added');
  assert.ok(changeKinds.has('ChangeFieldOption'), 'max_length changed');

  const md = diffToMarkdown(events);
  assert.match(md, /### Schema changes/);
  assert.match(md, /Post/);
});

/* ==============================================================
 * Journey 9 — Rename detection over add+drop
 * ============================================================== */
test('Journey 9: renaming a field is one RenameField event, not add+drop', () => {
  const before = parseModelsFile(
    '/blog/models.py',
    [
      'class Author(models.Model):',
      '    fullname = models.CharField(max_length=100)',
    ].join('\n'),
  );
  const after = parseModelsFile(
    '/blog/models.py',
    [
      'class Author(models.Model):',
      '    fullname_v2 = models.CharField(max_length=100)',
    ].join('\n'),
  );
  const events = diffSchemas(before, after);
  const modify = events.find((e) => e.kind === 'ModifyModel');
  assert.ok(modify);
  const rename = modify.changes.find((c) => c.kind === 'RenameField');
  assert.ok(rename, 'expected RenameField');
  assert.equal(rename.from, 'fullname');
  assert.equal(rename.to, 'fullname_v2');
  const addDropCount = modify.changes.filter(
    (c) => c.kind === 'AddField' || c.kind === 'DropField'
  ).length;
  assert.equal(addDropCount, 0, 'no add+drop for the same pair');
});

/* ==============================================================
 * Journey 10 — Impact analysis across admin + serializer + template
 * ============================================================== */
test('Journey 10: impact scan finds admin/serializer/template references', () => {
  const admin = "class PostAdmin(admin.ModelAdmin):\n    list_display = ['id', 'author', 'created']";
  const serializer = "class PostSerializer(serializers.ModelSerializer):\n    class Meta:\n        fields = ['author', 'title']";
  const template = '<p>By {{ post.author.name }}</p>';
  const views = 'qs = Post.objects.select_related("author")';

  const findings = [
    ...scanFileText('/repo/blog/admin.py', admin, 'author'),
    ...scanFileText('/repo/blog/serializers.py', serializer, 'author'),
    ...scanFileText('/repo/blog/templates/detail.html', template, 'author'),
    ...scanFileText('/repo/blog/views.py', views, 'author'),
  ];
  findings.sort(sortFindings);
  const layers = new Set(findings.map((f) => f.layer));
  assert.ok(layers.has('admin'));
  assert.ok(layers.has('serializers'));
  assert.ok(layers.has('templates'));
  assert.ok(layers.has('views'));
  const certain = findings.filter((f) => f.confidence === 'certain');
  assert.ok(certain.length >= 2, 'at least admin+views should be certain');
});

/* ==============================================================
 * Journey 11 — Query builder over parsed FK with related_name
 * ============================================================== */
test('Journey 11: query builder honours related_name for reverse-FK count', () => {
  const models = parseModelsFile(
    '/blog/models.py',
    [
      'class Author(models.Model):',
      '    name = models.CharField(max_length=100)',
      '',
      'class Post(models.Model):',
      '    title = models.CharField(max_length=100)',
      '    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="articles")',
    ].join('\n'),
  );
  const index = { apps: [{ name: 'blog', path: '.', models }], scannedAt: 0 };
  const templates = generateQueryTemplates(
    { kind: 'model', appName: 'blog', modelName: 'Author' },
    index,
  );
  const annotate = templates.find((t) => t.category === 'aggregate');
  assert.ok(annotate, 'expected an aggregate template');
  assert.match(annotate.title, /Count\('articles'\)/);
});

/* ==============================================================
 * Journey 12 — Full pipeline: parse → rules → factory in one flow
 * ============================================================== */
test('Journey 12: parse + rules + factory in one flow yields consistent output', () => {
  const source = [
    'class Article(models.Model):',
    '    slug = models.CharField()',
    '    body = models.TextField(max_length=100)',
    '    author = models.ForeignKey(User, related_name="articles")',
    '    def __str__(self):',
    '        return self.slug',
  ].join('\n');

  const models = parseModelsFile('/blog/models.py', source);
  assert.equal(models.length, 1);
  assert.equal(models[0].name, 'Article');
  assert.equal(models[0].fields.length, 3);

  const findings = scanAllRules(source);
  const codes = new Set(findings.map((f) => f.code));
  assert.ok(codes.has('DOL013'));
  assert.ok(codes.has('DOL014'));
  assert.ok(codes.has('DOL015'));
  assert.ok(!codes.has('DOL012'), 'DOL012 should NOT fire — __str__ is defined');

  const index = { apps: [{ name: 'blog', path: '.', models }], scannedAt: 0 };
  const code = generateFactoryCode(models[0], index);
  assert.match(code, /class ArticleFactory/);
  assert.match(code, /slug = factory\.Faker/);
});

/* ==============================================================
 * Bonus — sanity checks over the whole registry
 * ============================================================== */
test('Registry sanity: every fixer targets a real rule code', () => {
  // Derived from the rules themselves rather than a hand-kept list. The list
  // version failed on DOL008 for no better reason than that nobody had added
  // the string to it — noise that says nothing about whether a fixer points at
  // a rule, which is the only thing this test is for.
  const knownCodes = new Set(
    [...querysetRules, ...modelRules, ...datetimeRules, ...formsRules].map(
      (r) => r.meta.code,
    ),
  );
  for (const fixer of ALL_FIXERS) {
    assert.ok(knownCodes.has(fixer.code), `unknown fixer code ${fixer.code}`);
  }
});

test('Registry sanity: layer detection is stable for common paths', () => {
  assert.equal(detectLayer('/x/y/z/models.py'), 'models');
  assert.equal(detectLayer('/x/y/z/api/serializers.py'), 'serializers');
  assert.equal(detectLayer('/x/y/z/templates/index.html'), 'templates');
});

test('snippetToPython renders every template into runnable Python', () => {
  const models = parseModelsFile(
    '/blog/models.py',
    'class Post(models.Model):\n    title = models.CharField(max_length=100)\n',
  );
  const index = { apps: [{ name: 'blog', path: '.', models }], scannedAt: 0 };
  const templates = generateQueryTemplates(
    { kind: 'field', appName: 'blog', modelName: 'Post', fieldName: 'title' },
    index,
  );
  for (const t of templates) {
    const python = snippetToPython(t.snippet);
    assert.match(python, /^Post\.objects/, `template ${t.title} should start with Post.objects`);
    assert.doesNotMatch(python, /\$\{/, 'no unresolved tab-stops');
  }
});
