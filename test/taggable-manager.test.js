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

test('parses TaggableManager defaults as a many-to-many relation', () => {
  const [post] = parseModelsFile('/project/blog/models.py', `
class Post(models.Model):
    title = models.CharField(max_length=200)
    tags = TaggableManager()
`);
  const tags = post.fields.find((field) => field.name === 'tags');

  assert.equal(tags.type, 'TaggableManager');
  assert.equal(tags.isRelation, true);
  assert.equal(tags.relationKind, 'ManyToManyField');
  assert.equal(tags.relatedModel, 'taggit.Tag');
  assert.equal(tags.throughModel, 'taggit.TaggedItem');
});

test('uses an explicit TaggableManager through model', () => {
  const [post] = parseModelsFile('/project/blog/models.py', `
class Post(models.Model):
    tags = TaggableManager(through=CustomTaggedItem)
`);
  const tags = post.fields.find((field) => field.name === 'tags');

  assert.equal(tags.relatedModel, 'taggit.Tag');
  assert.equal(tags.throughModel, 'CustomTaggedItem');
});
