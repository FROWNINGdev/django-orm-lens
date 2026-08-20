const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { parseModelsFile } = require('../out/parser');

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
  assert.deepEqual(names(src), ['TimeStamped', 'Post']);
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
  assert.deepEqual(names(src), ['Base', 'Auditable', 'Post']);
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
  assert.deepEqual(names(src), ['TimeStamped', 'Post']);
});

test('an unrelated class hierarchy is untouched', () => {
  const src = `class Helper:
    pass


class Other(Helper):
    pass
`;
  assert.deepEqual(names(src), []);
});

// Python requires the base to exist before the subclass, so a forward
// reference is not valid code — and guessing at one would be the recogniser
// inventing a model the file does not have.
test('a class declared before its base is not retroactively a model', () => {
  const src = `from django.db import models


class Post(TimeStamped):
    title = models.CharField(max_length=200)


class TimeStamped(models.Model):
    class Meta:
        abstract = True
`;
  assert.deepEqual(names(src), ['TimeStamped']);
});
