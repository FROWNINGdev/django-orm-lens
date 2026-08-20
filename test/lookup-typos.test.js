const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { lookupTypos, nearestName } = require('../out/lookupTypos');

test.after(() => {
  Module._load = originalLoad;
});

const field = (name, type, over = {}) => ({
  name,
  type,
  args: '',
  isRelation: false,
  lineNumber: 1,
  ...over,
});

const model = (name, fields, baseClasses = ['models.Model']) => ({
  name,
  appName: 'blog',
  filePath: 'blog/models.py',
  lineNumber: 1,
  fields,
  inheritedFields: [],
  meta: {},
  baseClasses,
});

const INDEX = {
  scannedAt: 0,
  apps: [
    {
      name: 'blog',
      path: 'blog',
      models: [
        model('Post', [
          field('title', 'CharField'),
          field('published', 'BooleanField'),
          field('author', 'ForeignKey', {
            isRelation: true,
            relatedModel: 'Author',
            relationKind: 'ForeignKey',
            relatedName: 'posts',
          }),
        ]),
        model('Author', [field('name', 'CharField'), field('email', 'EmailField')]),
      ],
    },
  ],
};

const typos = (line) => lookupTypos(line, INDEX);
const one = (line) => {
  const found = typos(line);
  assert.equal(found.length, 1, `expected exactly one finding in: ${line}`);
  return found[0];
};

// --- what it catches -------------------------------------------------------

test('a misspelled field is reported with the name it meant', () => {
  const t = one("Post.objects.filter(titel='x')");
  assert.equal(t.typed, 'titel');
  assert.equal(t.suggestion, 'title');
});

test('the range covers exactly the misspelled segment', () => {
  const line = "Post.objects.filter(titel='x')";
  const t = one(line);
  assert.equal(line.slice(t.startCol, t.endCol), 'titel');
});

test('a misspelling in a later kwarg is found too', () => {
  const t = one("Post.objects.filter(title='x', publishd=True)");
  assert.equal(t.typed, 'publishd');
  assert.equal(t.suggestion, 'published');
});

test('a misspelling across a relation is found', () => {
  const t = one("Post.objects.filter(author__emial='a@b.c')");
  assert.equal(t.typed, 'emial');
  assert.equal(t.suggestion, 'email');
});

test('a misspelled lookup is reported against the lookup list', () => {
  const t = one("Post.objects.filter(title__icontans='x')");
  assert.equal(t.typed, 'icontans');
  assert.equal(t.suggestion, 'icontains');
});

test('exclude and get are checked as well as filter', () => {
  assert.equal(one("Post.objects.exclude(titel='x')").suggestion, 'title');
  assert.equal(one("Post.objects.get(titel='x')").suggestion, 'title');
});

// --- what it refuses to touch ---------------------------------------------
//
// Each of these is a line where a red underline would be wrong. They matter
// more than the cases above: the rule's value is entirely in not crying wolf.

test('a correct lookup is silent', () => {
  assert.deepEqual(typos("Post.objects.filter(title__icontains='x')"), []);
  assert.deepEqual(typos("Post.objects.filter(author__name='a')"), []);
  assert.deepEqual(typos('Post.objects.filter(pk=1)'), []);
});

test('a reverse accessor is silent', () => {
  // `posts` exists only as Post.author's related_name — it is in no model's
  // `fields`, and flagging it was the single likeliest false positive.
  assert.deepEqual(typos("Author.objects.filter(posts__title='x')"), []);
});

test('a name close to nothing is left alone', () => {
  // Unparsed mixin, custom lookup, something from a third-party field — all
  // unrecognised, none of them a misspelling of anything.
  assert.deepEqual(typos("Post.objects.filter(zzzqqq='x')"), []);
});

test('an annotated queryset is not judged at all', () => {
  // `total` is created by the annotation and exists in no model.
  assert.deepEqual(
    typos("Post.objects.annotate(total=Count('x')).filter(total__gt=2)"),
    []
  );
});

test('a Q object suspends the check', () => {
  assert.deepEqual(typos("Post.objects.filter(Q(titel='x'))"), []);
});

test('an unknown model is silent rather than guessed at', () => {
  assert.deepEqual(typos("Ghost.objects.filter(titel='x')"), []);
});

test('a call that is not a manager call is ignored', () => {
  assert.deepEqual(typos("some_dict.update(titel='x')"), []);
  assert.deepEqual(typos("render(request, 't.html', titel='x')"), []);
});

test('an unbalanced line does not throw', () => {
  assert.deepEqual(typos("Post.objects.filter(titel='x'"), []);
});

// --- the near-match rule ---------------------------------------------------

test('a differing first letter is not a suggestion', () => {
  // `witle` is one edit from `title`, but people do not miss the first letter,
  // and allowing it pairs short names off across a whole model.
  assert.equal(nearestName('witle', ['title']), null);
});

test('short names get no slack', () => {
  assert.equal(nearestName('nam', ['name']), 'name', 'distance 1 is fine');
  assert.equal(nearestName('nxyz', ['name']), null, 'distance 2 on a short name is not');
});

test('longer names may be two edits out', () => {
  assert.equal(nearestName('publishd', ['published']), 'published');
  assert.equal(nearestName('pubished', ['published']), 'published');
});

test('an exact match is never a suggestion', () => {
  assert.equal(nearestName('title', ['title', 'titles']), null);
});

test('the closest candidate wins', () => {
  assert.equal(nearestName('titl', ['title', 'titles']), 'title');
});
