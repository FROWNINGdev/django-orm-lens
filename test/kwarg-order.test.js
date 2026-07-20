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

// Regression: legacy `extractRelated` used an anchored `^(?:to=)?...` regex,
// so reordered kwargs like `ForeignKey(on_delete=CASCADE, to='User')` returned
// undefined (or worse, `on_delete`). This locks in the lookahead fix so the
// TS parser stays behaviour-compatible with the Python CLI.
const SAMPLE = `
class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    author = models.ForeignKey(
        on_delete=models.CASCADE,
        related_name='books',
        to='Author',
    )
    editor = models.ForeignKey(
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        to='accounts.User',
    )
`;

test('extractRelated resolves to= even when it is not the first kwarg', () => {
  const models = parseModelsFile('blog/models.py', SAMPLE);
  const book = models.find((m) => m.name === 'Book');
  assert.ok(book, 'Book model parsed');

  const author = book.fields.find((f) => f.name === 'author');
  assert.equal(author.relatedModel, 'Author');
  assert.equal(author.onDelete, 'CASCADE');
  assert.equal(author.relatedName, 'books');

  const editor = book.fields.find((f) => f.name === 'editor');
  assert.equal(editor.relatedModel, 'accounts.User');
  assert.equal(editor.onDelete, 'SET_NULL');
});
