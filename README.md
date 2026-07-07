<div align="center">

<img src="media/icon.png" width="112" alt="Django ORM Lens" />

# Django ORM Lens

**Your Django models — visible, navigable, and one click away.**

A VS Code sidebar and live ER diagram for every `models.py` in your workspace. No settings.py wiring. No runserver. Just open a Django project and see the whole schema.

[![Version](https://img.shields.io/visual-studio-marketplace/v/frowningdev.django-orm-lens?color=0c4b33&label=marketplace)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/frowningdev.django-orm-lens?color=0c4b33)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Rating](https://img.shields.io/visual-studio-marketplace/r/frowningdev.django-orm-lens?color=0c4b33)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![License: MIT](https://img.shields.io/badge/license-MIT-0c4b33)](LICENSE)
[![CI](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml)

</div>

---

## Why

Django's ORM is powerful, but the schema lives scattered across `apps/*/models.py`. When you're onboarding into a new project — or coming back to your own after two months — you spend the first day just *finding things*.

Django ORM Lens gives you the same big-picture view of your models that Django admin gives your users of the data. In your editor. Without touching your runtime.

## Features

- **📚 Sidebar tree** — every app, every model, every field, grouped by application. Click a field to jump straight to its definition.
- **🕸️ Live ER diagram** — Mermaid-rendered entity-relationship graph of the entire project, updated as you edit.
- **🔍 Field-aware icons** — instantly distinguish `CharField`, `ForeignKey`, `ManyToManyField`, and 20+ built-in types by icon.
- **⚡ Zero configuration** — parses `models.py` directly. No Django introspection, no `DJANGO_SETTINGS_MODULE`, works with a broken venv.
- **🔄 Auto-refresh** — file watcher rescans on save. Add a field → tree updates instantly.
- **🎯 Meta introspection** — `class Meta` options (ordering, unique_together, db_table, verbose_name) surface inline.
- **🧭 Jump to definition** — every node in the tree is clickable and takes you to the exact line.

## Install

```bash
code --install-extension frowningdev.django-orm-lens
```

Or search `Django ORM Lens` in the Extensions marketplace inside VS Code.

## Usage

1. Open a folder containing a Django project (anything with a `manage.py` or `models.py`).
2. Click the **Django ORM Lens** icon in the activity bar.
3. Expand apps → models → fields.
4. Click the graph icon (top-right of the panel) to open the ER diagram in a side view.

## Configuration

| Setting | Type | Default | Description |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | `["**/migrations/**", "**/node_modules/**", "**/venv/**", "**/.venv/**", "**/env/**"]` | Glob patterns to skip when scanning |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | Rescan on `models.py` changes |

## Commands

| Command | Description |
|---|---|
| `Django ORM Lens: Refresh` | Rescan the workspace |
| `Django ORM Lens: Show ER Diagram` | Open the Mermaid ER diagram in a side panel |
| `Django ORM Lens: Jump to Model` | Programmatic — used by tree clicks |

## Roadmap

- [ ] Inline hover cards over `ForeignKey('app.Model')` in the editor
- [ ] Migration graph view (which migrations touch which models)
- [ ] Export ER diagram as SVG/PNG
- [ ] Support for third-party fields (`django-mptt`, `django-model-utils`)
- [ ] Pro tier: custom themes, private cloud share links, team schema diff

If you want any of these sooner — [open an issue](https://github.com/FROWNINGdev/django-orm-lens/issues) or +1 an existing one.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for local dev setup.

Quick start:

```bash
git clone https://github.com/FROWNINGdev/django-orm-lens.git
cd django-orm-lens
npm install
npm run build
# Press F5 in VS Code to launch a dev host
```

## Support the project

If this saved you time, consider:

- ⭐ Starring the [repo](https://github.com/FROWNINGdev/django-orm-lens)
- 💚 Sponsoring on [GitHub Sponsors](https://github.com/sponsors/FROWNINGdev)
- 📝 Rating on the [Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)

## License

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)
