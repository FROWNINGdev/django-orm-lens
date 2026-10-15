const Module = require('node:module');
const test = require('node:test');
const assert = require('node:assert/strict');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};
const { parseModelsFile } = require('../out/parser');
test.after(() => {
  Module._load = originalLoad;
});

test('a comment before the first positional argument does not hide the related model', () => {
  const src = [
    'class Rule(models.Model):',
    '    variants = models.ManyToManyField(  # type: ignore[var-annotated]',
    '        "product.ProductVariant", blank=True',
    '    )',
    '    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE)  # keep "#"',
  ].join('\n');
  const [model] = parseModelsFile('/tmp/shop/models.py', src);
  const byName = Object.fromEntries(model.fields.map((f) => [f.name, f]));
  assert.equal(byName.variants.relatedModel, 'product.ProductVariant');
  assert.equal(byName.owner.relatedModel, 'auth.User');
});
