const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const {
  completionsAt,
  parseQueryContext,
  lookupsForField,
  lookupPathLength,
  QUERY_METHODS,
} = require('../out/ormCompletions');

test.after(() => {
  Module._load = originalLoad;
});

const field = (name, type, over = {}) => ({
  name,
  type,
  args: '',
  isRelation: false,
  lineNumber: 1,
  ...over,
});

const fk = (name, relatedModel) =>
  field(name, 'ForeignKey', { isRelation: true, relatedModel, relationKind: 'ForeignKey' });

const model = (name, fields) => ({
  name,
  appName: 'blog',
  filePath: 'blog/models.py',
  lineNumber: 1,
  fields,
  meta: {},
  baseClasses: ['models.Model'],
});

const INDEX = {
  scannedAt: 0,
  apps: [
    {
      name: 'blog',
      path: 'blog',
      models: [
        model('Post', [
          field('title', 'CharField'),
          field('published', 'BooleanField'),
          field('created', 'DateTimeField'),
          field('views', 'IntegerField'),
          fk('author', 'Author'),
          fk('parent', 'self'),
        ]),
        model('Author', [field('name', 'CharField'), field('email', 'EmailField')]),
      ],
    },
  ],
};

const labels = (line) => completionsAt(line, INDEX).map((s) => s.label);

// --- context detection -----------------------------------------------------

test('resolves the model and method from a literal manager call', () => {
  const ctx = parseQueryContext('    qs = Post.objects.filter(');
  assert.deepEqual(ctx, { model: 'Post', method: 'filter', partial: '' });
});

test('reads the partial token being typed', () => {
  assert.equal(parseQueryContext('Post.objects.filter(auth').partial, 'auth');
});

test('a second kwarg after a complete one is still in scope', () => {
  const ctx = parseQueryContext("Post.objects.filter(title__icontains='x', auth");
  assert.equal(ctx.partial, 'auth');
});

test('a chained call resolves to the model that started the chain', () => {
  const ctx = parseQueryContext('Post.objects.filter(published=True).exclude(ti');
  assert.deepEqual(ctx, { model: 'Post', method: 'exclude', partial: 'ti' });
});

test('steps out of a Q() wrapper to find the naming call', () => {
  const ctx = parseQueryContext('Post.objects.filter(Q(auth');
  assert.deepEqual(ctx, { model: 'Post', method: 'filter', partial: 'auth' });
});

test('order_by strips the descending marker and the quote', () => {
  assert.equal(parseQueryContext("Post.objects.order_by('-crea").partial, 'crea');
});

// The value side is where a field list is actively wrong: offering `title`
// after `title=` would insert a bare name where a value belongs.
test('typing a value offers nothing', () => {
  assert.equal(parseQueryContext('Post.objects.filter(title='), null);
  assert.deepEqual(labels("Post.objects.filter(title='"), []);
});

test('outside any call there is no context', () => {
  assert.equal(parseQueryContext('qs = Post.objects.all()'), null);
  assert.equal(parseQueryContext('x = 1'), null);
});

test('a non-manager call is not a query context', () => {
  assert.equal(parseQueryContext('print(so'), null);
  assert.equal(parseQueryContext('Post.objects.bogus_method(ti'), null);
});

test('parens inside a string do not open a context', () => {
  assert.equal(parseQueryContext("label = 'filter(' + x"), null);
});

test('every advertised method parses', () => {
  for (const method of QUERY_METHODS) {
    assert.ok(
      parseQueryContext(`Post.objects.${method}(`),
      `${method} should be a query context`
    );
  }
});

// --- suggestions -----------------------------------------------------------

test('an empty call offers every declared field plus pk', () => {
  const got = labels('Post.objects.filter(');
  for (const name of ['title', 'published', 'created', 'views', 'author', 'parent', 'pk']) {
    assert.ok(got.includes(name), `missing ${name}: ${got.join(', ')}`);
  }
});

test('a partial token filters case-insensitively', () => {
  assert.deepEqual(labels('Post.objects.filter(TI'), ['title']);
});

test('an unknown model offers nothing rather than other fields', () => {
  assert.deepEqual(labels('Ghost.objects.filter(ti'), []);
});

test('traversing a FK offers the related model fields', () => {
  const got = labels('Post.objects.filter(author__');
  assert.ok(got.includes('author__name'), got.join(', '));
  assert.ok(got.includes('author__email'), got.join(', '));
  assert.ok(!got.includes('author__title'), 'Post fields must not leak across the edge');
});

test('a self-referential FK resolves back to its own model', () => {
  const got = labels('Post.objects.filter(parent__');
  assert.ok(got.includes('parent__title'), got.join(', '));
  assert.ok(got.includes('parent__parent'), got.join(', '));
});

test('traversal composes across two edges', () => {
  assert.ok(labels('Post.objects.filter(parent__author__').includes('parent__author__name'));
});

test('a relation also offers relation lookups', () => {
  const got = labels('Post.objects.filter(author__');
  assert.ok(got.includes('author__isnull'), got.join(', '));
  assert.ok(got.includes('author__in'), got.join(', '));
});

test('a completed lookup is a dead end, not a wrong list', () => {
  assert.deepEqual(labels('Post.objects.filter(title__icontains__'), []);
});

// --- lookups by field type -------------------------------------------------

test('text fields offer the text lookups', () => {
  const got = lookupsForField(field('title', 'CharField'));
  for (const l of ['icontains', 'istartswith', 'iexact', 'exact', 'in', 'isnull']) {
    assert.ok(got.includes(l), `${l} missing from ${got.join(', ')}`);
  }
  assert.ok(!got.includes('gt'), 'ordered lookups do not belong on CharField');
});

test('numeric fields offer the ordered lookups and not the text ones', () => {
  const got = lookupsForField(field('views', 'IntegerField'));
  assert.ok(got.includes('gte') && got.includes('range'));
  assert.ok(!got.includes('icontains'));
});

test('datetime fields offer both date and time parts', () => {
  const got = lookupsForField(field('created', 'DateTimeField'));
  for (const l of ['year', 'month', 'hour', 'date', 'gt']) {
    assert.ok(got.includes(l), `${l} missing from ${got.join(', ')}`);
  }
});

test('boolean fields stay at exact/in/isnull', () => {
  assert.deepEqual(lookupsForField(field('published', 'BooleanField')), [
    'exact',
    'in',
    'isnull',
  ]);
});

test('a text lookup is reachable through the completion path', () => {
  assert.ok(labels('Post.objects.filter(title__ic').includes('title__icontains'));
});

test('relations sort after plain fields', () => {
  const groups = completionsAt('Post.objects.filter(', INDEX).reduce((acc, s) => {
    acc[s.kind] = s.sortGroup;
    return acc;
  }, {});
  assert.ok(groups.field < groups.relation, 'plain fields sort first');
});

// --- resolving through an assignment chain (#83) ---------------------------

const ctxWith = (lines, prefix) => parseQueryContext(prefix, lines);

test('a queryset bound to a name resolves to its model', () => {
  const ctx = ctxWith(['qs = Post.objects.all()'], 'qs = qs.filter(ti');
  assert.deepEqual(ctx, { model: 'Post', method: 'filter', partial: 'ti' });
});

test('suggestions come through the bound name, not just the context', () => {
  const got = completionsAt('qs.filter(auth', INDEX, ['qs = Post.objects.all()']);
  assert.deepEqual(got.map((s) => s.label), ['author']);
});

test('traversal works through a bound name', () => {
  const got = completionsAt('qs.filter(author__na', INDEX, ['qs = Post.objects.all()']);
  assert.deepEqual(got.map((s) => s.label), ['author__name']);
});

test('a rebinding chain is followed back to the model', () => {
  const lines = [
    'qs = Post.objects.all()',
    'if flag:',
    '    qs = qs.exclude(published=False)',
  ];
  assert.equal(ctxWith(lines, 'qs = qs.filter(ti').model, 'Post');
});

// The nearest binding is the one in effect. An older binding of the same name
// is dead code as far as the cursor is concerned.
test('the nearest binding wins over an earlier one', () => {
  const lines = ['qs = Author.objects.all()', 'qs = Post.objects.all()'];
  assert.equal(ctxWith(lines, 'qs.filter(ti').model, 'Post');
});

// The important half. Falling through to the older binding here would answer
// with a model the code no longer holds.
test('a binding from something unrecognised poisons the lookup', () => {
  const lines = ['qs = Post.objects.all()', 'qs = build_queryset(request)'];
  assert.equal(ctxWith(lines, 'qs.filter(ti'), null);
  assert.deepEqual(completionsAt('qs.filter(ti', INDEX, lines), []);
});

test('a binding on the far side of a def is a different variable', () => {
  const lines = ['qs = Post.objects.all()', '', 'def other(request):'];
  assert.equal(ctxWith(lines, '    qs.filter(ti'), null);
});

test('a class body is a scope boundary too', () => {
  const lines = ['qs = Post.objects.all()', 'class Thing:'];
  assert.equal(ctxWith(lines, '    qs.filter(ti'), null);
});

test('an unbound name resolves to nothing', () => {
  assert.equal(ctxWith(['x = 1'], 'qs.filter(ti'), null);
  assert.equal(ctxWith([], 'qs.filter(ti'), null);
});

test('a dotted receiver is not treated as a local queryset name', () => {
  // `self.qs` is not the local `qs`, however tempting the trailing name looks.
  assert.equal(ctxWith(['qs = Post.objects.all()'], 'self.qs.filter(ti'), null);
});

test('the literal form still wins without any preceding lines', () => {
  assert.equal(parseQueryContext('Post.objects.filter(ti').model, 'Post');
});

test('a self-rebinding does not hang', () => {
  // `qs = qs.filter(...)` with no origin above it must terminate, not recurse.
  assert.equal(ctxWith(['qs = qs.filter(x=1)'], 'qs.filter(ti'), null);
});

// --- the replace range ----------------------------------------------------
//
// Accepting a suggestion has to consume the whole path already typed. VS
// Code's own word range stops at the last `__`, which would turn accepting
// `author__name` after typing `author__na` into `author__author__name`.

test('the replaced span covers the whole lookup path, not the last segment', () => {
  assert.equal(lookupPathLength('Post.objects.filter(author__na'), 'author__na'.length);
});

test('an empty call replaces nothing', () => {
  assert.equal(lookupPathLength('Post.objects.filter('), 0);
});

test('a path after a comma starts at the path, not at the comma', () => {
  const line = "Post.objects.filter(published=True, author__na";
  assert.equal(lookupPathLength(line), 'author__na'.length);
});

test('the span and the label agree, so accepting is idempotent', () => {
  const line = 'Post.objects.filter(author__na';
  const span = lookupPathLength(line);
  const chosen = completionsAt(line, INDEX).find((s) => s.label === 'author__name');
  assert.ok(chosen, 'author__name should be offered');
  const applied = line.slice(0, line.length - span) + chosen.label;
  assert.equal(applied, 'Post.objects.filter(author__name');
});

test('a relation suggestion names its target model', () => {
  const author = completionsAt('Post.objects.filter(author', INDEX).find(
    (s) => s.label === 'author'
  );
  assert.equal(author.kind, 'relation');
  assert.equal(author.detail, 'ForeignKey → Author');
});
