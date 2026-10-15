const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { appDirFor, isModelSourceRelPath, walkForModels } = require('../out/parser');

test.after(() => {
  Module._load = originalLoad;
});

test('isModelSourceRelPath accepts nested models packages', () => {
  assert.equal(
    isModelSourceRelPath('ai_approval_engine/models/builders/approval_flow.py'),
    true
  );
  assert.equal(
    isModelSourceRelPath('ai_approval_engine/models/requests/components/offer.py'),
    true
  );
  assert.equal(isModelSourceRelPath('ai_approval_engine/models/post.py'), true);
  assert.equal(isModelSourceRelPath('ai_approval_engine/models.py'), true);
  assert.equal(isModelSourceRelPath('ai_approval_engine/abstract_models.py'), true);
  assert.equal(isModelSourceRelPath('ai_approval_engine/models/__init__.py'), true);
  assert.equal(isModelSourceRelPath('ai_api/models/lead/__init__.py'), true);
  assert.equal(isModelSourceRelPath('ai_approval_engine/__init__.py'), false);
  assert.equal(isModelSourceRelPath('ai_approval_engine/views/flow.py'), false);
});

test('appDirFor keeps a nested models package on the owning app', () => {
  const root = '/repo/src';
  const nested = appDirFor(
    '/repo/src/ai_approval_engine/models/builders/approval_flow.py',
    root
  );
  assert.equal(nested.name, 'ai_approval_engine');
  assert.equal(nested.dir, '/repo/src/ai_approval_engine');

  const oneLevel = appDirFor('/repo/src/shop/models/order.py', root);
  assert.equal(oneLevel.name, 'shop');

  const classic = appDirFor('/repo/src/shop/models.py', root);
  assert.equal(classic.name, 'shop');
  assert.equal(classic.dir, '/repo/src/shop');
});

test('appDirFor uses the workspace root when the models package is at the root', () => {
  const root = '/work/ai_approval_engine';
  const app = appDirFor(`${root}/models/builders/approval_flow.py`, root);
  assert.equal(app.name, 'ai_approval_engine');
  assert.equal(app.dir, root);
});

test('walkForModels reads nested modules and package inits, and skips views', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dol-nested-'));
  const files = [
    'ai_approval_engine/models/builders/approval_flow.py',
    'ai_approval_engine/models/requests/components/offer.py',
    'ai_approval_engine/models/__init__.py',
    'ai_approval_engine/__init__.py',
    'ai_approval_engine/models/post.py',
    'ai_approval_engine/models.py',
    'ai_approval_engine/views/flow.py',
  ];
  for (const rel of files) {
    const full = path.join(root, rel);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, '');
  }
  const found = new Set(
    walkForModels(root, () => false).map((p) => path.relative(root, p).split(path.sep).join('/'))
  );
  assert.deepEqual(
    [...found].sort(),
    [
      'ai_approval_engine/models.py',
      'ai_approval_engine/models/__init__.py',
      'ai_approval_engine/models/builders/approval_flow.py',
      'ai_approval_engine/models/post.py',
      'ai_approval_engine/models/requests/components/offer.py',
    ]
  );
});
