# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
