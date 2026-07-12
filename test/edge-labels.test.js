const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') {
    return {};
  }
  return originalLoad.call(this, request, parent, isMain);
};

const { buildMermaid } = require('../out/graphWebview');
const { parseModelsFile } = require('../out/parser');

test('labels OneToOneField metadata and ManyToManyField through models', () => {
  const models = parseModelsFile('/project/app/models.py', `
class User(models.Model):
    profile = models.OneToOneField(
        'Profile', on_delete=models.CASCADE, related_name='user'
    )

class Profile(models.Model):
    pass

class Group(models.Model):
    members = models.ManyToManyField(
        'User', through='Membership', related_name='groups'
    )

class Membership(models.Model):
    pass
`);
  const mermaid = buildMermaid({
    apps: [{ name: 'app', path: '/project/app', models }],
    scannedAt: 0,
  });

  assert.match(mermaid, /User \|\|--\|\| Profile : "profile \[CASCADE, as user\]"/);
  assert.match(mermaid, /Group \}o--o\{ User : "members \[through Membership, as groups\]"/);
});