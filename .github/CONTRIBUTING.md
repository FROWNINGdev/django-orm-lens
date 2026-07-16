# Contributing to Django ORM Lens

Thanks for wanting to help! This project ships across three surfaces (VS Code
extension, Python CLI, MCP server) that all share one parser — so any
improvement usually lands in both `src/` (TypeScript) and `cli/django_orm_lens/`
(Python).

## How to become a contributor (all skill levels welcome)

You do **not** need to write Python or TypeScript to contribute. Every merged
PR — including documentation, translations, screenshots, or a one-line typo
fix — lands you on the [Contributors graph](https://github.com/FROWNINGdev/django-orm-lens/graphs/contributors)
and (once the bot is enabled) in the auto-generated Contributors table at the
bottom of the README.

Concrete first-PR ideas (all labelled [`good first issue`](https://github.com/FROWNINGdev/django-orm-lens/labels/good%20first%20issue)):

- **Translate the README** to your language (RU, ZH, ES already open —
  see issues #9-11). No code involved.
- **Add a screenshot** of the sidebar / ER diagram in your editor. Issue #15.
- **Fix a small CLI paper cut** — issues #8, #12, #14 each take under an hour.
- **Add a golden fixture** from a real Django project (issue #13).
- **Answer a question** on [Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions)
  — help others use the tool and get recognized as a `question` contributor.

All contribution types recognized via the [All Contributors spec](https://allcontributors.org/docs/en/emoji-key):
code, docs, translation, design, ideas, question answers, bug reports, tests,
tutorials, and more.

Once the `@all-contributors` bot is installed on the repo, comment on any
issue or PR to be added:

    @all-contributors please add @your-username for docs

The bot opens a PR that updates the contributors table. Once merged, you're
in permanently.

## Quick paths

- 🐛 **Found a parser edge case?** Open an issue with the smallest `models.py`
  snippet that reproduces it. Bonus points for a failing test.
- 💡 **Have a feature idea?** Start with a
  [Discussion](https://github.com/FROWNINGdev/django-orm-lens/discussions)
  rather than a PR — quicker to align on scope.
- 🛠️ **Want to fix something?** See "Development setup" below.

## Development setup

### VS Code extension (TypeScript)

```bash
npm install
npm run build          # tsc -p ./
npm test               # tsc + node --test
npm run watch          # rebuild on save
```

Press `F5` in VS Code to launch an Extension Development Host with the
uncompiled extension loaded — the tree view and ER diagram render live.

### CLI + MCP server (Python)

```bash
cd cli
pip install -e ".[dev,mcp]"
django-orm-lens scan --path /some/django/project
python -m pytest       # if tests added
```

## Parity rule

The TS parser (`src/parser.ts`) and the Python parser
(`cli/django_orm_lens/parser.py`) emit the same camelCase JSON schema. If you
add a field to one, add it to the other in the same PR — otherwise
downstream consumers (VS Code extension, CLI, MCP tools) diverge.

Shared shapes:
- `ParsedField`: `throughModel`, `onDelete`, `relatedName`, `relationKind`, ...
- `ParsedModel`: `baseClasses`, `meta`, `fields`, ...
- `WorkspaceIndex`: `apps`, `scannedAt`

## Commit and PR conventions

- **One logical change per PR** — makes reviews (and reverts) painless.
- **Reference issues** — `Fixes #12` in the PR body auto-closes on merge.
- **Commit style:** `type(scope): short imperative` (e.g. `feat(parser): extract through=`).
- **CI must be green.** The `CI` workflow runs `npm test` and Python parser
  self-checks on every push and PR.

## Where to look first

| Area | Files |
|---|---|
| Parser core (shared shape source of truth) | `src/parser.ts`, `cli/django_orm_lens/parser.py` |
| VS Code tree view | `src/treeProvider.ts` |
| VS Code hover cards | `src/hoverProvider.ts` |
| VS Code CodeLens | `src/codeLensProvider.ts` |
| Mermaid diagram builder | `src/graphWebview.ts`, `cli/django_orm_lens/cli.py::_build_mermaid` |
| CLI subcommands | `cli/django_orm_lens/cli.py` |
| MCP server | `cli/django_orm_lens/mcp_server.py` |

## Areas that welcome help

Marked with `good first issue` in the tracker:
- Zoom + minimap in the ER diagram webview ([#4](https://github.com/FROWNINGdev/django-orm-lens/issues/4))
- ORM query autocomplete inside `.filter() / .exclude() / .annotate()` ([#3](https://github.com/FROWNINGdev/django-orm-lens/issues/3))

## Getting your PR merged

- CI must pass.
- Add / update a `CHANGELOG.md` entry under a new `[Unreleased]` header for
  user-visible changes.
- If you're a first-time contributor, we'll credit you in the CHANGELOG on
  release — thanks in advance!

## Release checklist (maintainer only)

Every release commit must bump **all three** version-bearing files atomically —
skipping any one causes downstream registry desync (Glama, mcp.so, PyPI, VS Code
Marketplace can each go out of sync independently). This list exists because
`server.json` was silently skipped in four consecutive releases and eventually
tripped a Glama build failure.

- [ ] `cli/pyproject.toml` → `version = "X.Y.Z"` (Python CLI, PyPI)
- [ ] `package.json` → `"version": "A.B.C"` (VS Code extension, Marketplace)
- [ ] `cli/server.json` → **both** top-level `"version"` AND `packages[0].version`
      set to the Python CLI version (MCP Registry → Glama, mcp.so sync)
- [ ] `CHANGELOG.md` → rename `[Unreleased]` → `[A.B.C] + [py-X.Y.Z] - YYYY-MM-DD`
      with combined-release intro paragraph (see `[0.3.5] + [py-1.0.11]` for shape)
- [ ] Release commit message: `release: vA.B.C + py-X.Y.Z — <one-line headline>`
- [ ] Tag both: `git tag vA.B.C && git tag py-vX.Y.Z && git push --tags`
      (each tag triggers its own auto-publish workflow; both must fire for
      Marketplace + PyPI to both update)

## Code of Conduct

Participation in this project is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).
