# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `suggest_indexes(app_label, model_name)` MCP tool — static analysis of every filter/exclude/order_by/get/aggregate usage across the workspace, returns field-usage frequency and proposes `Meta.indexes` covering entries. Zero-runtime, no DB, no Django boot. Solves the top Django performance blind spot for AI coding agents.
- `signal_graph()` MCP tool — parses every `@receiver()` decorator and `Signal()` definition in the workspace, returns the sender→signal→handler DAG plus custom-signal send-sites. Surfaces the invisible connections between models that cause the majority of enterprise Django bugs.
- **Golden fixture suite** — parser now tested against real open-source Django projects: Zulip (Apache-2.0, 33 models across `zerver/models/`), Saleor (BSD-3, 19 models across product/order/discount/warehouse), Wagtail (BSD-3, 8 models from `wagtail/models/`), and django-CMS (BSD-3, 3 models from `cms/models/`). Pytest asserts every project scans without error, finds at least 1 model, and the aggregate scan of all vendored fixtures completes under 2 seconds (currently ~11 ms). Credibility: `django-orm-lens` is proven against 63 total models parsed from real-world Django deployments, not synthetic examples. Fixtures live under `cli/tests/fixtures/golden/<project>/<original-path>/models.py` with attribution + fetch date in that directory's README.md.

## [0.4.2] - 2026-07-16

Hotfix. Extension only.

### Fixed
- **Activity-bar icon actually ships in the VSIX now.** A stray `media/*.svg` line in `.vscodeignore` (introduced during the 0.4.0 React Flow packaging pass) silently excluded `media/activitybar.svg` from the published extension. The branded icon rendered in Extension Development Host (files read from repo path directly) but was completely absent from the Marketplace VSIX — VS Code had nothing to draw, so the sidebar slot appeared blank. Ignore pattern replaced with an explicit whitelist (`!media/**/*.png`, `!media/**/*.svg`, `!media/webview/**`).

## [0.4.1] - 2026-07-16

VS Code extension only. Python CLI unchanged.

### Changed
- **Branded activity-bar icon** — replaced the generic Material database cylinder (which rendered as an apparently blank slot at 24×24 in some VS Code themes) with a three-connected-tables silhouette that reads unambiguously as "ORM schema" at any size. Uses `stroke="currentColor"` so the icon inherits VS Code's activity-bar foreground colour on every theme (dark/light/high-contrast). Reload the VS Code window after updating to pick up the new icon — VS Code caches activity-bar SVGs per extension host.

## [0.4.0] + [py-1.0.15] - 2026-07-16

Major visual upgrade for the ER diagram — the VS Code webview now renders every model as an interactive React Flow node instead of a static Mermaid SVG. Drag models around to lay the diagram out the way you think about it, click a node to highlight its inbound and outbound relations, double-click to jump straight to the class in `models.py`. Edges are colour-coded by relation semantics (ForeignKey CASCADE / SET_NULL / PROTECT, OneToOne, ManyToMany with `through=` label) so the on_delete blast radius is visible at a glance. Ships with a minimap, zoom controls, and PNG / SVG export. Automatic hierarchical layout via `elkjs`. Python CLI is unchanged in behaviour — the version bump keeps the extension and CLI shipping together, and the Mermaid emitter (`build_mermaid`) remains available for the CLI `--mermaid` output.

### Added
- **Interactive ER diagram (React Flow)** — replaces Mermaid rendering in the VS Code webview. Draggable nodes with rounded corners, drop shadow, and Inter-family typography. Each node shows `app · Model` header and every field with a colour-coded badge (FK / 1:1 / M2M / plain). Edges are laid out with `elkjs` layered algorithm (`RIGHT` direction, orthogonal routing) so hierarchies read naturally instead of the force-directed mush the previous Mermaid `erDiagram` rendered as workspace size grew.
- **Click-to-focus highlighting** — clicking any model dims unrelated nodes to 35 % opacity, keeps the selected node plus every connected neighbour at full brightness, and animates its edges. Click empty canvas or the same node again to clear.
- **Double-click to jump to source** — double-clicking a node posts `jumpToModel` back to the extension, which opens the `models.py` file in the primary editor column at the model's class line. Reuses the existing message handler contract from the Mermaid webview.
- **PNG + SVG export** — new Export dropdown in the header uses `html-to-image` to serialise the diagram viewport at 2× pixel ratio (PNG) or as inline SVG. Falls back to VS Code's `showSaveDialog` for the target path.
- **MiniMap + zoom controls** — bottom-right minimap (150×100) with the current selection highlighted in the accent colour; bottom-left React Flow zoom controls (zoom in / out / fit view). Both surfaces inherit VS Code panel colours via CSS variables and use a subtle `backdrop-filter: blur(6px)` for the Linear/ChartDB aesthetic.
- **Relation-kind legend** — small footer chip explains the FK CASCADE / SET_NULL / PROTECT / 1:1 / M2M colour palette so you don't have to guess.

### Changed
- **Webview build pipeline now uses esbuild.** New `npm run build:webview` bundles `src/webview/graph.tsx` → `media/webview/graph.js` as a minified IIFE (~1.85 MB raw / ~565 KB gzipped, well under the 3 MB VSIX budget). `npm run build` runs both `build:extension` (tsc) and `build:webview` (esbuild). The webview source under `src/webview/` is excluded from the extension's `tsc` project via `tsconfig.json`.
- **Webview header rebuilt to Linear/Vercel spec** — 48 px tall, subtle 2 px gradient bottom border (`transparent → focus → transparent`), workspace name in the title, app + model count badge, refresh button, and export dropdown.
- **`diagramTheme` config values `default` / `forest` / `neutral` now collapse to the `light` React Flow palette.** The old Mermaid-specific enum values are still accepted for setting compatibility but no longer produce distinct visuals — Mermaid is the only renderer that had those. `auto` and `dark` behave as before.

### Kept
- **Mermaid vendored file (`media/vendor/mermaid.min.js`) stays in the VSIX** in case a user needs to roll back to v0.3.8 by re-enabling the old renderer.
- **CLI `build_mermaid` emitter is unchanged.** The Python CLI still exposes `--mermaid` for terminal / CI consumers, so agents and pipelines that scrape the Mermaid output are unaffected.

## [0.3.8] + [py-1.0.14] - 2026-07-16

Second hotfix on the two 0.3.6 regressions that 0.3.7's partial fix did not fully resolve for users running a single-app workspace ("hello/" opened at the app root). Icon rendered blank on some installs even after the theme-aware SVG rewrite; the workspace scan still came up empty on cold-start when `vscode.workspace.findFiles` returned no results before the file index was warm. This release simplifies the icon glyph and adds a direct filesystem walker fallback so the scan never depends on the file index being ready.

### Fixed
- **Activity-bar icon is now a single centred database glyph that fills the 24×24 canvas.** The v0.3.7 SVG was already `fill="currentColor"`, but the two-shape database + magnifier composition left large empty margins on the left and top, which on some themes (and at some HiDPI scale factors) rendered as an apparently blank slot in the activity bar. Replaced with a codicon-shaped monochrome database drawn from x=4 to x=20, y=2 to y=22 — visually dense across the whole viewbox and unambiguously visible on every theme.
- **Workspace scan now falls back to a direct filesystem walk when `findFiles` returns empty.** Root cause: `vscode.workspace.findFiles` depends on VS Code's internal file index. On `onStartupFinished` activation the index can be cold, and on some Windows single-folder-workspace setups the `**/models.py` glob silently misses depth-0 `models.py` regardless. v0.3.7 tried to work around this by adding a bare `models.py` `RelativePattern` and a 1.5s startup-retry backstop; both still failed for users who open the Django app folder itself. `scanWorkspace` now runs `findFiles` first as the fast path, and if it returns zero URIs walks each workspace folder with `fs.readdirSync` directly, honouring the same exclude-glob defaults (`**/migrations/**`, `**/venv/**`, ...). Fallback runs once per empty scan — no cost when the file index is warm.

### Tests
- Added `cli/tests/test_scan_root.py` — three regression tests covering "app-as-workspace-root" (models.py at depth 0), "project-as-workspace-root" (app one level down), and the `**/migrations/**` exclude at root depth. Locks in that the shared parser behaviour never regresses on the single-app layout.

## [0.3.7] + [py-1.0.13] - 2026-07-16

Hotfix release — closes the two regressions reported against 0.3.6: the activity-bar icon rendered blank (stroke-based SVG that VS Code's activity-bar CSS couldn't theme reliably), and single-app workspaces opened at the app root ("hello/" containing `models.py` directly) came up empty because the include-glob and initial-scan timing both failed the root-file case. TypeScript extension fixes only; Python CLI + MCP server are re-published at the same version for combined-release parity.

### Fixed
- **Activity-bar icon is now visible on every theme.** The previous SVG was a stroke-based line drawing with `fill="none"` on both the root and every shape. VS Code's activity-bar renderer applies its own theme foreground via `fill: currentColor`, which the inline `fill="none"` overrode — the icon rendered as a blank slot on most themes ("I see the panel open but the sidebar icon is gone" — real user report). Icon is now a fill-based database + magnifier drawn with `fill="currentColor"`, matching the codicon convention for activity-bar entries.
- **Workspace with `models.py` at the root now scans on activation.** Two root causes: (1) `vscode.workspace.findFiles('**/models.py', ...)` was expected to match root-level files, but on some setups (notably single-folder workspaces on Windows) the leading `**/` requires at least one path segment and silently skipped `<root>/models.py`. Now uses a `vscode.RelativePattern` per workspace folder with an explicit `models.py` include alongside `**/models.py` and `**/models/*.py`, de-duplicated on `fsPath`. (2) With `onStartupFinished` activation (added in 0.3.6) the initial `refresh()` can race the workspace file index and return zero results before it's warm. Now also re-scans on `TreeView.onDidChangeVisibility` (user clicks the sidebar), on `workspace.onDidChangeWorkspaceFolders`, and once as a 1.5s startup backstop if the first scan came back empty against a non-empty workspace. Manual `Refresh scan` from the welcome view is unaffected and continues to work.

## [0.3.6] + [py-1.0.12] - 2026-07-16

Combined release — migration-dependency debugger for AI agents, always-visible activity-bar icon with empty-state welcome, and a subtle star-ask on MCP startup. Ships the three feature commits accumulated since 0.3.5: the migration DAG tool closes a gap no other Django MCP server addresses (agents can now trace conflict chains without booting Django), while the UX and star-ask improvements close the discoverability/conversion loop between install and star.

### Added
- `describe_migration_dependency` MCP tool — return per-app migration DAG (dependencies, roots, leaves, cross-app deps) from static AST parse, no Django boot. Standout differentiator: no other Django MCP server or graph tool (django-schema-graph, django-extensions graph_models, gts360/django-mcp-server, kitespark/django-mcp, admin-mcp-api) offers migration-conflict introspection without a running Django process.

### Changed
- **MCP server prints a one-line star-ask on startup** (stderr). Mirrors the CLI welcome convention from py-1.0.9. Zero effect on the JSON-RPC protocol (stderr is out-of-band); surfaces in Cursor, Aider, mcp-inspector, and any client that shows server logs.

### Fixed
- **Activity-bar icon now appears on any workspace, not only Django ones.** Previously the extension activated exclusively on `workspaceContains:**/manage.py` or `workspaceContains:**/models.py`, so a user who installed the extension without a Django project open saw no icon and no way to discover the tool ("I installed it and see nothing" — real user report). Added `onStartupFinished` to `activationEvents` so the icon always renders; added a `viewsWelcome` empty-state message explaining the tool looks for `manage.py` / `models.py`, with quick actions to open a folder, refresh the scan, or read docs on GitHub. Django auto-activation on those files is unchanged.

## [0.3.5] + [py-1.0.11] - 2026-07-15

Combined release — Django 5.2 support, cascade blast-radius preview for AI agents, and a reverse-references sidebar action. Feature-set derived from a competitive analysis of `meshy/django-schema-graph` (stale since 2023, Django ≤ 4.1) and MCP peers (`gts360/django-mcp-server`, `kitespark/django-mcp`) — all of which require a running Django process; django-orm-lens keeps the zero-runtime moat.

### Added
- **Django 5.2 support** — new `Framework :: Django :: 5.2` classifier and a CI matrix job (`python-cli`) that runs pytest against Python 3.10-3.12 × Django 4.2-5.2 in parallel with the existing Node/TS build.
- **`cascade_preview` MCP tool** — new tool `cascade_preview(app_label, model_name)` returns inbound relations grouped by `on_delete` behavior into `cascade_kills` / `set_null` / `protected` buckets. Lets AI agents preview a delete's blast radius before acting, using only static parse (no DB, no boot).
- **`on_delete` on inbound relations** — `find_relations` inbound entries now include the `on_delete` value (`CASCADE`, `SET_NULL`, `PROTECT`, `SET_DEFAULT`, `DO_NOTHING`, `RESTRICT`, or `SET` for callable form) extracted via the existing parser helper.
- **VS Code: "Find Reverse References" context action** — right-click any model in the sidebar tree → `Find Reverse References` → QuickPick of every FK/OneToOne/M2M pointing at this model, using the in-memory workspace index (no re-parse).
- **`[full]` optional-dependencies alias** — `pip install "django-orm-lens[full]"` is now equivalent to `[mcp]`; documents the default install as zero-dependency in a pyproject header comment.

### Changed
- **README hero** — added `Works offline. Works on a broken venv. Works on someone else's laptop. Works in CI.` positioning line under the problem section.
- **README comparison table** — added Django version support row (ours 4.0-5.2 · schema-graph 3.2-4.1 stale since 2023 · django-extensions latest) with an explicit stale-since-2023 note for `django-schema-graph`.

## [0.3.4] + [py-1.0.10] - 2026-07-15

Combined release — the parser hardening ships identically in both the VS Code extension and the Python CLI. Product of a 3-round security + stability + type-design + Django-semantics audit.

### Added
- **`on_delete=models.SET(default_value)` callable form now recognised** — previous regex `[A-Z][A-Z_]+` matched only bare identifiers (`CASCADE`, `SET_NULL`, `PROTECT`, etc.) and silently dropped the callable form used to inject a default value on delete. Parser now falls back to matching `on_delete=SET(` and records `"SET"`, so consumers know the field has a dynamic on_delete rather than treating it as absent.

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
