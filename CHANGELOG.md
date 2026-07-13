# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-07-13

### Added
- **`throughModel` on the M2M edge** — Mermaid ER diagrams now render `through=` on `ManyToManyField` relations, e.g. `authors [through Authorship]`. First-time external contribution by [@kingrubic](https://github.com/kingrubic) in [#5](https://github.com/FROWNINGdev/django-orm-lens/pull/5).
- **Listed on [Glama.ai MCP directory](https://glama.ai/mcp/servers/vjrz91hg8o)** — third discovery channel alongside VS Code Marketplace and the official MCP Registry.

## [py-1.0.4] - 2026-07-13

Python package parity release. Extension bumped in parallel to 0.3.1.

### Added
- **`through_model` on `ParsedField`** — Python parser now extracts `through=` from `ManyToManyField(...)` and emits `"throughModel": "..."` in JSON. Matches the TypeScript port field-for-field.

## [py-1.0.3] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.0.

### Added
- **Listed in the official [MCP Registry](https://registry.modelcontextprotocol.io/servers/io.github.FROWNINGdev%2Fdjango-orm-lens)** — the server is now discoverable through the canonical Model Context Protocol directory. MCP-compatible clients can find it by name (`io.github.FROWNINGdev/django-orm-lens`).
- `cli/server.json` — MCP Registry metadata (PyPI package, stdio transport, uvx runtime hint).
- Ownership-verification marker in `cli/README.md` (hidden HTML comment) so the registry can prove the PyPI package is ours.

### Fixed
- 1.0.1: added `on_delete` and `related_name` extraction — kept for parity with the VS Code extension.

## [0.3.0] - 2026-07-13

Ships the terminal + AI-agent story and a batch of ER-diagram / editor polish.

### Added
- **Python CLI + MCP server** — companion package `django-orm-lens` on PyPI. Zero-dep CLI (`scan`, `describe`, `hover`, `list`, `er`) and an optional MCP stdio server exposing five read-only tools to Cursor, Aider, Continue.dev, Zed, and any MCP client. Install: `pip install "django-orm-lens[mcp]"`.
- **CodeLens above every model class** — shows field count, relation count, and an "Open ER diagram" action. Toggle with `djangoOrmLens.showCodeLens`.
- **Edge labels on the ER diagram** — relation arrows now include `on_delete` (CASCADE / SET_NULL / PROTECT) and `related_name` when present, e.g. `author [CASCADE, as posts]`.
- **Diagram theme picker** — `djangoOrmLens.diagramTheme` accepts `auto` (default, follows VS Code theme), `default`, `dark`, `forest`, and `neutral`.

### Fixed
- CI publish workflow was silently failing because of a YAML quoting bug — restored to green; adds a parallel PyPI publish job.

### Docs
- README rewritten around three surfaces: VS Code extension, Python CLI, and MCP server. New Integrations table, updated roadmap, and Support section.

## [0.2.0] - 2026-07-15

The polish release. Consolidates hover, filter, welcome, security hardening, and diagram export into a single minor bump.

### Added
- **Export ER diagram as SVG** — new button in the diagram panel header saves the rendered graph to a file inside your workspace.
- **Welcome view** — when no Django models are found, the sidebar now shows a friendly explanation and a Refresh action instead of a blank panel.
- **Smart tree expansion** — apps start expanded on small projects (<= 40 models) and collapsed on larger ones; a filter always expands to reveal matches.
- **Multi-line class inheritance** — the parser now handles Black-formatted classes where the base list wraps across two or three lines.

### Security
- **jumpToModel path scoping** — the jump command now rejects any target outside the current workspaceFolders. Prevents a crafted models.py from opening arbitrary local files.
- **Hover markdown sanitization** — parser-derived strings are escaped and the trusted-command scope is narrowed to djangoOrmLens.jumpToModel only. Blocks command-URI injection through model or field names.

### Docs

## [0.1.3] - 2026-07-14

### Added
- **Filter tree** — new sidebar buttons and command palette actions (`Django ORM Lens: Filter Models`, `Clear Filter`) let you type a substring and narrow the tree to matching apps, models, and fields in real time. Parent nodes stay visible when a descendant matches.

## [0.1.2] - 2026-07-14

### Added
- **Hover cards** over `ForeignKey('app.Model')`, `OneToOneField(...)`, and `ManyToManyField(...)` references. Hovering a related-model string in the editor now shows a preview of that model (fields, relations, base classes) and a one-click jump link.

## [0.1.1] - 2026-07-13

### Added
- Support for split `models/` package directories (multi-file apps).
- Support for bare field imports (`from django.db.models import CharField`).
- Output channel "Django ORM Lens" for surfaced scan errors.

### Fixed
- Parser now detects indentation width per class instead of assuming 4 spaces (2-space codebases were showing zero fields).
- False-positive base-class detection: `ModelAdmin`, `ModelSerializer`, `ModelForm`, `ResponseModel`, and similar classes are no longer treated as database models.
- Race condition in the workspace scanner: concurrent saves could leave stale results in the tree.
- `Jump to Model` crashed when the target file had been deleted between scan and click — now shows a warning and refreshes.

### Security
- Webview nonce is now generated via `crypto.randomBytes` instead of `Math.random()`.
- Mermaid CDN reference pinned to `10.9.4` (was floating on `mermaid@10`).

## [0.1.0] - 2026-07-07

### Added
- Initial release.
- Sidebar TreeView grouping apps → models → fields → Meta.
- Field-type-aware icons for CharField, ForeignKey, ManyToManyField, and 20+ built-ins.
- Mermaid-rendered ER diagram in a side webview panel.
- Jump-to-definition on any tree node.
- Auto-refresh via `models.py` file watcher.
- Configurable exclude globs (defaults skip `migrations/`, `venv/`, `node_modules/`).
- Status-bar item showing scanned model count.
