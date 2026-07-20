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

// Regression for issue #25 (jsabater): PEP-526 type annotations between
// the field name and `=` used to break FIELD_RE/BARE_FIELD_RE so typed
// Django/Ninja fields vanished from the sidebar tree and the ER diagram.
const SAMPLE = `
from django.db import models
from django.db.models import CharField, IntegerField


class RevokedToken(models.Model):
    jti: CharField[str] = models.CharField(max_length=32, unique=True)
    revoked_count: IntegerField[int] = IntegerField(default=0)
    label: str = models.CharField(max_length=64)
    note = models.TextField(blank=True)
`;

test('PEP-526 annotated fields are extracted (issue #25)', () => {
  const models = parseModelsFile('auth/models.py', SAMPLE);
  assert.equal(models.length, 1, 'RevokedToken parsed');
  const token = models[0];
  const names = token.fields.map((f) => f.name);
  assert.deepEqual(names, ['jti', 'revoked_count', 'label', 'note']);

  const jti = token.fields.find((f) => f.name === 'jti');
  assert.equal(jti.type, 'CharField');

  const rc = token.fields.find((f) => f.name === 'revoked_count');
  assert.equal(rc.type, 'IntegerField');
});
