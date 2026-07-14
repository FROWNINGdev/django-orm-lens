# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **ReDoS clamp on class-indent detection** — `_detect_class_indent` now clamps the reported indent width to 32 and expands tabs to width 4 before use. A crafted `models.py` with an absurd number of leading spaces (10k+) or a tab that produced a width-mismatched regex could previously build patterns like `\s{20000,}` for the meta-body match and trigger catastrophic backtracking. Fixes both the ReDoS vector and the tab-indent correctness bug (Meta blocks in tab-indented codebases were silently unparsed).

### Fixed
- **Workspace scan no longer aborts on a single broken `models.py`** — `scan_workspace` (Python CLI) and `scanWorkspace` (VS Code extension) previously wrapped both the read AND the parse in one broad try/catch. A parser exception in a single file (e.g. missing `(` after a matched field, malformed multi-line class header) would either abort the whole workspace scan with exit 1 (Python) or silently drop that file's models from the tree (TypeScript). Now the read and parse are caught separately: parse errors log a per-file warning to stderr (Python) or dev-tools console (TypeScript) and scanning continues on the next file.
- **Multi-line class header parser no longer near-loops on malformed signatures** — `_read_multiline_class` used to return `None` when parens closed but the joined buffer didn't match `CLASS_RE`. The caller would then advance by only one line, causing every continuation line of a malformed wrap to be re-evaluated as a potential class header. Now returns `(None, end_index)` so the caller skips past the whole section.
- **`_read_balanced_args` guard for missing `(`** — if a matched field somehow doesn't have `(` on its starting line, `.index("(")` used to raise `ValueError` that propagated out of `parse_models_file` and aborted the entire scan. Now returns an empty args block and the field is captured with no relation metadata.
- **Message handler disposable leak in the ER-diagram webview** — `panel.webview.onDidReceiveMessage(...)` registered its subscription in `context.subscriptions`, but the handler is scoped to the panel's lifetime, not the extension's. Every close/reopen of the diagram panel appended a dead listener to `context.subscriptions` forever. Handler now scoped to the panel's `onDidDispose` cleanup.
- **Watcher listener leak on `autoRefresh` config change + split-module files not watched** — `setupWatcher` disposed the old watcher on config toggle but left the three `onDidChange/Create/Delete` listeners registered in `context.subscriptions` permanently, firing against a disposed watcher. Now tracks a module-level `watcherDisposables` array that fully disposes before re-registering. Same pass also adds a second watcher for `**/models/*.py` — split-module Django apps' sub-files now trigger auto-refresh on save (previously ignored, tree silently went stale on those files).
- **Model-name collision in filtered tree** — two models sharing a name in different apps (a valid Django pattern) collided in the filtered-tree child lookup because identity was matched by `label + kind` only. Now also compares `filePath`, so children resolve to the correct model.

## [0.3.3] - 2026-07-13

### Security
- **Mermaid bundled locally instead of fetched from a CDN** — the ER-diagram webview now loads `mermaid.min.js` from a vendored copy at `media/vendor/`. The `script-src` CSP no longer allows `https://cdn.jsdelivr.net`, and `localResourceRoots` restricts the webview to files under `media/`. Removes a third-party network dependency, works offline, and eliminates supply-chain risk from the CDN.

## [0.3.2] - 2026-07-13

### Security
- **`jumpToModel` workspace check hardened** — the previous manual `.toLowerCase()` prefix comparison was Windows-oriented and could false-positive on case-sensitive filesystems (Linux). Switched to `vscode.workspace.getWorkspaceFolder(uri)`, which VS Code resolves with OS-appropriate case handling. Simpler code, correct on every platform.

## [py-1.0.9] - 2026-07-14

Python package only. VS Code extension unchanged at 0.3.3.

### Added
- **Subtle star ask in the welcome output** — `django-orm-lens` (no args) now closes with a two-line invitation to star the repo if the tool saved a search. Rationale: 134 unique cloners on the 14-day traffic window converted to only 2 stars — infrastructure tools bleed stars silently because users never revisit the repo after `pip install`. A single sentence at the point of first-run gratitude is the smallest touch that closes the loop without becoming spam. No CLI behaviour change.

## [py-1.0.8] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.3.

### Added
- **Friendly welcome when `django-orm-lens` runs without a subcommand** — previously bare invocation printed a cryptic `argparse: the following arguments are required: command` error, killing the pip-install-and-poke-around funnel. Now shows a compact commands table + docs link so a new user immediately sees what to try next.

## [py-1.0.7] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.1.

### Added
- **Mermaid ER edge labels — Python ↔ TypeScript parity** — `django-orm-lens er` and the MCP `er_diagram` tool now emit the same `on_delete`, `through`, and `related_name` metadata as the VS Code diagram. Example: `Book }o--|| Author : "author [CASCADE, as books]"` and `Book }o--o{ Tag : "tags [through BookTag]"`. Previously the Python side stripped all metadata to just the field name.
- **MCP index cache (30s TTL)** — agents chaining multiple tool calls (`list_apps` → `describe_model` → `find_relations`) no longer re-walk the filesystem and re-parse every `models.py` per call. Cache keyed by workspace root; short TTL keeps manual edits visible.

## [py-1.0.6] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.1.

### Changed
- **MCP tool error semantics** — `describe_model` and `find_relations` now raise `ValueError` on missing-model instead of returning a `"error: ..."` string. FastMCP maps this to a protocol-level `isError: true` response, so MCP-compatible agents recognize it as a tool error rather than a successful call with error text.

### Fixed
- **Parser perf** — `_read_balanced_args` was building the args buffer with per-char `str += ch` inside a nested loop (quadratic on multi-line field bodies). Now uses a list + single `"".join`.

## [py-1.0.5] - 2026-07-13

Hotfix release. Python package only. VS Code extension unchanged at 0.3.1.

### Fixed
- **Crash on `ManyToManyField(through=...)`** — `_extract_through_model` was called from `parse_models_file` but never defined, and `through_model` was assigned on `ParsedField` without a matching dataclass field. Any Django project with an M2M `through=` argument would raise `NameError` / `AttributeError` and return an empty index. Both are now declared. Discovered by QA sweep of 1.0.4 with type-design and Python reviewers.

## [0.3.1] - 2026-07-13

### Added
- **`throughModel` on the M2M edge** — Mermaid ER diagrams now render `through=` on `ManyToManyField` relations, e.g. `authors [through Authorship]`. First-time external contribution by [@kingrubic](https://github.com/kingrubic) in [#5](https://github.com/FROWNINGdev/django-orm-lens/pull/5).
- **Listed on [Glama.ai MCP directory](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)** — third discovery channel alongside VS Code Marketplace and the official MCP Registry.

## [py-1.0.4] - 2026-07-13

Python package parity release. Extension bumped in parallel to 0.3.1.

### Added
- **`through_model` on `ParsedField`** — Python parser now extracts `through=` from `ManyToManyField(...)` and emits `"throughModel": "..."` in JSON. Matches the TypeScript port field-for-field.

## [py-1.0.3] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.0.

### Added
- **Listed in the official [MCP Registry](https://registry.modelcontextprotocol.io/)** — the server is now discoverable through the canonical Model Context Protocol directory. MCP-compatible clients can find it by name (`io.github.FROWNINGdev/django-orm-lens`).
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
