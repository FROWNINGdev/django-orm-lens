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

// Mirrors cli/tests/test_mptt_models.py. The sidebar and the CLI must agree
// about a django-mptt schema, so every assertion here has a counterpart there.

test('recognises MPTTModel as a model base', () => {
  const models = parseModelsFile('/project/catalog/models.py', `
class Category(MPTTModel):
    name = models.CharField(max_length=50)
`);

  assert.equal(models.length, 1);
  assert.equal(models[0].name, 'Category');
  assert.deepEqual(models[0].fields.map((f) => f.name), ['name']);
});

test('parses a self-referential TreeForeignKey as a ForeignKey edge', () => {
  const [category] = parseModelsFile('/project/catalog/models.py', `
class Category(MPTTModel):
    name = models.CharField(max_length=50)
    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, related_name='children')
`);
  const parent = category.fields.find((field) => field.name === 'parent');

  assert.equal(parent.type, 'TreeForeignKey');
  assert.equal(parent.isRelation, true);
  // Reported as the Django field it subclasses, so downstream consumers need
  // no mptt knowledge.
  assert.equal(parent.relationKind, 'ForeignKey');
  assert.equal(parent.relatedModel, 'self');
  assert.equal(parent.onDelete, 'CASCADE');
  assert.equal(parent.relatedName, 'children');
});

test('parses TreeOneToOneField and TreeManyToManyField', () => {
  const [genre] = parseModelsFile('/project/catalog/models.py', `
class Genre(MPTTModel):
    canonical = TreeOneToOneField('Category', on_delete=models.PROTECT)
    tags = TreeManyToManyField('Category', related_name='genres')
`);

  assert.deepEqual(
    genre.fields.map((f) => [f.type, f.relationKind]),
    [
      ['TreeOneToOneField', 'OneToOneField'],
      ['TreeManyToManyField', 'ManyToManyField'],
    ]
  );
  assert.equal(genre.fields[0].onDelete, 'PROTECT');
  assert.equal(genre.fields[1].relatedName, 'genres');
});

test('leaves plain Django relations untouched', () => {
  const [order] = parseModelsFile('/project/shop/models.py', `
class Order(models.Model):
    buyer = models.ForeignKey('User', on_delete=models.CASCADE)
`);
  const buyer = order.fields.find((field) => field.name === 'buyer');

  assert.equal(buyer.type, 'ForeignKey');
  assert.equal(buyer.relationKind, 'ForeignKey');
});
