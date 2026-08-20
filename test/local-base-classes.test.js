const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const {
  parseModelsFile,
  collectDefs,
  resolveAndFilter,
} = require('../out/parser');

test.after(() => {
  Module._load = originalLoad;
});

// The recogniser was a fixed list of base names — `models.Model`,
// `Abstract*`, `*Mixin`, `TimeStampedModel` and a few others. A project-local
// abstract base under any other name matched none of them, so every model
// beneath it was invisible to the entire extension: sidebar, ER diagram,
// hover, and every DOL rule. `class Post(TimeStamped)` is about as common as
// Django patterns get.

const names = (src) => parseModelsFile('blog/models.py', src).map((m) => m.name);

test('a subclass of a project-local abstract base is a model', () => {
  const src = `from django.db import models


class TimeStamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Post(TimeStamped):
    title = models.CharField(max_length=200)
`;
  // `TimeStamped` is absent because it is abstract: no table, so nothing for
  // a schema tool to show. That is what the Python CLI has always done, and
  // the two now agree.
  assert.deepEqual(names(src), ['Post']);
});

test('recognition chains through several local bases', () => {
  const src = `from django.db import models


class Base(models.Model):
    class Meta:
        abstract = True


class Auditable(Base):
    updated_by = models.CharField(max_length=50)

    class Meta:
        abstract = True


class Post(Auditable):
    title = models.CharField(max_length=200)
`;
  assert.deepEqual(names(src), ['Post'], 'both bases are abstract, so both drop');
});

test('the subclass keeps its own fields and its declared base', () => {
  const src = `from django.db import models


class TimeStamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Post(TimeStamped):
    title = models.CharField(max_length=200)
    body = models.TextField()
`;
  const post = parseModelsFile('blog/models.py', src).find((m) => m.name === 'Post');
  assert.deepEqual(
    post.fields.map((f) => f.name),
    ['title', 'body']
  );
  assert.deepEqual(post.baseClasses, ['TimeStamped']);
});

// The guard that keeps this from swallowing the file. Recognising a local base
// must not make every class within reach of one a model.
test('a non-model class is still not a model, whatever it subclasses', () => {
  const src = `from django.db import models
from django import forms


class TimeStamped(models.Model):
    class Meta:
        abstract = True


class Post(TimeStamped):
    title = models.CharField(max_length=200)


class PostForm(forms.ModelForm):
    class Meta:
        model = Post


class PostAdmin(admin.ModelAdmin):
    pass
`;
  assert.deepEqual(names(src), ['Post']);
});

test('an unrelated class hierarchy is untouched', () => {
  const src = `class Helper:
    pass


class Other(Helper):
    pass
`;
  assert.deepEqual(names(src), []);
});

// Recognition runs to a fixed point rather than in source order. A class
// written above its base is ordinary code once that base is imported rather
// than declared locally, and an order-dependent pass silently misses it —
// which is what the first version of this fix did.
test('a class written above its base is still recognised', () => {
  const src = `from django.db import models


class Post(TimeStamped):
    title = models.CharField(max_length=200)


class TimeStamped(models.Model):
    class Meta:
        abstract = True
`;
  assert.deepEqual(names(src), ['Post']);
});

// --- inherited fields ------------------------------------------------------

const parse = (src) => parseModelsFile('blog/models.py', src);

const INHERIT_SRC = `from django.db import models


class TimeStamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Post(TimeStamped):
    title = models.CharField(max_length=200)
    updated = models.CharField(max_length=10)
`;

test('inherited fields are kept apart from declared ones', () => {
  const post = parse(INHERIT_SRC).find((m) => m.name === 'Post');
  assert.deepEqual(
    post.fields.map((f) => f.name),
    ['title', 'updated'],
    'fields holds only what the class declares'
  );
  assert.deepEqual(
    post.inheritedFields.map((f) => f.name),
    ['created'],
    'updated is declared on Post, so it shadows the base and is not inherited'
  );
});

test('an inherited field records the base it came from', () => {
  const post = parse(INHERIT_SRC).find((m) => m.name === 'Post');
  assert.equal(post.inheritedFields[0].inheritedFrom, 'TimeStamped');
});

// Multi-table inheritance keeps the parent's columns on the parent's table and
// gives the child a parent_ptr. Copying them onto the child would invent
// columns no migration will ever create.
test('a concrete parent contributes no inherited fields', () => {
  const src = `from django.db import models


class Place(models.Model):
    address = models.CharField(max_length=200)


class Restaurant(Place):
    menu = models.TextField()
`;
  const models = parse(src);
  const restaurant = models.find((m) => m.name === 'Restaurant');
  assert.deepEqual(models.map((m) => m.name), ['Place', 'Restaurant']);
  assert.deepEqual(restaurant.inheritedFields, []);
});

// --- resolving across files ------------------------------------------------

test('a base in another file resolves when the union is passed', () => {
  const base = collectDefs('core/models.py', `from django.db import models


class TimeStamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
`);
  const child = collectDefs('blog/models.py', `from core.models import TimeStamped


class Post(TimeStamped):
    title = models.CharField(max_length=200)
`);
  // Each file alone cannot see the other, which is the whole reason the
  // workspace scan resolves the union rather than one file at a time.
  assert.deepEqual(resolveAndFilter([...child]).map((m) => m.name), []);
  const resolved = resolveAndFilter([...base, ...child]);
  assert.deepEqual(resolved.map((m) => m.name), ['Post']);
  assert.deepEqual(
    resolved[0].inheritedFields.map((f) => f.name),
    ['created'],
    'the field crosses the file boundary too'
  );
});
