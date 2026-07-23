const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { generateFactoryCode } = require('../out/factoryGenerator');

test.after(() => {
  Module._load = originalLoad;
});

/** Minimal WorkspaceIndex builder for tests. */
function indexOf(...models) {
  const byApp = new Map();
  for (const m of models) {
    if (!byApp.has(m.appName)) byApp.set(m.appName, { name: m.appName, path: '.', models: [] });
    byApp.get(m.appName).models.push(m);
  }
  return { apps: [...byApp.values()], scannedAt: 0 };
}

test('emits DjangoModelFactory class with Faker providers per field type', () => {
  const model = {
    name: 'Author',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 3,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'name', type: 'CharField', args: 'max_length=100', isRelation: false, lineNumber: 4 },
      { name: 'email', type: 'EmailField', args: '', isRelation: false, lineNumber: 5 },
      { name: 'bio', type: 'TextField', args: '', isRelation: false, lineNumber: 6 },
      { name: 'active', type: 'BooleanField', args: 'default=True', isRelation: false, lineNumber: 7 },
    ],
  };
  const code = generateFactoryCode(model, indexOf(model));
  assert.match(code, /class AuthorFactory\(factory\.django\.DjangoModelFactory\):/);
  assert.match(code, /model = Author/);
  assert.match(code, /name = factory\.Faker\('sentence', nb_words=10\)/);
  assert.match(code, /email = factory\.Faker\('email'\)/);
  assert.match(code, /bio = factory\.Faker\('paragraph'\)/);
  assert.match(code, /active = factory\.Faker\('pybool'\)/);
});

test('CharField provider scales with max_length', () => {
  const model = {
    name: 'Tag',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'slug', type: 'CharField', args: 'max_length=15', isRelation: false, lineNumber: 2 },
      { name: 'title', type: 'CharField', args: 'max_length=60', isRelation: false, lineNumber: 3 },
      { name: 'summary', type: 'CharField', args: 'max_length=500', isRelation: false, lineNumber: 4 },
    ],
  };
  const code = generateFactoryCode(model, indexOf(model));
  assert.match(code, /slug = factory\.Faker\('word'\)/);
  assert.match(code, /title = factory\.Faker\('sentence', nb_words=4\)/);
  assert.match(code, /summary = factory\.Faker\('sentence', nb_words=10\)/);
});

test('DecimalField uses max_digits / decimal_places', () => {
  const model = {
    name: 'Product',
    appName: 'shop',
    filePath: '/shop/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'price', type: 'DecimalField', args: 'max_digits=8, decimal_places=2', isRelation: false, lineNumber: 2 },
    ],
  };
  const code = generateFactoryCode(model, indexOf(model));
  assert.match(code, /price = factory\.Faker\('pydecimal', left_digits=6, right_digits=2\)/);
});

test('emits SubFactory + pulls related model into output', () => {
  const author = {
    name: 'Author',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'name', type: 'CharField', args: 'max_length=100', isRelation: false, lineNumber: 2 },
    ],
  };
  const book = {
    name: 'Book',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 6,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'title', type: 'CharField', args: 'max_length=200', isRelation: false, lineNumber: 7 },
      {
        name: 'author',
        type: 'ForeignKey',
        args: 'Author, on_delete=models.CASCADE',
        isRelation: true,
        relatedModel: 'Author',
        relationKind: 'ForeignKey',
        onDelete: 'CASCADE',
        lineNumber: 8,
      },
    ],
  };
  const code = generateFactoryCode(book, indexOf(author, book));
  assert.match(code, /class BookFactory/);
  assert.match(code, /class AuthorFactory/);
  assert.match(code, /author = factory\.SubFactory\(AuthorFactory\)/);
});

test('AutoField / BigAutoField are skipped', () => {
  const model = {
    name: 'Thing',
    appName: 'app',
    filePath: '/app/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'id', type: 'BigAutoField', args: 'primary_key=True', isRelation: false, lineNumber: 2 },
      { name: 'name', type: 'CharField', args: 'max_length=10', isRelation: false, lineNumber: 3 },
    ],
  };
  const code = generateFactoryCode(model, indexOf(model));
  assert.doesNotMatch(code, /\bid = /);
  assert.match(code, /name = factory\.Faker/);
});

test('ManyToMany emits post_generation hook', () => {
  const tag = {
    name: 'Tag',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [{ name: 'name', type: 'CharField', args: 'max_length=30', isRelation: false, lineNumber: 2 }],
  };
  const post = {
    name: 'Post',
    appName: 'blog',
    filePath: '/blog/models.py',
    lineNumber: 5,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      {
        name: 'tags',
        type: 'ManyToManyField',
        args: 'Tag',
        isRelation: true,
        relatedModel: 'Tag',
        relationKind: 'ManyToManyField',
        lineNumber: 6,
      },
    ],
  };
  const code = generateFactoryCode(post, indexOf(tag, post));
  assert.match(code, /@factory\.post_generation/);
  assert.match(code, /self\.tags\.add\(item\)/);
});

test('choices=... field prefers Iterator with TODO', () => {
  const model = {
    name: 'Order',
    appName: 'shop',
    filePath: '/shop/models.py',
    lineNumber: 1,
    baseClasses: ['models.Model'],
    meta: {},
    fields: [
      { name: 'status', type: 'CharField', args: "max_length=20, choices=STATUS_CHOICES", isRelation: false, lineNumber: 2 },
    ],
  };
  const code = generateFactoryCode(model, indexOf(model));
  assert.match(code, /status = factory\.Iterator\(\[\.\.\.\]\)/);
  assert.match(code, /TODO: fill from STATUS_CHOICES/);
});
