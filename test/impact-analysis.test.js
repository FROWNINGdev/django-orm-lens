const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const {
  classifyLine,
  detectLayer,
  layerOf,
  scanFileText,
  sortFindings,
} = require('../out/impactAnalysis');

test.after(() => {
  Module._load = originalLoad;
});

test('detectLayer classifies by path shape', () => {
  assert.equal(detectLayer('/repo/blog/models.py'), 'models');
  assert.equal(detectLayer('/repo/blog/models/post.py'), 'models');
  assert.equal(detectLayer('/repo/blog/serializers.py'), 'serializers');
  assert.equal(detectLayer('/repo/blog/api/serializers_v2.py'), 'serializers');
  assert.equal(detectLayer('/repo/blog/admin.py'), 'admin');
  assert.equal(detectLayer('/repo/blog/views.py'), 'views');
  assert.equal(detectLayer('/repo/blog/viewsets.py'), 'views');
  assert.equal(detectLayer('/repo/blog/urls.py'), 'urls');
  assert.equal(detectLayer('/repo/blog/templates/index.html'), 'templates');
  assert.equal(detectLayer('/repo/blog/tests.py'), 'tests');
  assert.equal(detectLayer('/repo/blog/tests/test_views.py'), 'tests');
  assert.equal(detectLayer('/repo/blog/migrations/0001_initial.py'), 'migrations');
  assert.equal(detectLayer('/repo/blog/random.py'), 'other');
});

test('classifyLine returns undefined on comment lines', () => {
  assert.equal(
    classifyLine('models', '# author = models.ForeignKey(Author)', 'author'),
    undefined,
  );
});

test('classifyLine flags ORM string references as certain', () => {
  const c = classifyLine('views', 'qs.order_by("-author")', 'author');
  assert.equal(c?.confidence, 'certain');
  assert.match(c.reason, /ORM string reference/);
});

test('classifyLine flags fields=[...] tuple as certain', () => {
  const c = classifyLine(
    'admin',
    "list_display = ['id', 'author', 'created']",
    'author',
  );
  assert.equal(c?.confidence, 'certain');
});

test('classifyLine flags template variable as likely', () => {
  const c = classifyLine('templates', '<p>{{ post.author }}</p>', 'author');
  assert.equal(c?.confidence, 'likely');
});

test('classifyLine flags attribute access as likely in Django layer', () => {
  const c = classifyLine('views', 'return obj.author.email', 'author');
  assert.equal(c?.confidence, 'likely');
});

test('classifyLine drops to possibly on unknown layer', () => {
  const c = classifyLine('other', 'obj.author', 'author');
  assert.equal(c?.confidence, 'possibly');
});

test('classifyLine returns undefined when needle absent', () => {
  assert.equal(classifyLine('views', 'return x.title', 'author'), undefined);
});

test('scanFileText finds multiple hits and reports line numbers', () => {
  const py = [
    'from blog.models import Post',
    '',
    'def index(request):',
    '    qs = Post.objects.select_related("author")',
    '    return render(request, "index.html", {"author_qs": qs})',
  ].join('\n');
  const hits = scanFileText('/repo/blog/views.py', py, 'author');
  assert.ok(hits.length >= 1);
  const cert = hits.find((h) => h.confidence === 'certain');
  assert.ok(cert, 'expected at least one certain hit');
  assert.equal(cert.layer, 'views');
});

test('scanFileText tags snippet and column', () => {
  const py = 'x = qs.filter(author__id=1)';
  const [h] = scanFileText('/repo/blog/views.py', py, 'author');
  assert.equal(h.line, 0);
  assert.ok(h.column > 0);
  assert.ok(h.snippet.includes('author__id=1'));
});

test('sortFindings orders by layer, then confidence, then path', () => {
  const findings = [
    {
      layer: 'tests',
      confidence: 'possibly',
      filePath: '/a',
      line: 1,
      column: 0,
      snippet: '',
      reason: '',
    },
    {
      layer: 'models',
      confidence: 'likely',
      filePath: '/b',
      line: 1,
      column: 0,
      snippet: '',
      reason: '',
    },
    {
      layer: 'models',
      confidence: 'certain',
      filePath: '/a',
      line: 1,
      column: 0,
      snippet: '',
      reason: '',
    },
  ];
  findings.sort(sortFindings);
  assert.equal(findings[0].layer, 'models');
  assert.equal(findings[0].confidence, 'certain');
  assert.equal(findings[1].confidence, 'likely');
  assert.equal(findings[2].layer, 'tests');
});

test('layerOf classifies on the workspace-relative path, not the checkout path', () => {
  // Regression: detectLayer matches its patterns anywhere in the string, so a
  // project living under a directory called `tests` used to have every one of
  // its files reported as the tests layer.
  assert.equal(detectLayer('/home/dev/tests/shop/blog/views.py'), 'tests');
  assert.equal(layerOf('blog/views.py'), 'views');
  assert.equal(layerOf('blog/serializers.py'), 'serializers');
  assert.equal(layerOf('blog/admin.py'), 'admin');
});

test('layerOf still honours a tests directory inside the project', () => {
  assert.equal(layerOf('blog/tests/test_views.py'), 'tests');
  assert.equal(layerOf('blog/migrations/0002_x.py'), 'migrations');
});

test('layerOf normalises separators and a leading slash', () => {
  // String.raw, not a plain literal: in 'blog\views.py' the \v is a vertical
  // tab escape, so the test would assert on a string with no backslash in it.
  assert.equal(layerOf(String.raw`blog\views.py`), 'views');
  assert.equal(layerOf('/blog/views.py'), 'views');
  assert.equal(layerOf('models.py'), 'models');
});

test('scanFileText accepts a pre-computed layer', () => {
  const text = 'qs = Post.objects.filter(author__id=1)\n';
  // Absolute path says `tests`; the caller-supplied layer must win.
  const found = scanFileText('/home/dev/tests/shop/blog/views.py', text, 'author', 'views');
  assert.equal(found.length, 1);
  assert.equal(found[0].layer, 'views');
  assert.equal(found[0].confidence, 'certain');
});

test('scanFileText without a layer falls back to the path', () => {
  const text = 'qs = Post.objects.filter(author__id=1)\n';
  const found = scanFileText('/repo/blog/views.py', text, 'author');
  assert.equal(found[0].layer, 'views');
});
