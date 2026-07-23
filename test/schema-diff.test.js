const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { diffSchemas, diffToMarkdown } = require('../out/schemaDiff');

test.after(() => {
  Module._load = originalLoad;
});

/** Compact ParsedField factory for test readability. */
function field(name, type, args = '', extra = {}) {
  return {
    name,
    type,
    args,
    isRelation: !!extra.isRelation,
    relatedModel: extra.relatedModel,
    relationKind: extra.relationKind,
    onDelete: extra.onDelete,
    relatedName: extra.relatedName,
    throughModel: extra.throughModel,
    lineNumber: extra.lineNumber ?? 1,
  };
}

/** Compact ParsedModel factory. */
function model(appName, name, fields, meta = {}) {
  return {
    name,
    appName,
    filePath: `/${appName}/models.py`,
    lineNumber: 1,
    fields,
    meta,
    baseClasses: ['models.Model'],
  };
}

test('empty vs empty → no events', () => {
  assert.deepEqual(diffSchemas([], []), []);
});

test('AddModel — new model in the new snapshot', () => {
  const events = diffSchemas([], [model('blog', 'Post', [field('title', 'CharField')])]);
  assert.deepEqual(events, [
    { kind: 'AddModel', model: 'Post', appName: 'blog' },
  ]);
});

test('DropModel — model gone in the new snapshot', () => {
  const events = diffSchemas(
    [model('blog', 'Draft', [field('title', 'CharField')])],
    [],
  );
  assert.deepEqual(events, [
    { kind: 'DropModel', model: 'Draft', appName: 'blog' },
  ]);
});

test('AddField and DropField inside a matched model', () => {
  const events = diffSchemas(
    [
      model('blog', 'Post', [
        field('title', 'CharField', 'max_length=100'),
        field('body', 'TextField'),
      ]),
    ],
    [
      model('blog', 'Post', [
        field('title', 'CharField', 'max_length=100'),
        field('slug', 'SlugField'),
      ]),
    ],
  );
  assert.equal(events.length, 1);
  assert.equal(events[0].kind, 'ModifyModel');
  const changes = events[0].changes.map((c) => c.kind).sort();
  assert.deepEqual(changes, ['AddField', 'DropField']);
});

test('ChangeFieldType is emitted for same-name mismatch', () => {
  const events = diffSchemas(
    [model('blog', 'Post', [field('id', 'AutoField', 'primary_key=True')])],
    [model('blog', 'Post', [field('id', 'BigAutoField', 'primary_key=True')])],
  );
  assert.equal(events[0].kind, 'ModifyModel');
  const [c] = events[0].changes;
  assert.equal(c.kind, 'ChangeFieldType');
  assert.equal(c.from, 'AutoField');
  assert.equal(c.to, 'BigAutoField');
});

test('ChangeFieldOption for null=True → null=False (option flip)', () => {
  const events = diffSchemas(
    [
      model('blog', 'Post', [
        field('title', 'CharField', 'max_length=100, null=True'),
      ]),
    ],
    [
      model('blog', 'Post', [
        field('title', 'CharField', 'max_length=100, null=False'),
      ]),
    ],
  );
  const [m] = events;
  const [c] = m.changes;
  assert.equal(c.kind, 'ChangeFieldOption');
  assert.equal(c.option, 'null');
  assert.equal(c.from, 'True');
  assert.equal(c.to, 'False');
});

test('ChangeFieldOption ignores verbose_name / help_text noise', () => {
  const events = diffSchemas(
    [
      model('blog', 'Post', [
        field('title', 'CharField', "max_length=100, verbose_name='Заголовок'"),
      ]),
    ],
    [
      model('blog', 'Post', [
        field('title', 'CharField', "max_length=100, verbose_name='Title'"),
      ]),
    ],
  );
  assert.deepEqual(events, []);
});

test('ChangeRelation — FK target changed', () => {
  const events = diffSchemas(
    [
      model('blog', 'Post', [
        field('author', 'ForeignKey', 'Author, on_delete=models.CASCADE', {
          isRelation: true,
          relatedModel: 'Author',
          relationKind: 'ForeignKey',
        }),
      ]),
    ],
    [
      model('blog', 'Post', [
        field('author', 'ForeignKey', 'User, on_delete=models.CASCADE', {
          isRelation: true,
          relatedModel: 'User',
          relationKind: 'ForeignKey',
        }),
      ]),
    ],
  );
  const [m] = events;
  const changeRel = m.changes.find((c) => c.kind === 'ChangeRelation');
  assert.ok(changeRel);
  assert.match(changeRel.from, /→ Author/);
  assert.match(changeRel.to, /→ User/);
});

test('RenameField — high similarity, same type', () => {
  const events = diffSchemas(
    [model('blog', 'Post', [field('titl', 'CharField', 'max_length=100')])],
    [model('blog', 'Post', [field('title', 'CharField', 'max_length=100')])],
  );
  const [m] = events;
  const rename = m.changes.find((c) => c.kind === 'RenameField');
  assert.ok(rename, 'expected a RenameField');
  assert.equal(rename.from, 'titl');
  assert.equal(rename.to, 'title');
  assert.ok(rename.confidence >= 0.7);
});

test('RenameModel — same fields, different name', () => {
  const events = diffSchemas(
    [
      model('blog', 'BlogPost', [
        field('title', 'CharField', 'max_length=100'),
        field('body', 'TextField'),
      ]),
    ],
    [
      model('blog', 'Post', [
        field('title', 'CharField', 'max_length=100'),
        field('body', 'TextField'),
      ]),
    ],
  );
  const rename = events.find((e) => e.kind === 'RenameModel');
  assert.ok(rename, 'expected RenameModel');
  assert.equal(rename.from, 'BlogPost');
  assert.equal(rename.to, 'Post');
  assert.ok(rename.confidence >= 0.7);
  // Should NOT also emit AddModel/DropModel for the same pair.
  assert.equal(
    events.filter((e) => e.kind === 'AddModel' || e.kind === 'DropModel')
      .length,
    0,
  );
});

test('deterministic ordering: AddModel < DropModel < RenameModel < ModifyModel', () => {
  const events = diffSchemas(
    [
      model('blog', 'Draft', [field('title', 'CharField', 'max_length=100')]),
      model('blog', 'Kept', [field('a', 'CharField', 'max_length=10')]),
    ],
    [
      model('blog', 'Post', [field('title', 'CharField', 'max_length=100')]),
      model('blog', 'Kept', [field('a', 'CharField', 'max_length=20')]),
    ],
  );
  const kinds = events.map((e) => e.kind);
  const idx = { AddModel: 0, DropModel: 1, RenameModel: 2, ModifyModel: 3 };
  for (let i = 1; i < kinds.length; i++) {
    assert.ok(idx[kinds[i - 1]] <= idx[kinds[i]], `order violated at ${i}`);
  }
});

test('diffToMarkdown produces a bulleted, model-grouped PR fragment', () => {
  const md = diffToMarkdown([
    { kind: 'AddModel', model: 'Post', appName: 'blog' },
    {
      kind: 'ModifyModel',
      model: 'User',
      appName: 'auth',
      changes: [
        { kind: 'AddField', name: 'nickname', type: 'CharField' },
        {
          kind: 'ChangeFieldType',
          name: 'id',
          from: 'AutoField',
          to: 'BigAutoField',
        },
      ],
    },
  ]);
  assert.match(md, /### Schema changes/);
  assert.match(md, /blog\.Post/);
  assert.match(md, /auth\.User/);
  assert.match(md, /`nickname`/);
  assert.match(md, /AutoField.*BigAutoField/);
});

test('diffToMarkdown handles empty diff', () => {
  const md = diffToMarkdown([]);
  assert.match(md, /No schema changes/i);
});
