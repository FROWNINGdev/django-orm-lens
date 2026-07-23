const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const {
  generateQueryTemplates,
  snippetToPython,
} = require('../out/queryGen');

test.after(() => {
  Module._load = originalLoad;
});

function field(name, type, extra = {}) {
  return {
    name,
    type,
    args: extra.args ?? '',
    isRelation: !!extra.isRelation,
    relatedModel: extra.relatedModel,
    relationKind: extra.relationKind,
    onDelete: extra.onDelete,
    relatedName: extra.relatedName,
    throughModel: extra.throughModel,
    lineNumber: 1,
  };
}

function model(appName, name, fields) {
  return {
    name,
    appName,
    filePath: `/${appName}/models.py`,
    lineNumber: 1,
    fields,
    meta: {},
    baseClasses: ['models.Model'],
  };
}

function indexOf(...models) {
  const byApp = new Map();
  for (const m of models) {
    if (!byApp.has(m.appName)) byApp.set(m.appName, { name: m.appName, path: '.', models: [] });
    byApp.get(m.appName).models.push(m);
  }
  return { apps: [...byApp.values()], scannedAt: 0 };
}

test('field kind: scalar produces filter + distinct + only', () => {
  const post = model('blog', 'Post', [field('title', 'CharField', { args: 'max_length=200' })]);
  const templates = generateQueryTemplates(
    { kind: 'field', appName: 'blog', modelName: 'Post', fieldName: 'title' },
    indexOf(post),
  );
  const titles = templates.map((t) => t.title);
  assert.ok(titles.some((t) => t.startsWith('.filter(title=')));
  assert.ok(titles.some((t) => t.includes(".values('title').distinct()")));
  assert.ok(titles.some((t) => t.includes(".only('title')")));
});

test('FK field: filter template auto-adds .select_related', () => {
  const author = model('blog', 'Author', [field('name', 'CharField')]);
  const post = model('blog', 'Post', [
    field('author', 'ForeignKey', {
      isRelation: true,
      relatedModel: 'Author',
      relationKind: 'ForeignKey',
    }),
  ]);
  const [filterT] = generateQueryTemplates(
    { kind: 'field', appName: 'blog', modelName: 'Post', fieldName: 'author' },
    indexOf(author, post),
  );
  assert.match(filterT.snippet, /\.filter\(author=.*\)\.select_related\('author'\)/);
});

test('FK field: also produces a standalone .select_related template', () => {
  const author = model('blog', 'Author', [field('name', 'CharField')]);
  const post = model('blog', 'Post', [
    field('author', 'ForeignKey', {
      isRelation: true,
      relatedModel: 'Author',
      relationKind: 'ForeignKey',
    }),
  ]);
  const templates = generateQueryTemplates(
    { kind: 'field', appName: 'blog', modelName: 'Post', fieldName: 'author' },
    indexOf(author, post),
  );
  assert.ok(
    templates.some((t) => t.title === ".select_related('author')"),
    'expected a standalone select_related template',
  );
});

test('M2M field: produces .prefetch_related, not .select_related', () => {
  const tag = model('blog', 'Tag', [field('name', 'CharField')]);
  const post = model('blog', 'Post', [
    field('tags', 'ManyToManyField', {
      isRelation: true,
      relatedModel: 'Tag',
      relationKind: 'ManyToManyField',
    }),
  ]);
  const templates = generateQueryTemplates(
    { kind: 'field', appName: 'blog', modelName: 'Post', fieldName: 'tags' },
    indexOf(tag, post),
  );
  assert.ok(templates.some((t) => t.title === ".prefetch_related('tags')"));
  assert.ok(!templates.some((t) => t.title === ".select_related('tags')"));
});

test('model kind: reverse-FK triggers annotate(Count(...))', () => {
  const author = model('blog', 'Author', [field('name', 'CharField')]);
  const post = model('blog', 'Post', [
    field('author', 'ForeignKey', {
      isRelation: true,
      relatedModel: 'Author',
      relationKind: 'ForeignKey',
    }),
  ]);
  const templates = generateQueryTemplates(
    { kind: 'model', appName: 'blog', modelName: 'Author' },
    indexOf(author, post),
  );
  assert.ok(
    templates.some((t) => t.title.includes("Count('post_set')")),
    'expected reverse-FK count annotation via post_set',
  );
});

test('reverse accessor honours related_name', () => {
  const author = model('blog', 'Author', [field('name', 'CharField')]);
  const post = model('blog', 'Post', [
    field('author', 'ForeignKey', {
      isRelation: true,
      relatedModel: 'Author',
      relationKind: 'ForeignKey',
      relatedName: 'articles',
    }),
  ]);
  const templates = generateQueryTemplates(
    { kind: 'model', appName: 'blog', modelName: 'Author' },
    indexOf(author, post),
  );
  assert.ok(
    templates.some((t) => t.title.includes("Count('articles')")),
    'expected reverse accessor to use related_name="articles"',
  );
});

test('snippetToPython resolves ${1:value} placeholders', () => {
  const rendered = snippetToPython(
    "Post.objects.filter(title=${1:value}).select_related('author')",
  );
  assert.equal(rendered, "Post.objects.filter(title=value).select_related('author')");
});

test('unknown model returns no templates instead of throwing', () => {
  const templates = generateQueryTemplates(
    { kind: 'model', appName: 'blog', modelName: 'DoesNotExist' },
    indexOf(),
  );
  assert.deepEqual(templates, []);
});
