const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { modelRules } = require('../../out/rules/models');

test.after(() => {
  Module._load = originalLoad;
});

function makeCtx(source) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    lineCount: lines.length,
    lineAt(i) {
      return lines[i] ?? '';
    },
    windowBefore(i, n) {
      return lines.slice(Math.max(0, i - n), i);
    },
    windowAfter(i, n) {
      return lines.slice(i + 1, Math.min(lines.length, i + 1 + n));
    },
  };
}

function codes(source) {
  const ctx = makeCtx(source);
  return modelRules
    .filter((rule) => ['DOL018', 'DOL019', 'DOL020'].includes(rule.meta.code))
    .flatMap((rule) => rule.check(ctx))
    .map((finding) => finding.code);
}

const ORDER = [
  'class Order(models.Model):',
  '    company = models.ForeignKey("Company", on_delete=models.CASCADE)',
  '    company_name = models.CharField(max_length=100)',
  '    company_id = models.PositiveIntegerField(default=0)',
  '    phone_1 = models.CharField(max_length=20)',
  '    phone_2 = models.CharField(max_length=20)',
  '    phone_3 = models.CharField(max_length=20)',
  '    job_ids = models.TextField(default="")',
].join('\n');

test('DOL018, DOL019 and DOL020 flag the three smells', () => {
  const found = codes(ORDER).sort();
  assert.deepEqual(found, ['DOL018', 'DOL019', 'DOL020']);
});

test('a scalar company_id and a pair of numbered columns stay quiet', () => {
  const source = [
    'class Lead(models.Model):',
    '    company_id = models.PositiveIntegerField(default=0)',
    '    phone_1 = models.CharField(max_length=20)',
    '    phone_2 = models.CharField(max_length=20)',
  ].join('\n');
  assert.deepEqual(codes(source), []);
});

test('a proxy model is not reviewed', () => {
  const source = [
    'class LeadProxy(models.Model):',
    '    job_ids = models.TextField(default="")',
    '    class Meta:',
    '        proxy = True',
  ].join('\n');
  assert.deepEqual(codes(source), []);
});
