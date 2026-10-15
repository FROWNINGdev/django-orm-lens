const assert = require('assert');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { collectDefs } = require('../out/parser');

test.after(() => {
  Module._load = originalLoad;
});

const SOURCE = [
  'from django.db import models',
  'from app.usertypes import BaseForeignKey, BaseOneToOneField, TinyIntegerField',
  '',
  'class Card(models.Model):',
  '    company = BaseForeignKey("ai_api.Company", on_delete=models.CASCADE)',
  '    profile = BaseOneToOneField("Profile", on_delete=models.CASCADE)',
  '    order_number = TinyIntegerField(default=0)',
  '    source_type = PositiveTinyIntegerField(default=1)',
  '    target = GenericForeignKey("content_type", "object_id")',
  '    helper = build_thing(1)',
].join('\n');

test('project-local field classes are parsed, relation subclasses keep their kind', () => {
  const [card] = collectDefs('/proj/app/models.py', SOURCE);
  const byName = Object.fromEntries(card.fields.map((f) => [f.name, f]));
  assert.deepEqual(Object.keys(byName), ['company', 'profile', 'order_number', 'source_type']);
  assert.equal(byName.company.relationKind, 'ForeignKey');
  assert.equal(byName.company.relatedModel, 'ai_api.Company');
  assert.equal(byName.profile.relationKind, 'OneToOneField');
  assert.equal(byName.order_number.isRelation, false);
  assert.equal(byName.source_type.type, 'PositiveTinyIntegerField');
});
