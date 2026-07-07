# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added
- Initial release.
- Sidebar TreeView grouping apps → models → fields → Meta.
- Field-type-aware icons for CharField, ForeignKey, ManyToManyField, and 20+ built-ins.
- Mermaid-rendered ER diagram in a side webview panel.
- Jump-to-definition on any tree node.
- Auto-refresh via `models.py` file watcher.
- Configurable exclude globs (defaults skip `migrations/`, `venv/`, `node_modules/`).
- Status-bar item showing scanned model count.
