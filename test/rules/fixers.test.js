const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { ALL_FIXERS, findFixersForCode } = require('../../out/rules/fixers');

test.after(() => {
  Module._load = originalLoad;
});

/**
 * Build a minimal document-like object with a single line — enough for
 * fixers that read `document.lineAt(i).text` slices.
 */
function docWithLine(line) {
  return {
    lineAt(_i) {
      return { text: line };
    },
  };
}

test('findFixersForCode returns fixer by code', () => {
  const fixers = findFixersForCode('DOL001');
  assert.equal(fixers.length, 1);
  assert.equal(fixers[0].code, 'DOL001');
});

test('findFixersForCode returns empty for unknown code', () => {
  assert.equal(findFixersForCode('DOL999').length, 0);
});

test('DOL001 fixer produces qs.exists() edit', () => {
  const fixer = findFixersForCode('DOL001')[0];
  const edits = fixer.build({
    finding: {
      code: 'DOL001',
      messageId: 'default',
      range: { line: 0, startCol: 3, endCol: 24 },
      applicability: 'safe',
      fixHint: 'qs',
    },
    document: docWithLine('if qs.count() > 0:'),
  });
  assert.ok(edits);
  assert.equal(edits.length, 1);
  assert.equal(edits[0].newText, 'qs.exists()');
});

test('DOL006 fixer drops list() by returning the inner expression', () => {
  const fixer = findFixersForCode('DOL006')[0];
  const edits = fixer.build({
    finding: {
      code: 'DOL006',
      messageId: 'default',
      range: { line: 0, startCol: 9, endCol: 26 },
      applicability: 'safe',
      fixHint: 'User.objects.all()',
    },
    document: docWithLine('for u in list(User.objects.all()):'),
  });
  assert.ok(edits);
  assert.equal(edits[0].newText, 'User.objects.all()');
});

test('DOL011 fixer swaps null=True for blank=True inside slice', () => {
  const fixer = findFixersForCode('DOL011')[0];
  const line = 'name = models.CharField(max_length=100, null=True)';
  const start = line.indexOf('models.CharField');
  const end = start + 'models.CharField(max_length=100, null=True)'.length;
  const edits = fixer.build({
    finding: {
      code: 'DOL011',
      messageId: 'default',
      range: { line: 0, startCol: start, endCol: end },
      applicability: 'suggestion',
    },
    document: docWithLine(line),
  });
  assert.ok(edits);
  assert.equal(
    edits[0].newText,
    'models.CharField(max_length=100, blank=True)',
  );
});

test('DOL013 fixer inserts on_delete kwarg before closing paren', () => {
  const fixer = findFixersForCode('DOL013')[0];
  const line = 'author = models.ForeignKey(Author)';
  const start = line.indexOf('models.ForeignKey');
  const end = start + 'models.ForeignKey(Author)'.length;
  const edits = fixer.build({
    finding: {
      code: 'DOL013',
      messageId: 'default',
      range: { line: 0, startCol: start, endCol: end },
      applicability: 'suggestion',
    },
    document: docWithLine(line),
  });
  assert.ok(edits);
  assert.equal(
    edits[0].newText,
    'models.ForeignKey(Author, on_delete=models.CASCADE)',
  );
});

test('DOL021 fixer replaces datetime.now() with timezone.now()', () => {
  const fixer = findFixersForCode('DOL021')[0];
  const edits = fixer.build({
    finding: {
      code: 'DOL021',
      messageId: 'default',
      range: { line: 0, startCol: 6, endCol: 20 },
      applicability: 'suggestion',
    },
    document: docWithLine('now = datetime.now()'),
  });
  assert.ok(edits);
  assert.equal(edits[0].newText, 'timezone.now()');
});

test('ALL_FIXERS has expected v0.8 codes', () => {
  const codes = ALL_FIXERS.map((f) => f.code).sort();
  assert.deepEqual(codes, [
    'DOL001',
    'DOL002',
    'DOL003',
    'DOL004',
    'DOL006',
    'DOL008',
    'DOL011',
    'DOL013',
    'DOL014',
    'DOL015',
    'DOL021',
    'DOL022',
  ]);
});
