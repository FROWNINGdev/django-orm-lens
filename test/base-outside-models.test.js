const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { collectDefs, resolveAndFilter, pullImportedBases } = require('../out/parser');

test.after(() => {
  Module._load = originalLoad;
});

// Issue #135: `class Person(MyCustomModel)` with the base in `core/base.py`
// vanished, because only models.py-style files are read and the base had no
// definition to resolve against. Same fixture and the same answers as
// cli/tests/test_base_outside_models.py, so the sidebar and `scan` agree.
const root = path.join(__dirname, 'fixtures', 'base_outside_models');
const modelFiles = ['people/models.py', 'places/models.py'].map((p) => path.join(root, p));

function scan() {
  const defs = modelFiles.flatMap((f) => collectDefs(f, fs.readFileSync(f, 'utf-8')));
  defs.push(...pullImportedBases(defs, [root]));
  return new Map(resolveAndFilter(defs).map((m) => [m.name, m]));
}

const inherited = (m) => m.inheritedFields.map((f) => [f.name, f.inheritedFrom]);

test('without following imports every model is lost — the bug', () => {
  const defs = modelFiles.flatMap((f) => collectDefs(f, fs.readFileSync(f, 'utf-8')));
  assert.deepEqual(resolveAndFilter(defs).map((m) => m.name), []);
});

test('exactly the concrete models are found', () => {
  assert.deepEqual([...scan().keys()].sort(), ['Archive', 'City', 'Located', 'Note', 'Person']);
});

test('a base imported from a plain module', () => {
  assert.deepEqual(inherited(scan().get('Person')), [['created', 'MyCustomModel']]);
});

test('a base behind a re-export, two hops away', () => {
  assert.deepEqual(inherited(scan().get('Archive')), [
    ['created', 'MyCustomModel'],
    ['deleted', 'SoftDeletable'],
  ]);
});

test('a base reached through a module alias', () => {
  assert.deepEqual(inherited(scan().get('Note')), [['created', 'MyCustomModel']]);
});

test('a concrete base via a relative import is a model of its own', () => {
  const models = scan();
  assert.deepEqual(models.get('Located').fields.map((f) => f.name), ['lat', 'lng']);
  assert.equal(models.get('Located').appName, 'places');
  assert.deepEqual(inherited(models.get('City')), []);
});

test('a plain class in the base module does not make a model', () => {
  const models = scan();
  assert.ok(!models.has('Plain'));
  assert.ok(!models.has('NotAModel'));
});

test('files outside the root are never read', () => {
  const defs = modelFiles.flatMap((f) => collectDefs(f, fs.readFileSync(f, 'utf-8')));
  assert.deepEqual(pullImportedBases(defs, [path.join(root, 'places')]).map((m) => m.name), ['Located']);
});
